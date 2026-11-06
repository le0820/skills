"""Lightweight stdio MCP bridge: the single `finance_hub` entry for every client.

Each client launches this script once. For every tools/list or tools/call it
discovers (or starts, under an exclusive lock) the project hub and opens one
short-lived downstream MCP session carrying this caller's identity.

Why a session per request instead of one long-lived client session: the bridge
runs inside the client's MCP server task group, and anyio cancel scopes must be
entered and exited in the same task. Holding a stored session created in one
request handler and reusing it from another produced cross-task cancel-scope
deadlocks. A nested, request-scoped session is simpler, isolated per call, and
the hub remains the only owner of upstream connections.

stdout carries MCP only. Diagnostics go to .runtime/finance-hub/logs/.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack, contextmanager
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import fcntl
import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hub_common import (  # noqa: E402
    HubConfig,
    HubPaths,
    health,
    pid_alive,
    read_state,
    setup_logging,
)

ROOT = Path(os.environ.get("FINANCE_HUB_ROOT") or Path(__file__).resolve().parents[1]).resolve()


class HubUnavailable(RuntimeError):
    pass


def _hub_settings(paths: HubPaths) -> tuple[float, str]:
    try:
        config = HubConfig(paths.root)
        return (float(config.hub.get("startup_timeout_seconds", 180)), config.project_id)
    except Exception:
        return 180.0, paths.root.name


def _spawn_hub(paths: HubPaths, log, reason: str):
    log(f"starting hub ({reason})")
    bootstrap_log = paths.logs_dir / "hub.bootstrap.log"
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
           if key in os.environ}
    env["PYTHONNOUSERSITE"] = "1"
    with bootstrap_log.open("ab") as sink:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().parent / "hub_server.py"),
             "--root", str(paths.root)],
            cwd=str(paths.root), env=env, stdin=subprocess.DEVNULL,
            stdout=sink, stderr=sink, start_new_session=True,
        )


def _ready_state(state: dict | None, project_id: str) -> dict | None:
    if not state or not pid_alive(state.get("pid", 0)):
        return None
    probe = health(state.get("health_url", ""), state.get("token", ""))
    if (probe and probe.get("project_id") == project_id
            and probe.get("phase") == "ready"):
        return state
    raise HubUnavailable(
        f"hub pid {state.get('pid')} is alive but its local health check failed "
        "or returned a different project/phase; check local-network permissions "
        "and run doctor_shared.py from an allowed environment. "
        "Not starting a second hub or deleting the live process state."
    )


@contextmanager
def _startup_lock(paths: HubPaths, timeout: float):
    # A different caller may be doing a cold start. Bound the lock wait rather
    # than silently blocking all MCP traffic for the full discovery interval.
    deadline = time.monotonic() + min(timeout, 5.0)
    with paths.lock_file.open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HubUnavailable("hub startup lock is busy; retry after the other startup finishes")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def ensure_hub(paths: HubPaths, log) -> dict:
    """Return a healthy hub state, starting one under an exclusive file lock if needed."""
    paths.prepare()
    timeout, project_id = _hub_settings(paths)
    ready = _ready_state(read_state(paths.state_file), project_id)
    if ready:
        return ready
    with _startup_lock(paths, timeout):
        state = read_state(paths.state_file)
        ready = _ready_state(state, project_id)
        if ready:
            return ready
        if state and not pid_alive(state.get("pid", 0)):
            log(f"removing stale hub state for dead pid {state.get('pid')}")
            try:
                paths.state_file.unlink()
            except OSError:
                pass
        child = _spawn_hub(paths, log, "no healthy hub")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            candidate = read_state(paths.state_file)
            if candidate and candidate.get("phase") == "ready":
                probe = health(candidate.get("health_url", ""), candidate.get("token", ""))
                if (probe and probe.get("project_id") == project_id
                        and probe.get("phase") == "ready"):
                    log(f"hub ready after {timeout - (deadline - time.monotonic()):.1f}s")
                    return candidate
            if child.poll() is not None:
                raise HubUnavailable(f"hub startup process exited with code {child.returncode}; "
                                     f"see {paths.logs_dir / 'hub.bootstrap.log'}")
            time.sleep(0.2)
        raise HubUnavailable(f"hub did not become ready within {timeout:.0f}s; see "
                             f"{paths.logs_dir / 'hub.bootstrap.log'}")


async def hub_request(paths: HubPaths, agent: str, run_id: str | None, client: str, log,
                      handler):
    """Open one short-lived hub session in the current task and run `handler(session)`."""
    # Health/lock/startup checks are synchronous; keep them off the MCP event
    # loop so other requests and timeouts can continue to run.
    state = await asyncio.to_thread(ensure_hub, paths, log)
    headers = {
        "x-finance-hub-token": state["token"],
        "x-finance-agent": agent,
        "x-finance-bridge": f"{client}-{os.getpid()}",
        "x-finance-client": client,
        "x-finance-run": run_id or "",
    }
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30.0, read=300.0),
                              trust_env=False)
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(state["url"], http_client=http)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return await handler(session)


async def serve(paths: HubPaths, agent: str, run_id: str | None, client: str) -> int:
    log, handle = setup_logging(paths.logs_dir / f"bridge-{client}-{os.getpid()}.log")
    server = Server(
        "finance_hub",
        version="hub-v1",
        instructions=(
            "finance-hub: shared project memory plus centrally managed upstream services. "
            "Call project_bootstrap first; memory_search before relying on prior work; "
            "execution agents submit memory_propose candidates only. Upstream tools are "
            "namespaced (openbb_*, notion_*, qveris_*). easy-tdx native CLI stays the primary "
            "data source. This hub does not replace AGENTS.md evidence and approval rules."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        async def run(session: ClientSession):
            result = await session.list_tools()
            return list(result.tools)
        return await hub_request(paths, agent, run_id, client, log, run)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        async def run(session: ClientSession):
            return await session.call_tool(name, arguments or {})
        try:
            return await hub_request(paths, agent, run_id, client, log, run)
        except Exception as exc:
            log(f"call {name} failed ({type(exc).__name__}: {exc}); retrying once")
            return await hub_request(paths, agent, run_id, client, log, run)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream,
                             server.create_initialization_options())
    finally:
        if handle:
            handle.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--client", default=os.environ.get("FINANCE_CLIENT", "unknown"))
    args = parser.parse_args()
    paths = HubPaths(args.root.resolve())
    agent = os.environ.get("FINANCE_AGENT", "unknown")
    run_id = os.environ.get("FINANCE_RUN_ID") or None
    try:
        return asyncio.run(serve(paths, agent, run_id, args.client))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Never write to stdout: it is the MCP transport.
        try:
            log, _ = setup_logging(paths.logs_dir / f"bridge-{args.client}-{os.getpid()}.log")
            log(f"fatal: {type(exc).__name__}: {exc}")
            log(traceback.format_exc()[-4000:])
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
