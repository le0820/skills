"""Memory-manager CLI for finance shared memory.

Execution agents use the hub's memory tools instead. This CLI is the explicit
maintenance path for reviewing/publishing candidates and rebuilding the index;
it reads the same SQLite database under the same revision rules.

Every mutation is audited with actor, run id and revision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hub_common import (  # noqa: E402
    HubConfig,
    HubPaths,
    health,
    hub_tool_call,
    pid_alive,
    read_state,
    sha256_path,
)
from memory_store import KINDS, MemoryStore  # noqa: E402


def _hub_state(paths: HubPaths) -> dict | None:
    """A healthy hub is the only writer; direct writes are a stopped-hub fallback."""
    state = read_state(paths.state_file)
    if (state and state.get("phase") == "ready" and pid_alive(state.get("pid", 0))
            and health(state.get("health_url", ""), state.get("token", ""))):
        return state
    return None


def _manager(config: HubConfig, actor: str) -> dict:
    role = config.agent_role(actor)
    if not role.get("can_publish"):
        raise SystemExit(f"actor {actor!r} has role {role.get('role')!r} without can_publish; "
                         "add an explicit role in config/agents.toml if this is the manager")
    return role


def _print(payload, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    def render(value, indent=0):
        pad = "  " * indent
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    print(f"{pad}{key}:")
                    render(item, indent + 1)
                else:
                    print(f"{pad}{key}: {item}")
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    print(f"{pad}-")
                    render(item, indent + 1)
                else:
                    print(f"{pad}- {item}")
        else:
            print(f"{pad}{value}")

    render(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--actor", default="finance-admin")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run-id", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list records by status/kind")
    listing.add_argument("--status", default=None,
                         choices=["candidate", "published", "rejected", "superseded"])
    listing.add_argument("--kind", default=None, choices=sorted(KINDS))
    listing.add_argument("--limit", type=int, default=50)

    show = sub.add_parser("show", help="show one record with content")
    show.add_argument("memory_id")

    search = sub.add_parser("search", help="search published memory")
    search.add_argument("query")
    search.add_argument("--kind", default=None, choices=sorted(KINDS))
    search.add_argument("--as-of", default=None)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--include-restricted", action="store_true")

    publish = sub.add_parser("publish", help="publish a reviewed candidate")
    publish.add_argument("memory_id")
    publish.add_argument("--expected-revision", type=int, default=None)
    publish.add_argument("--verification", default="verified",
                         choices=["verified", "disputed", "candidate"])
    publish.add_argument("--conflict-resolution", default=None)
    publish.add_argument("--note", default="")

    reject = sub.add_parser("reject", help="reject a candidate")
    reject.add_argument("memory_id")
    reject.add_argument("--note", default="")

    sub.add_parser("rebuild", help="rebuild FTS index and MEMORY.md from SQLite")
    sub.add_parser("status", help="database status, counts and index hashes")

    args = parser.parse_args()
    paths = HubPaths(args.root.resolve())
    config = HubConfig(paths.root)
    store = MemoryStore(paths.root)

    if args.command in {"publish", "reject", "rebuild"}:
        _manager(config, args.actor)
    if args.command == "list":
        clauses = ["1=1"]
        params: list = []
        if args.status:
            clauses.append("status=?")
            params.append(args.status)
        if args.kind:
            clauses.append("kind=?")
            params.append(args.kind)
        rows = store._q(
            "SELECT memory_id, status, kind, summary, revision, verification, source_agent,"
            " visibility FROM memory_records WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?", (*params, args.limit)
        )
        payload = {"records": [dict(row) for row in rows], "revision": store.revision(),
                   "counts": store.counts()}
    elif args.command == "show":
        record = store.get(args.memory_id, include_candidates=True)
        if not record:
            raise SystemExit(f"not found: {args.memory_id}")
        payload = record
    elif args.command == "search":
        payload = store.search(args.query, kind=args.kind, as_of=args.as_of,
                               limit=args.limit,
                               include_restricted=args.include_restricted)
    elif args.command in {"publish", "reject"}:
        state = _hub_state(paths)
        if state:
            # Serialized single-writer path. The hub also enforces the manager
            # role, so the CLI cannot silently bypass the memory-manager flow.
            params = {"memory_id": args.memory_id,
                      "decision": "publish" if args.command == "publish" else "reject",
                      "note": args.note}
            if args.command == "publish":
                params["verification"] = args.verification
                if args.expected_revision is not None:
                    params["expected_revision"] = args.expected_revision
                if args.conflict_resolution:
                    params["conflict_resolution"] = args.conflict_resolution
            payload = asyncio.run(hub_tool_call(state, args.actor, "memory_publish", params))
            payload["via"] = "hub"
        else:
            print("warning: hub is not running; writing directly to SQLite in "
                  "single-writer maintenance mode", file=sys.stderr)
            if args.command == "publish":
                payload = store.publish(args.memory_id, actor=args.actor,
                                        expected_revision=args.expected_revision,
                                        run_id=args.run_id, note=args.note,
                                        verification=args.verification,
                                        conflict_resolution=args.conflict_resolution)
                payload.pop("record", None)
            else:
                payload = store.reject(args.memory_id, actor=args.actor, note=args.note,
                                       run_id=args.run_id)
            payload["via"] = "local-sqlite"
        payload["index"] = {"path": str(paths.memory_md),
                            "sha256": sha256_path(paths.memory_md)}
    elif args.command == "rebuild":
        payload = store.rebuild()
    else:  # status
        payload = {
            "db_path": str(paths.memory_db),
            "revision": store.revision(),
            "integrity": store.integrity_check(),
            "counts": store.counts(),
            "index_path": str(paths.memory_md),
            "index_sha256": sha256_path(paths.memory_md),
            "index_revision": store.meta("memory_md_revision"),
            "kinds": KINDS,
        }
    _print(payload, args.json)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
