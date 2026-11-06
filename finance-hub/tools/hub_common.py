"""Shared helpers for finance-hub: config, paths, credentials, state and call audit.

Credential rule: this module returns credential *values* only at the call
boundary, never persists them, and never puts them in logs, state files or
error messages. Everything that can be reported is a reference plus a status.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tomllib
from urllib import error as urlerror
from urllib import request as urlrequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_path(path: Path) -> str | None:
    if not Path(path).exists():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_toml(path: Path) -> dict:
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


class HubPaths:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.config_dir = self.root / "config"
        self.services_toml = self.config_dir / "services.toml"
        self.runtimes_toml = self.config_dir / "runtimes.toml"
        self.agents_toml = self.config_dir / "agents.toml"
        self.capabilities_toml = self.config_dir / "capabilities.toml"
        self.agents_md = self.root / "AGENTS.md"
        self.memory_md = self.root / "MEMORY.md"
        self.memory_db = self.root / "memory" / "shared.sqlite3"
        self.state_dir = self.root / ".runtime" / "finance-hub"
        self.state_file = self.state_dir / "hub.json"
        self.lock_file = self.state_dir / "hub.lock"
        self.logs_dir = self.state_dir / "logs"
        self.audit_dir = self.state_dir / "audit"
        self.catalog_file = self.state_dir / "tool_catalog.json"
        self.bridge_dir = self.state_dir / "bridges"

    def prepare(self) -> None:
        for directory in (self.state_dir, self.logs_dir, self.audit_dir, self.bridge_dir,
                          self.state_dir / "npm-cache", self.state_dir / "npm-logs"):
            directory.mkdir(parents=True, exist_ok=True)


class HubConfig:
    """Resolved project configuration (no secrets)."""

    def __init__(self, root: Path):
        self.paths = HubPaths(root)
        self.raw = load_toml(self.paths.services_toml)
        self.runtimes = load_toml(self.paths.runtimes_toml).get("runtimes", {})
        self.project = self.raw.get("project", {})
        self.hub = self.raw.get("hub", {})
        self.services = {k: v for k, v in self.raw.get("services", {}).items()}
        self.agents = load_toml(self.paths.agents_toml) if self.paths.agents_toml.exists() else {}

    @property
    def project_id(self) -> str:
        return self.project.get("id", "finance")

    @property
    def hub_version(self) -> str:
        return self.project.get("hub_version", "hub-v1")

    def service(self, name: str) -> dict:
        return dict(self.services.get(name, {}))

    def runtime_executable(self, ref: str) -> tuple[str, dict]:
        key = ref.split(":", 1)[-1] if ":" in ref else ref
        entry = self.runtimes.get(key)
        if not entry:
            raise KeyError(f"runtime not found in config/runtimes.toml: {ref}")
        path = entry["path"]
        if not Path(path).exists():
            raise FileNotFoundError(f"runtime executable missing: {path}")
        return path, entry

    def agent_role(self, agent: str) -> dict:
        default = dict(self.agents.get("default", {}))
        default.setdefault("role", "executor")
        default.setdefault("can_publish", False)
        default.setdefault("can_read_restricted", False)
        specific = self.agents.get("agents", {}).get(agent)
        if specific:
            merged = {**default, **specific}
        else:
            merged = {**default, "display": agent, "unregistered": True}
        merged["agent_id"] = agent
        return merged


# ----------------------------------------------------------------- credentials
class CredentialError(RuntimeError):
    pass


def _keychain_lookup(service: str) -> str:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CredentialError(f"keychain unavailable: {type(exc).__name__}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise CredentialError("keychain item not found or not readable")
    return result.stdout.strip()


def _codex_config_lookup(path: str) -> str:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        raise CredentialError("codex config not found")
    data = load_toml(config_path)
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise CredentialError("codex config path not found")
        node = node[part]
    if not isinstance(node, str) or not node.strip():
        raise CredentialError("codex config value is empty")
    return node.strip()


def resolve_credential(ref: str) -> tuple[str, dict]:
    """Resolve a credential reference. The returned status never contains the value."""
    if ref.startswith("keychain:"):
        service = ref.split(":", 1)[1]
        value = _keychain_lookup(service)
        return value, {"ref": ref, "source": "macos-keychain", "present": True}
    if ref.startswith("codex-config:"):
        path = ref.split(":", 1)[1]
        value = _codex_config_lookup(path)
        return value, {"ref": ref, "source": "codex-config-read-only", "present": True}
    raise CredentialError(f"unsupported credential reference: {ref.split(':', 1)[0]}")


def credential_status(ref: str | None) -> dict:
    if not ref:
        return {"ref": None, "present": None, "source": None,
                "detail": "no hub-side credential required"}
    try:
        _, status = resolve_credential(ref)
        return status
    except CredentialError as exc:
        return {"ref": ref, "present": False, "source": ref.split(":", 1)[0],
                "detail": str(exc)}


# ------------------------------------------------------------------- state I/O
def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def read_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def health(url: str, token: str, timeout: float = 2.0) -> dict | None:
    request = urlrequest.Request(
        url, headers={"x-finance-hub-token": token, "accept": "application/json"}
    )
    try:
        # This endpoint is local to the project. Environment HTTP/SOCKS proxies
        # must never intercept the hub token or affect loopback availability.
        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urlerror.URLError, TimeoutError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------- audit
class CallAudit:
    """Append-only call audit. Parameters are recorded as digests, never verbatim."""

    def __init__(self, audit_dir: Path):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, *, agent: str, bridge: str | None, run_id: str | None,
               tool: str, service: str | None, arguments: dict, status: str,
               duration_ms: float, detail: dict | None = None) -> None:
        entry = {
            "at": utc_now(),
            "agent": agent,
            "bridge": bridge,
            "run_id": run_id,
            "tool": tool,
            "service": service,
            "arguments_sha256": sha256_text(
                json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
            ),
            "argument_keys": sorted(arguments.keys()),
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "detail": detail or {},
        }
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.audit_dir / f"calls-{day}.jsonl"
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)


# ---------------------------------------------------------------------- misc
def setup_logging(log_path: Path | None = None):
    """stdout is reserved for MCP; all diagnostics go to stderr and/or a file."""
    stream = sys.stderr
    handle = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handle = Path(log_path).open("a", encoding="utf-8", buffering=1)
        stream = handle

    def log(message: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[finance-hub {stamp}] {message}", file=stream, flush=True)

    return log, handle


async def hub_tool_call(state: dict, agent: str, tool: str, arguments: dict) -> dict:
    """Call one hub tool from a local maintenance process with an explicit identity."""
    import httpx
    from contextlib import AsyncExitStack
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {
        "x-finance-hub-token": state["token"],
        "x-finance-agent": agent,
        "x-finance-bridge": f"cli-{os.getpid()}",
        "x-finance-client": "cli",
    }
    async with AsyncExitStack() as stack:
        http = await stack.enter_async_context(
            httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30.0, read=300.0))
        )
        read, write, _ = await stack.enter_async_context(
            streamable_http_client(state["url"], http_client=http)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        result = await session.call_tool(tool, arguments)
        if result.isError:
            text = result.content[0].text if result.content else "hub tool error"
            raise RuntimeError(text)
        return result.structuredContent or json.loads(result.content[0].text)
