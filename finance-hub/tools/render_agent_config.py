"""Generate and merge the single `finance_hub` adapter for each Agent client.

The installer never rewrites unrelated configuration. It:
  1. reads the target config,
  2. backs it up under runs/setup/finance-hub/config-backup/<stamp>/,
  3. inserts exactly one finance_hub entry (textual insertion for DSH so the
     rest of the file stays byte-identical),
  4. re-parses the result and verifies that every pre-existing entry survived
     and exactly one finance_hub entry exists.

Default is a dry run. `--write` performs the change; writing outside the
project workspace needs the operator's file-access approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hub_common import HubConfig, HubPaths  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DSH_CONFIG = Path.home() / ".dsh" / "cordis.patch.yml"
ENTRY_ID = "finance-hub"
SERVER_NAME = "finance_hub"
PLUGIN_NAME = "@deepseek-ai/dsh-mcp-client"
AGENT_BY_CLIENT = {"dsh": "deepseek-harness", "codex": "codex", "opencode": "opencode"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dsh_entry(root: Path, agent: str, client: str, timeout_ms: int = 180000) -> dict:
    return {
        "id": ENTRY_ID,
        "name": PLUGIN_NAME,
        "config": {
            "serverName": SERVER_NAME,
            "transport": "stdio",
            "command": str(root / ".venv" / "bin" / "python"),
            "args": [str((root / "tools" / "hub_client.py").resolve())],
            "cwd": str(root.resolve()),
            "toolCallTimeoutMs": timeout_ms,
            "env": {
                "FINANCE_HUB_ROOT": str(root.resolve()),
                "FINANCE_AGENT": agent,
                "FINANCE_CLIENT": client,
            },
        },
    }


def render_entry(entry: dict, indent: str = "    ") -> str:
    """Deterministic YAML block for the mcp-client entry (scalars only)."""
    cfg = entry["config"]
    # `config:` sits at indent+2; its mapping must be indented one level deeper.
    children = indent + "    "
    lines = [
        f"{indent}- id: {entry['id']}",
        f"{indent}  name: \"{entry['name']}\"",
        f"{indent}  config:",
        f"{children}serverName: {cfg['serverName']}",
        f"{children}transport: {cfg['transport']}",
        f"{children}command: {cfg['command']}",
        f"{children}args:",
        f"{children}  - {cfg['args'][0]}",
        f"{children}cwd: {cfg['cwd']}",
        f"{children}toolCallTimeoutMs: {cfg['toolCallTimeoutMs']}",
        f"{children}env:",
    ]
    for key, value in cfg["env"].items():
        lines.append(f"{children}  {key}: \"{value}\"")
    return "\n".join(lines) + "\n"


def find_finance_entries(document) -> list[dict]:
    found = []
    if not isinstance(document, list):
        return found
    for layer in document:
        if not isinstance(layer, dict):
            continue
        items = layer.get("insert") if "insert" in layer else [layer]
        for item in items or []:
            if not isinstance(item, dict):
                continue
            cfg = item.get("config") or {}
            if cfg.get("serverName") == SERVER_NAME or item.get("id") == ENTRY_ID:
                found.append(item)
    return found


def entry_ids(document) -> list[tuple]:
    pairs = []
    if not isinstance(document, list):
        return pairs
    for layer in document:
        if not isinstance(layer, dict):
            continue
        items = layer.get("insert") if "insert" in layer else [layer]
        for item in items or []:
            if isinstance(item, dict):
                pairs.append((item.get("id"), item.get("name")))
    return pairs


def merge_text(original: str, block: str) -> str:
    lines = original.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() == "- insert:":
            return "".join(lines[: index + 1]) + block + "".join(lines[index + 1:])
    if original and not original.endswith("\n"):
        original += "\n"
    return original + "- insert:\n" + block


def adapter_snippets(root: Path) -> dict:
    dsh = render_entry(dsh_entry(root, "deepseek-harness", "dsh")).rstrip()
    codex = (
        "# Codex project .codex/config.toml (apply only after project trust and a fresh-session test)\n"
        "[mcp_servers.finance_hub]\n"
        f"command = \"{root / '.venv' / 'bin' / 'python'}\"\n"
        f"args = [\"{(root / 'tools' / 'hub_client.py').resolve()}\"]\n"
        f"cwd = \"{root.resolve()}\"\n"
        "startup_timeout_sec = 180.0\n"
        "tool_timeout_sec = 180.0\n\n"
        "[mcp_servers.finance_hub.env]\n"
        f"FINANCE_HUB_ROOT = \"{root.resolve()}\"\n"
        "FINANCE_AGENT = \"codex\"\n"
        "FINANCE_CLIENT = \"codex\"\n"
    )
    opencode = json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                SERVER_NAME: {
                    "type": "local",
                    "command": [str(root / ".venv" / "bin" / "python"),
                                str((root / "tools" / "hub_client.py").resolve())],
                    "environment": {"FINANCE_HUB_ROOT": str(root.resolve()),
                                    "FINANCE_AGENT": "opencode",
                                    "FINANCE_CLIENT": "opencode"},
                    "enabled": True,
                    "timeout": 180000,
                }
            },
        },
        ensure_ascii=False, indent=2,
    )
    return {"dsh": dsh, "codex": codex, "opencode": opencode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--path", type=Path, default=DSH_CONFIG,
                        help="DSH patch file (default: ~/.dsh/cordis.patch.yml)")
    parser.add_argument("--client", default="dsh", choices=sorted(AGENT_BY_CLIENT))
    parser.add_argument("--write", action="store_true", help="apply the change (default: dry run)")
    parser.add_argument("--print-adapters", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    config = HubConfig(root)
    paths = HubPaths(root)
    entry = dsh_entry(root, AGENT_BY_CLIENT[args.client], args.client)

    if args.print_adapters:
        for name, snippet in adapter_snippets(root).items():
            print(f"===== {name} =====")
            print(snippet)
            print()
        return 0

    if not args.path.exists():
        print(f"config not found: {args.path}", file=sys.stderr)
        return 2
    original_bytes = args.path.read_bytes()
    original = original_bytes.decode("utf-8")
    try:
        before = yaml.safe_load(original)
    except yaml.YAMLError as exc:
        print(f"refusing to edit unparsable YAML: {exc}", file=sys.stderr)
        return 2
    existing = find_finance_entries(before)
    if len(existing) == 1 and existing[0].get("config", {}).get("command") == entry["config"]["command"]:
        print(json.dumps({"status": "already_registered", "path": str(args.path),
                          "entry": existing[0]}, ensure_ascii=False, indent=2))
        return 0
    if existing:
        print(json.dumps({
            "status": "manual_review_required",
            "reason": "finance_hub entry exists but differs from the canonical adapter; refusing to "
                      "overwrite or duplicate",
            "existing": existing,
            "desired": entry,
        }, ensure_ascii=False, indent=2))
        return 1

    merged = merge_text(original, render_entry(entry))
    try:
        after = yaml.safe_load(merged)
    except yaml.YAMLError as exc:
        print(f"generated YAML is invalid, aborting: {exc}", file=sys.stderr)
        return 2
    before_pairs = entry_ids(before)
    after_pairs = entry_ids(after)
    missing = [pair for pair in before_pairs if pair not in after_pairs]
    new_entries = find_finance_entries(after)
    problems = []
    if missing:
        problems.append(f"pre-existing entries lost: {missing}")
    if len(new_entries) != 1:
        problems.append(f"expected exactly one finance_hub entry, found {len(new_entries)}")
    else:
        # Structural equality, not just presence: a mis-indented block can parse
        # as sibling keys with config: null and would silently register nothing.
        if new_entries[0] != entry:
            problems.append(f"generated entry differs from the intended adapter: "
                            f"{new_entries[0]!r}")
    if problems:
        print(json.dumps({"status": "validation_failed", "problems": problems},
                         ensure_ascii=False, indent=2))
        return 1

    result = {
        "status": "would_write" if not args.write else "written",
        "path": str(args.path),
        "client": args.client,
        "entry": entry,
        "before_sha256": sha256_bytes(original_bytes),
        "after_sha256": sha256_bytes(merged.encode("utf-8")),
        "entries_before": len(before_pairs),
        "entries_after": len(after_pairs),
    }
    if not args.write:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / "runs" / "setup" / "finance-hub" / "config-backup" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / args.path.name
    shutil.copy2(args.path, backup)
    (backup_dir / "manifest.json").write_text(json.dumps({
        "at": stamp,
        "source": str(args.path),
        "backup": str(backup),
        "sha256": sha256_bytes(backup.read_bytes()),
        "client": args.client,
        "entry": entry,
    }, ensure_ascii=False, indent=2) + "\n")
    args.path.write_text(merged)
    result["backup"] = str(backup)
    result["backup_sha256"] = sha256_bytes(backup.read_bytes())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
