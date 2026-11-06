"""Shared finance memory store: schema, revisions, audit, search and MEMORY.md rendering.

The database is the single source of truth. MEMORY.md is a generated index, never
an independently editable fact source: every render is tied to a revision and a
content hash, and can be rebuilt from SQLite at any time.

Connection policy: every operation uses a short-lived connection. The hub holds
the write lock through this class, so writes remain serialized, while readers in
other processes never share a pinned WAL snapshot with the hub. This avoids the
mixed-journal/snapshot failure mode observed when a long-lived connection stayed
open across external commits.

Design contract: docs/MEMORY_AND_TOOL_SHARING_DESIGN.md sections 4 and 7.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from uuid import uuid4

PROJECT_ID = "finance"

# Controlled kinds. Adding a kind is a schema decision, not a free-text field:
# the index renderer and retrieval filters depend on this set.
KINDS = {
    "access": "接入经验：包/服务版本、可用与失败入口、参数与单位陷阱、复现证据",
    "method": "方法与规则索引：公式版本、适用范围、Notion 规则链接与读取要求",
    "research": "研究记忆索引：案例、反例、证据 ID、当时可得时点",
    "handoff": "任务交接：已做/未做、阻断、下一负责人、产物路径与哈希",
    "failure": "失败教训：错误假设、坏数据、无效调用及纠正方式",
    "decision": "有效决策索引：已批准决策的时点、范围与引用（不替代 Notion 规则正文）",
}

VERIFICATIONS = {"candidate", "verified", "disputed", "superseded"}
STATUSES = {"candidate", "published", "rejected", "superseded"}
RESTRICTED_PREFIX = "restricted:"
MAX_SUMMARY = 1000
MAX_CONTENT = 1_000_000

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_records (
  memory_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  entity_ids TEXT NOT NULL DEFAULT '[]',
  summary TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  source_refs TEXT NOT NULL DEFAULT '[]',
  source_agent TEXT NOT NULL,
  run_id TEXT,
  created_at TEXT NOT NULL,
  published_at TEXT,
  available_at TEXT,
  valid_from TEXT,
  valid_to TEXT,
  checked_at TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  verification TEXT NOT NULL DEFAULT 'candidate',
  supersedes TEXT,
  superseded_by TEXT,
  conflicts_with TEXT NOT NULL DEFAULT '[]',
  notion_refs TEXT NOT NULL DEFAULT '[]',
  artifact_refs TEXT NOT NULL DEFAULT '[]',
  visibility TEXT NOT NULL DEFAULT 'project:finance',
  status TEXT NOT NULL DEFAULT 'candidate',
  idempotency_key TEXT UNIQUE,
  decided_by TEXT,
  decided_at TEXT,
  decision_note TEXT,
  text_norm TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_records(status, kind);
CREATE INDEX IF NOT EXISTS idx_memory_revision ON memory_records(revision);
CREATE INDEX IF NOT EXISTS idx_memory_available ON memory_records(available_at);
CREATE TABLE IF NOT EXISTS audit_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  run_id TEXT,
  action TEXT NOT NULL,
  memory_id TEXT,
  revision INTEGER,
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED,
  summary,
  content,
  entity_ids,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    raise ValueError("expected a string or a list of strings")


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


class MemoryStore:
    """Serialized writer via a process-level lock; every operation is its own transaction."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "memory" / "shared.sqlite3"
        self.index_path = self.root / "MEMORY.md"
        self.exports_dir = self.root / "memory" / "exports"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    # ----------------------------------------------------------- connections
    def _connect(self, write: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        if write:
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect(write=True)
            try:
                mode = None
                for _attempt in range(5):
                    mode = conn.execute("PRAGMA journal_mode=WAL").fetchall()[0][0]
                    if str(mode).lower() == "wal":
                        break
                if str(mode).lower() != "wal":
                    raise RuntimeError(
                        f"shared memory database is not in WAL mode (got {mode!r}); "
                        "another process may hold it in a different journal mode"
                    )
                conn.executescript(SCHEMA)
                conn.execute("BEGIN IMMEDIATE")
                for key, value in {
                    "project_id": PROJECT_ID,
                    "revision": "0",
                    "schema_version": "1",
                    "created_at": now_iso(),
                }.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)", (key, value)
                    )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()

    def _q(self, sql: str, params=(), *, one: bool = False):
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return (rows[0] if rows else None) if one else rows
        finally:
            conn.close()

    @contextmanager
    def _tx(self):
        conn = self._connect(write=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ meta
    def meta(self, key: str, default: str | None = None) -> str | None:
        row = self._q("SELECT value FROM meta WHERE key=?", (key,), one=True)
        return row["value"] if row else default

    def revision(self) -> int:
        return int(self.meta("revision", "0"))

    def _bump_revision(self, conn: sqlite3.Connection) -> int:
        conn.execute(
            "UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='revision'"
        )
        row = conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
        return int(row["value"])

    def _audit(self, conn: sqlite3.Connection, action: str, actor: str,
               run_id: str | None, memory_id: str | None, revision: int | None,
               detail: dict) -> None:
        conn.execute(
            "INSERT INTO audit_events(event_id, occurred_at, actor, run_id, action,"
            " memory_id, revision, detail) VALUES(?,?,?,?,?,?,?,?)",
            (f"evt_{uuid4().hex}", now_iso(), actor, run_id, action, memory_id,
             revision, _dumps(detail)),
        )

    # ---------------------------------------------------------------- propose
    def propose(self, *, kind: str, summary: str, content: str = "", source_agent: str,
                run_id: str | None = None, entity_ids=None, source_refs=None,
                artifact_refs=None, notion_refs=None, visibility: str = "project:finance",
                available_at: str | None = None, valid_from: str | None = None,
                valid_to: str | None = None, checked_at: str | None = None,
                verification: str = "candidate", supersedes: str | None = None,
                conflicts_with=None, idempotency_key: str | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; allowed: {sorted(KINDS)}")
        summary = (summary or "").strip()
        if not summary:
            raise ValueError("summary is required")
        if len(summary) > MAX_SUMMARY:
            raise ValueError(f"summary exceeds {MAX_SUMMARY} characters")
        if len(content) > MAX_CONTENT:
            raise ValueError("content exceeds 1,000,000 characters")
        if verification not in VERIFICATIONS - {"superseded"}:
            raise ValueError("verification must be candidate, verified or disputed")
        if not visibility.startswith(("project:", RESTRICTED_PREFIX)):
            raise ValueError("visibility must start with 'project:' or 'restricted:'")
        if not source_agent:
            raise ValueError("source_agent is required")
        entities = _json_list(entity_ids)
        sources = _json_list(source_refs)
        artifacts = _json_list(artifact_refs)
        notions = _json_list(notion_refs)
        conflicts = _json_list(conflicts_with)
        with self._lock:
            if idempotency_key:
                existing = self._q(
                    "SELECT * FROM memory_records WHERE idempotency_key=?", (idempotency_key,),
                    one=True,
                )
                if existing:
                    return {"created": False, "record": self._row(existing, include_content=True),
                            "reason": "idempotency_key already exists"}
            if supersedes and not self.get(supersedes, include_candidates=True):
                raise ValueError(f"supersedes target not found: {supersedes}")
            for conflict in conflicts:
                if not self.get(conflict, include_candidates=True):
                    raise ValueError(f"conflicts_with target not found: {conflict}")
            created = now_iso()
            memory_id = f"mem_{uuid4().hex[:16]}"
            with self._tx() as conn:
                conn.execute(
                    "INSERT INTO memory_records(memory_id, project_id, kind, entity_ids, summary,"
                    " content, source_refs, source_agent, run_id, created_at, available_at,"
                    " valid_from, valid_to, checked_at, verification, supersedes, conflicts_with,"
                    " notion_refs, artifact_refs, visibility, status, idempotency_key, text_norm)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'candidate', ?, ?)",
                    (memory_id, PROJECT_ID, kind, _dumps(entities), summary, content,
                     _dumps(sources), source_agent, run_id, created, available_at, valid_from,
                     valid_to, checked_at or created, verification, supersedes, _dumps(conflicts),
                     _dumps(notions), _dumps(artifacts), visibility, idempotency_key,
                     _normalize(" ".join([summary, content, " ".join(entities), kind]))),
                )
                self._audit(conn, "propose", source_agent, run_id, memory_id, self.revision(),
                            {"kind": kind, "sources": len(sources),
                             "restricted": visibility.startswith(RESTRICTED_PREFIX)})
            return {"created": True, "record": self.get(memory_id, include_candidates=True)}

    # ---------------------------------------------------------------- publish
    def publish(self, memory_id: str, *, actor: str, expected_revision: int | None = None,
                run_id: str | None = None, note: str = "",
                verification: str = "verified",
                conflict_resolution: str | None = None) -> dict:
        if verification not in {"verified", "disputed", "candidate"}:
            raise ValueError("verification must be verified, disputed or candidate")
        with self._lock:
            record = self.get(memory_id, include_candidates=True)
            if not record:
                raise ValueError(f"memory not found: {memory_id}")
            if record["status"] == "rejected":
                raise ValueError("rejected candidates cannot be published")
            current = self.revision()
            if expected_revision is not None and expected_revision != current:
                raise ValueError(
                    f"revision mismatch: expected {expected_revision}, current {current}; "
                    "re-read and retry"
                )
            conflicts = record["conflicts_with"]
            effective_verification = verification
            if conflicts and not conflict_resolution:
                effective_verification = "disputed"
            superseded_ids = [record["supersedes"]] if record["supersedes"] else []
            published_at = now_iso()
            with self._tx() as conn:
                revision = self._bump_revision(conn)
                for old_id in superseded_ids:
                    conn.execute(
                        "UPDATE memory_records SET status='superseded', verification='superseded',"
                        " superseded_by=?, valid_to=COALESCE(valid_to, ?) WHERE memory_id=?",
                        (memory_id, published_at, old_id),
                    )
                    conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (old_id,))
                    self._audit(conn, "supersede", actor, run_id, old_id, revision,
                                {"superseded_by": memory_id})
                conn.execute(
                    "UPDATE memory_records SET status='published', verification=?, revision=?,"
                    " published_at=?, decided_by=?, decided_at=?, decision_note=?,"
                    " available_at=COALESCE(available_at, ?),"
                    " checked_at=COALESCE(checked_at, ?),"
                    " text_norm=? WHERE memory_id=?",
                    (effective_verification, revision, published_at, actor, published_at, note,
                     published_at, published_at,
                     _normalize(" ".join([record["summary"], record["content"],
                                          " ".join(record["entity_ids"]), record["kind"]])),
                     memory_id),
                )
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
                conn.execute(
                    "INSERT INTO memory_fts(memory_id, summary, content, entity_ids)"
                    " VALUES(?,?,?,?)",
                    (memory_id, record["summary"], record["content"],
                     " ".join(record["entity_ids"])),
                )
                self._audit(conn, "publish", actor, run_id, memory_id, revision,
                            {"verification": effective_verification,
                             "conflicts": conflicts,
                             "conflict_resolution": conflict_resolution,
                             "supersedes": superseded_ids})
            self.render_index(actor=actor, run_id=run_id)
            updated = self.get(memory_id, include_candidates=True)
            updated["revision"] = revision
            return {"memory_id": memory_id, "revision": revision,
                    "verification": effective_verification, "record": updated}

    def reject(self, memory_id: str, *, actor: str, note: str = "",
               run_id: str | None = None) -> dict:
        with self._lock:
            record = self.get(memory_id, include_candidates=True)
            if not record:
                raise ValueError(f"memory not found: {memory_id}")
            if record["status"] == "published":
                raise ValueError("published records must be superseded, not rejected")
            revision = self.revision()
            with self._tx() as conn:
                conn.execute(
                    "UPDATE memory_records SET status='rejected', decided_by=?, decided_at=?,"
                    " decision_note=? WHERE memory_id=?",
                    (actor, now_iso(), note, memory_id),
                )
                self._audit(conn, "reject", actor, run_id, memory_id, revision, {"note": note})
            self.render_index(actor=actor, run_id=run_id)
            return {"memory_id": memory_id, "status": "rejected", "revision": revision}

    # ------------------------------------------------------------------ read
    def _row(self, row: sqlite3.Row, include_content: bool = False) -> dict:
        record = {
            "memory_id": row["memory_id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "entity_ids": json.loads(row["entity_ids"]),
            "summary": row["summary"],
            "source_refs": json.loads(row["source_refs"]),
            "source_agent": row["source_agent"],
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "published_at": row["published_at"],
            "available_at": row["available_at"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "checked_at": row["checked_at"],
            "revision": row["revision"],
            "verification": row["verification"],
            "supersedes": row["supersedes"],
            "superseded_by": row["superseded_by"],
            "conflicts_with": json.loads(row["conflicts_with"]),
            "notion_refs": json.loads(row["notion_refs"]),
            "artifact_refs": json.loads(row["artifact_refs"]),
            "visibility": row["visibility"],
            "status": row["status"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
            "decision_note": row["decision_note"],
        }
        if include_content:
            record["content"] = row["content"]
        return record

    def get(self, memory_id: str, *, include_candidates: bool = False) -> dict | None:
        row = self._q(
            "SELECT * FROM memory_records WHERE memory_id=?", (memory_id,), one=True
        )
        if not row:
            return None
        if row["status"] in {"candidate", "rejected"} and not include_candidates:
            return None
        return self._row(row, include_content=True)

    def _acl(self, include_restricted: bool) -> str:
        if include_restricted:
            return ""
        return " AND visibility NOT LIKE 'restricted:%'"

    def search(self, query: str = "", *, kind: str | None = None, entity: str | None = None,
               as_of: str | None = None, limit: int = 10, include_history: bool = False,
               include_restricted: bool = False, include_candidates: bool = False) -> dict:
        limit = max(1, min(int(limit), 50))
        clauses = ["project_id=?"]
        params: list = [PROJECT_ID]
        if include_candidates:
            clauses.append("status IN ('published','superseded','candidate')")
        elif include_history:
            clauses.append("status IN ('published','superseded')")
        else:
            clauses.append("status='published'")
        if kind:
            if kind not in KINDS:
                raise ValueError(f"unknown kind {kind!r}")
            clauses.append("kind=?")
            params.append(kind)
        if entity:
            clauses.append("entity_ids LIKE ?")
            params.append(f'%"{entity}"%')
        if as_of:
            # Point-in-time: a record may only be used if it was available then.
            # Unknown availability is excluded rather than silently assumed.
            clauses.append("available_at IS NOT NULL AND available_at <= ?")
            params.append(as_of)
        security = self._acl(include_restricted)
        mode = "filters"
        query = (query or "").strip()
        if query:
            if CJK.search(query) or len(query) < 2:
                clauses.append("text_norm LIKE ? ESCAPE '\\'")
                params.append("%" + query.lower().replace("\\", "\\\\").replace("%", "\\%")
                              .replace("_", "\\_") + "%")
                mode = "substring"
            else:
                tokens = [tok for tok in re.split(r"\s+", query) if tok]
                match = " ".join('"' + tok.replace('"', '""') + '"*' for tok in tokens)
                clauses.append("memory_id IN (SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?)")
                params.append(match)
                mode = "fts5"
        sql = (
            "SELECT * FROM memory_records WHERE " + " AND ".join(clauses) + security
            + " ORDER BY revision DESC, checked_at DESC LIMIT ?"
        )
        rows = self._q(sql, (*params, limit))
        hits = []
        for row in rows:
            item = self._row(row)
            item["summary_only"] = True
            hits.append(item)
        total = self._q(
            "SELECT COUNT(*) FROM memory_records WHERE " + " AND ".join(clauses) + security,
            params, one=True,
        )[0]
        return {"query": query, "mode": mode, "revision": self.revision(),
                "returned": len(hits), "matching": total, "hits": hits,
                "restricted_included": include_restricted}

    def changes(self, since_revision: int = 0, *, limit: int = 50,
                include_restricted: bool = False) -> dict:
        limit = max(1, min(int(limit), 200))
        security = self._acl(include_restricted)
        rows = self._q(
            "SELECT * FROM memory_records WHERE revision > ? AND status IN"
            " ('published','superseded')" + security + " ORDER BY revision ASC LIMIT ?",
            (since_revision, limit),
        )
        events = self._q(
            "SELECT seq, event_id, occurred_at, actor, run_id, action, memory_id, revision,"
            " detail FROM audit_events WHERE revision > ? ORDER BY seq ASC LIMIT ?",
            (since_revision, limit),
        )
        return {
            "since_revision": since_revision,
            "revision": self.revision(),
            "records": [self._row(row) for row in rows],
            "events": [dict(event) for event in events],
        }

    def counts(self, *, include_restricted: bool = True) -> dict:
        security = "" if include_restricted else self._acl(False)
        rows = self._q(
            "SELECT status, COUNT(*) AS n FROM memory_records WHERE project_id=?" + security
            + " GROUP BY status", (PROJECT_ID,)
        )
        by_status = {row["status"]: row["n"] for row in rows}
        by_kind = {}
        for row in self._q(
            "SELECT kind, COUNT(*) AS n FROM memory_records WHERE status='published' AND project_id=?"
            + security + " GROUP BY kind", (PROJECT_ID,)
        ):
            by_kind[row["kind"]] = row["n"]
        restricted = self._q(
            "SELECT COUNT(*) FROM memory_records WHERE status='published'"
            " AND visibility LIKE 'restricted:%'", one=True,
        )[0]
        return {"status": by_status, "published_by_kind": by_kind,
                "restricted_published": restricted, "revision": self.revision()}

    # ----------------------------------------------------------------- index
    def render_index(self, *, actor: str = "system", run_id: str | None = None) -> dict:
        revision = self.revision()
        counts = self.counts()
        rows = self._q(
            "SELECT memory_id, kind, summary, verification, revision, checked_at, source_agent"
            " FROM memory_records WHERE status='published' AND visibility NOT LIKE 'restricted:%'"
            " ORDER BY kind, revision DESC"
        )
        superseded = self._q(
            "SELECT memory_id, kind, summary, superseded_by FROM memory_records"
            " WHERE status='superseded' AND visibility NOT LIKE 'restricted:%'"
            " ORDER BY revision DESC LIMIT 50"
        )
        generated = now_iso()
        lines = [
            "<!-- generated by tools/memory_store.py from memory/shared.sqlite3; do not edit by hand -->",
            "# finance 共享记忆索引",
            "",
            f"- project_id: `{PROJECT_ID}`",
            f"- revision: `{revision}`",
            f"- generated_at: `{generated}`",
            "- database: `memory/shared.sqlite3`",
            f"- published: `{counts['status'].get('published', 0)}` · candidates pending: "
            f"`{counts['status'].get('candidate', 0)}` · superseded: "
            f"`{counts['status'].get('superseded', 0)}` · rejected: "
            f"`{counts['status'].get('rejected', 0)}`",
            f"- restricted records (not expanded here): `{counts['restricted_published']}`",
            "",
            "读取要求：先调用 `project_bootstrap` 取得当前 revision 与服务状态，再按问题、主体、时点",
            "调用 `memory_search`，命中后用 `memory_get` 读取正文与来源。本文件只是索引，不替代",
            "Notion 规则正文、原始证据或运行时验证；执行 Agent 只能 `memory_propose` 候选，",
            "发布由记忆管理者完成。",
            "",
        ]
        for kind, description in KINDS.items():
            entries = [row for row in rows if row["kind"] == kind]
            if not entries:
                continue
            lines.append(f"## {kind} — {description}")
            lines.append("")
            for row in entries:
                lines.append(
                    f"- `{row['memory_id']}` {row['summary']} "
                    f"({row['verification']}, rev {row['revision']}, "
                    f"checked {row['checked_at'] or 'unknown'})"
                )
            lines.append("")
        if superseded:
            lines.append("## 已被取代（保留证据，不进入默认检索）")
            lines.append("")
            for row in superseded:
                lines.append(
                    f"- `{row['memory_id']}` {row['summary']} → superseded_by "
                    f"`{row['superseded_by'] or 'unknown'}`"
                )
            lines.append("")
        lines += [
            "---",
            "",
            "候选与审计事件保存在 SQLite 中，不写入本索引；用 `memory_search`/`memory_changes` "
            "或 `tools/memory_admin.py` 查看。",
        ]
        text = "\n".join(lines) + "\n"
        payload = text.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        temp = self.index_path.with_suffix(".md.tmp")
        temp.write_bytes(payload)
        os.replace(temp, self.index_path)
        snapshot = self.exports_dir / f"MEMORY.r{revision:06d}.md"
        if not snapshot.exists():
            snapshot.write_bytes(payload)
        with self._lock:
            with self._tx() as conn:
                for key, value in {
                    "memory_md_sha256": digest,
                    "memory_md_revision": str(revision),
                    "memory_md_generated_at": generated,
                }.items():
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES(?, ?)"
                        " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
                    )
                self._audit(conn, "render_index", actor, run_id, None, revision,
                            {"sha256": digest, "bytes": len(payload)})
        return {"revision": revision, "sha256": digest, "bytes": len(payload),
                "path": str(self.index_path), "generated_at": generated,
                "snapshot": str(snapshot)}

    def rebuild(self) -> dict:
        """Rebuild the FTS index and MEMORY.md from SQLite (crash recovery path)."""
        with self._lock:
            sources = self._q(
                "SELECT memory_id, summary, content, entity_ids FROM memory_records"
                " WHERE status='published'"
            )
            with self._tx() as conn:
                conn.execute("DELETE FROM memory_fts")
                conn.executemany(
                    "INSERT INTO memory_fts(memory_id, summary, content, entity_ids)"
                    " VALUES(?,?,?,?)",
                    [(row["memory_id"], row["summary"], row["content"],
                      " ".join(json.loads(row["entity_ids"]))) for row in sources],
                )
            rendered = self.render_index(actor="system")
        return {"rebuilt": True, **rendered}

    def db_digest(self) -> str:
        parts = [sha256_file(self.db_path)]
        wal = Path(str(self.db_path) + "-wal")
        if wal.exists():
            parts.append(sha256_file(wal))
        return hashlib.sha256("".join(parts).encode()).hexdigest()

    def integrity_check(self) -> str:
        rows = self._q("PRAGMA integrity_check")
        if len(rows) == 1 and rows[0][0] == "ok":
            return "ok"
        return "; ".join(str(row[0]) for row in rows) or "unknown"

    def diagnostics(self) -> dict:
        """State for staleness diagnosis and doctor checks (no long-lived connection)."""
        row = self._q("SELECT value FROM meta WHERE key='revision'", one=True)
        conn = self._connect()
        try:
            journal = conn.execute("PRAGMA journal_mode").fetchall()[0][0]
            data_version = conn.execute("PRAGMA data_version").fetchall()[0][0]
        finally:
            conn.close()
        return {
            "db_path": str(self.db_path),
            "db_digest": self.db_digest(),
            "revision": self.revision(),
            "meta_revision_raw": row[0] if row else None,
            "data_version": data_version,
            "journal_mode": journal,
            "in_transaction": False,
            "connection_policy": "short-lived per operation",
            "integrity": self.integrity_check(),
            "record_count": self._q("SELECT COUNT(*) FROM memory_records", one=True)[0],
        }

    def close(self) -> None:
        """No persistent connection is held; kept for API compatibility."""
        return None
