"""Read shared finance memory through the real hub, without publishing or Notion writes."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from contextlib import AsyncExitStack

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hub_client import HubUnavailable, hub_request
from hub_common import HubPaths

ROOT = Path(__file__).resolve().parents[1]


def unpack(result) -> dict:
    if result.isError:
        raise RuntimeError("hub tool returned an error; no successful Recall claimed")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads("\n".join(item.text for item in result.content if item.type == "text"))


async def recall(args) -> dict:
    began = time.monotonic()
    async def read(session):
        bootstrap = unpack(await session.call_tool("project_bootstrap", {}))
        status = unpack(await session.call_tool("memory_status", {}))
        search = unpack(await session.call_tool("memory_search", {
            "query": args.query, "as_of": args.as_of, "limit": args.limit,
        }))
        records = []
        for hit in search.get("hits", []):
            result = unpack(await session.call_tool("memory_get", {
                "memory_id": hit["memory_id"],
            }))
            records.append(result["record"])
        return {"bootstrap": bootstrap, "memory_status": status,
                "search": search, "records": records}
    if args.transport == "stdio":
        # Exercise the same bridge executable/env used by the Codex project
        # adapter, including caller identity propagation and MCP discovery.
        async with AsyncExitStack() as stack:
            streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=str(ROOT / '.venv/bin/python'),
                args=[str(ROOT / 'tools/hub_client.py')], cwd=str(ROOT),
                env={"FINANCE_HUB_ROOT": str(ROOT), "FINANCE_AGENT": args.agent,
                     "FINANCE_CLIENT": "recall-stdio", "FINANCE_RUN_ID": args.run_id},
            )))
            session = await stack.enter_async_context(ClientSession(*streams))
            await session.initialize()
            tool_names = {tool.name for tool in (await session.list_tools()).tools}
            if not {"project_bootstrap", "memory_search", "memory_get"} <= tool_names:
                raise RuntimeError("bridge did not expose required Recall tools")
            result = await read(session)
    else:
        result = await hub_request(HubPaths(ROOT), args.agent, args.run_id,
                                   "recall-cli", lambda _: None, read)
    return {"task_id": args.task_id, "run_id": args.run_id, "agent_id": args.agent,
            "model_version": "unknown", "kind": "recall_result", "as_of": args.as_of,
            "read_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - began, 3),
            "status": "completed", "transport": args.transport, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="")
    parser.add_argument("--transport", choices=["direct", "stdio"], default="direct")
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 51), metavar="1..50")
    parser.add_argument("--agent", choices=["codex", "deepseek-harness", "opencode"], default="codex")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stamp = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        parser.error("--as-of requires an explicit timezone offset")
    # MemoryStore compares canonical ISO timestamps; normalize offset-bearing
    # caller input to UTC instead of letting a lexical comparison shift PIT.
    args.as_of = stamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    target = args.out.resolve()
    if not target.is_relative_to(ROOT / "runs"):
        parser.error("--out must be inside the project runs directory")
    try:
        result = asyncio.run(recall(args))
    except HubUnavailable as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__,
                          "error": "hub Recall failed; no successful recall claimed"}))
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive evidence creation: do not replace a previous Recall result.
    with target.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": result["status"], "output": str(target),
                      "revision": result["search"]["revision"],
                      "matches": result["search"]["matching"],
                      "records_read": len(result["records"]),
                      "duration_seconds": result["duration_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
