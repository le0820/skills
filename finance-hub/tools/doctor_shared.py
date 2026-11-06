"""Self-check for the finance-hub deployment across clients, services, credentials and memory.

Read-only by default. `--start` may start the hub through the normal bridge
lifecycle; `--stop` sends SIGTERM to the recorded hub pid. It never reads or
prints credential values, and never edits client configuration.

Exit code: 0 when every check is ok/warn, 1 when any check fails.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx
import yaml
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hub_common import (  # noqa: E402
    HubConfig,
    HubPaths,
    credential_status,
    health,
    pid_alive,
    read_state,
    sha256_path,
    setup_logging,
    utc_now,
)

ROOT = Path(__file__).resolve().parents[1]
DSH_CONFIG = Path.home() / ".dsh" / "cordis.patch.yml"


class Checker:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, name: str, status: str, detail, evidence=None):
        self.items.append({"check": name, "status": status, "detail": detail,
                           "evidence": evidence})
        icon = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[status]
        print(f"[{icon}] {name}: {detail}"[:400])

    def failed(self) -> bool:
        return any(item["status"] == "fail" for item in self.items)


def check_environment(check: Checker) -> None:
    venv_python = (ROOT / ".venv" / "bin" / "python")
    expected = venv_python.resolve()
    actual = Path(sys.executable).resolve()
    if actual != expected:
        check.add("python.interpreter", "fail",
                  f"interpreter {actual} is not the project .venv ({venv_python})")
    else:
        check.add("python.interpreter", "ok",
                  f"{venv_python} ({actual}, {sys.version.split()[0]})")
    if not sys.version.startswith("3.13"):
        check.add("python.version", "warn", f"{sys.version.split()[0]} (baseline 3.13.x)")
    else:
        check.add("python.version", "ok", sys.version.split()[0])
    lock = ROOT / "requirements.lock"
    drift = []
    if not lock.exists():
        check.add("requirements.lock", "fail", "missing")
        return
    from importlib import metadata
    for line in lock.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line or " @ " in line:
            continue
        name, version = line.split("==", 1)
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            drift.append(f"{name} missing")
            continue
        if installed != version:
            drift.append(f"{name} {installed} != {version}")
    if drift:
        check.add("requirements.lock", "fail", "; ".join(drift))
    else:
        check.add("requirements.lock", "ok",
                  f"pinned versions installed (sha256 {sha256_path(lock)[:12]}…)")


def check_config(check: Checker) -> HubConfig | None:
    try:
        config = HubConfig(ROOT)
    except Exception as exc:
        check.add("config.parse", "fail", f"{type(exc).__name__}: {exc}")
        return None
    check.add("config.parse", "ok",
              f"project={config.project_id} hub={config.hub_version} "
              f"services={sorted(config.services)}")
    missing = []
    for name, cfg in config.services.items():
        if cfg.get("kind", "mcp") != "mcp" or not cfg.get("enabled", True):
            continue
        if cfg.get("runtime_ref"):
            try:
                config.runtime_executable(cfg["runtime_ref"])
            except Exception as exc:
                missing.append(f"{name}: {exc}")
    if missing:
        check.add("config.runtimes", "fail", "; ".join(missing))
    else:
        check.add("config.runtimes", "ok", "all referenced executables exist")
    external = [name for name, cfg in config.services.items()
                if cfg.get("environment", "").startswith("external:")]
    check.add("config.environment", "warn" if external else "ok",
              f"external runtime dependency retained for {external}" if external
              else "all runtimes inside project environment")
    return config


def check_memory(check: Checker, paths: HubPaths, config: HubConfig | None) -> dict | None:
    if not paths.memory_db.exists():
        check.add("memory.db", "fail", f"missing {paths.memory_db}")
        return None
    from memory_store import MemoryStore
    store = MemoryStore(paths.root)
    try:
        integrity = store.integrity_check()
        revision = store.revision()
        counts = store.counts(include_restricted=True)
        if integrity != "ok":
            check.add("memory.integrity", "fail", integrity)
        else:
            check.add("memory.integrity", "ok",
                      f"revision {revision}, published "
                      f"{counts['status'].get('published', 0)}, candidates "
                      f"{counts['status'].get('candidate', 0)}, restricted "
                      f"{counts['restricted_published']}")
        actual_hash = sha256_path(paths.memory_md)
        recorded = store.meta("memory_md_sha256")
        recorded_rev = store.meta("memory_md_revision")
        if not actual_hash:
            check.add("memory.index", "fail", "MEMORY.md missing")
        elif actual_hash != recorded:
            check.add("memory.index", "fail",
                      "MEMORY.md hash differs from the database revision; run "
                      "tools/memory_admin.py rebuild")
        elif str(recorded_rev) != str(revision):
            check.add("memory.index", "warn",
                      f"MEMORY.md is at revision {recorded_rev}, database is {revision}")
        else:
            check.add("memory.index", "ok",
                      f"MEMORY.md matches revision {revision} ({actual_hash[:12]}…)")
        return {"revision": revision, "integrity": integrity, "counts": counts,
                "index_sha256": actual_hash}
    finally:
        store.close()


def check_client_config(check: Checker) -> dict:
    if not DSH_CONFIG.exists():
        check.add("client.dsh", "warn", f"config not found: {DSH_CONFIG}")
        return {"present": False}
    try:
        document = yaml.safe_load(DSH_CONFIG.read_text())
    except Exception as exc:
        check.add("client.dsh", "fail", f"cannot parse {DSH_CONFIG}: {exc}")
        return {"present": True, "parsed": False}
    entries = []
    for layer in document if isinstance(document, list) else []:
        items = layer.get("insert") if isinstance(layer, dict) and "insert" in layer else [layer]
        for item in items or []:
            if not isinstance(item, dict):
                continue
            cfg = item.get("config") or {}
            if cfg.get("serverName") == "finance_hub":
                entries.append(item)
    if not entries:
        check.add("client.dsh", "fail", "no finance_hub entry registered")
        return {"present": True, "entries": 0}
    if len(entries) > 1:
        check.add("client.dsh", "fail", f"{len(entries)} finance_hub entries (must be exactly one)")
        return {"present": True, "entries": len(entries)}
    entry = entries[0]
    cfg = entry.get("config") or {}
    problems = []
    if cfg.get("transport") != "stdio":
        problems.append("transport is not stdio")
    if not Path(cfg.get("command", "")).exists():
        problems.append(f"command missing: {cfg.get('command')}")
    args = cfg.get("args") or []
    if not args or not Path(args[0]).exists():
        problems.append(f"bridge script missing: {args}")
    if cfg.get("env", {}).get("FINANCE_AGENT") in (None, "", "unknown"):
        problems.append("FINANCE_AGENT is not set in the adapter")
    if problems:
        check.add("client.dsh", "fail", "; ".join(problems))
    else:
        check.add("client.dsh", "ok",
                  f"single finance_hub entry, bridge={args[0]}, "
                  f"agent={cfg.get('env', {}).get('FINANCE_AGENT')}, "
                  f"timeout={cfg.get('toolCallTimeoutMs')}ms")
    return {"present": True, "entries": 1, "config": cfg}


def check_easy_tdx(check: Checker, config: HubConfig | None) -> None:
    wrapper = ROOT / "tools" / "easy_tdx_cli.py"
    cli = ROOT / ".venv" / "bin" / "easy-tdx"
    if not wrapper.exists() or not cli.exists():
        check.add("easy_tdx.entrypoint", "fail", f"wrapper={wrapper.exists()} cli={cli.exists()}")
        return
    check.add("easy_tdx.entrypoint", "ok", str(wrapper))
    catalog = ROOT / "tools" / "easy_tdx_capabilities.json"
    verification = ROOT / "tools" / "verification.json"
    if catalog.exists() and verification.exists():
        data = json.loads(verification.read_text())
        recorded = (data.get("catalog") or {}).get("sha256")
        current = sha256_path(catalog)
        if recorded and recorded != current:
            check.add("easy_tdx.catalog", "warn",
                      "capabilities catalog changed since verification.json; rerun "
                      "tools/inspect_easy_tdx.py and the command matrix")
        else:
            check.add("easy_tdx.catalog", "ok",
                      f"matches verification record; "
                      f"{data.get('catalog', {}).get('leaf_command_count')} leaf commands, "
                      f"all_interfaces_qualified={data.get('all_interfaces_qualified')}")
    else:
        check.add("easy_tdx.catalog", "warn", "capabilities/verification record missing")


async def _hub_session(state: dict, agent: str):
    headers = {"x-finance-hub-token": state["token"], "x-finance-agent": agent,
               "x-finance-bridge": f"doctor-{os.getpid()}", "x-finance-client": "doctor"}
    from contextlib import AsyncExitStack
    stack = AsyncExitStack()
    try:
        http = await stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30.0, read=300.0),
                              trust_env=False)
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(state["url"], http_client=http)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return stack, session
    except BaseException:
        await stack.aclose()
        raise


async def check_hub_async(check: Checker, paths: HubPaths, start: bool) -> dict | None:
    if start:
        from hub_client import ensure_hub
        log, _handle = setup_logging(paths.logs_dir / f"doctor-{os.getpid()}.log")
        try:
            await asyncio.to_thread(ensure_hub, paths, log)
            check.add("hub.start", "ok", "hub started/verified through the bridge lifecycle")
        except Exception as exc:
            check.add("hub.start", "fail", f"{type(exc).__name__}: {exc}")
    state = read_state(paths.state_file)
    if not state:
        check.add("hub.state", "fail", "no .runtime/finance-hub/hub.json (hub not started)")
        return None
    alive = pid_alive(state.get("pid", 0))
    probe = health(state.get("health_url", ""), state.get("token", "")) if alive else None
    if not alive or not probe:
        check.add("hub.state", "fail",
                  f"state present but hub unreachable (pid {state.get('pid')}, alive={alive})")
        return None
    check.add("hub.state", "ok",
              f"pid {state['pid']} phase={probe.get('phase')} revision="
              f"{probe.get('memory_revision')} tools={probe.get('upstream_tools')}")
    try:
        stack, session = await _hub_session(state, "finance-admin")
    except Exception as exc:
        check.add("hub.session", "fail", f"{type(exc).__name__}: {exc}")
        return state
    try:
        tools = (await session.list_tools()).tools
        check.add("hub.tools", "ok",
                  f"{len(tools)} tools exposed to a manager "
                  f"({sum(1 for t in tools if not t.name.startswith('memory_'))} upstream)")
        status_result = await session.call_tool("service_status", {})
        payload = status_result.structuredContent or json.loads(status_result.content[0].text)
        for service in payload["services"]:
            if not service.get("enabled", True):
                check.add(f"service.{service['name']}", "warn",
                          f"disabled by config ({service.get('notes')})")
                continue
            if service.get("kind") != "mcp":
                check.add(f"service.{service['name']}", "warn",
                          f"{service.get('state')} (CLI service; call through the audited wrapper)")
                continue
            if service.get("state") != "connected":
                check.add(f"service.{service['name']}", "fail",
                          f"state={service.get('state')} error={service.get('error')}")
                continue
            cred = service.get("credential") or {}
            check.add(f"service.{service['name']}", "ok",
                      f"connected, {service.get('tool_count')} tools, "
                      f"credential={'n/a' if cred.get('ref') is None else cred.get('present')} "
                      f"({cred.get('source')})")
        return {**state, "service_status": payload, "tool_count": len(tools)}
    finally:
        await stack.aclose()


def stop_hub(check: Checker, paths: HubPaths) -> None:
    state = read_state(paths.state_file)
    if not state or not pid_alive(state.get("pid", 0)):
        check.add("hub.stop", "warn", "no running hub recorded")
        return
    os.kill(state["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and pid_alive(state["pid"]):
        time.sleep(0.2)
    stopped = not pid_alive(state["pid"])
    check.add("hub.stop", "ok" if stopped else "fail",
              f"pid {state['pid']} {'stopped' if stopped else 'still alive'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="start the hub if not running")
    parser.add_argument("--stop", action="store_true", help="stop the recorded hub")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true", help="write a run record")
    args = parser.parse_args()
    paths = HubPaths(ROOT)
    paths.prepare()
    check = Checker()
    if args.stop:
        stop_hub(check, paths)
    check_environment(check)
    config = check_config(check)
    memory = check_memory(check, paths, config)
    client = check_client_config(check)
    check_easy_tdx(check, config)
    hub = asyncio.run(check_hub_async(check, paths, args.start))
    payload = {
        "generated_at": utc_now(),
        "project_id": "finance",
        "root": str(ROOT),
        "checks": check.items,
        "ok": not check.failed(),
        "memory": memory,
        "client": client,
        "hub": ({key: hub.get(key) for key in
                 ("pid", "port", "url", "phase", "memory_revision", "tool_count")}
                if hub else None),
        "services": (hub or {}).get("service_status", {}).get("services"),
    }
    if args.save:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = paths.root / "runs" / "setup" / "finance-hub" / f"doctor-{stamp}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        payload["saved_to"] = str(target)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nresult: {'OK' if payload['ok'] else 'FAILED'} "
          f"({sum(1 for c in check.items if c['status']=='ok')} ok, "
          f"{sum(1 for c in check.items if c['status']=='warn')} warn, "
          f"{sum(1 for c in check.items if c['status']=='fail')} fail)")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
