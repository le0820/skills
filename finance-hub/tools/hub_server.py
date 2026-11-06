"""finance-hub MCP server: shared memory + centrally managed upstream services.

Design: docs/MEMORY_AND_TOOL_SHARING_DESIGN.md.

Contract:
  * loopback-only Streamable HTTP, one hub process per project, port published
    in .runtime/finance-hub/hub.json and never hardcoded by clients;
  * upstream MCP connections are owned by the hub (one verified request-scoped
    session per service) and exposed under namespaced tool names;
  * credentials are resolved only at the call boundary from keychain/config
    references and never written to state, logs or audit;
  * memory is written only through this process; MEMORY.md is a generated index.

stdout is never used for logging: the transport owns it (stdio bridge) and
uvicorn runs the HTTP server here.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import contextvars
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sys
import time
from typing import Any

import httpx
import uvicorn
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hub_common import (  # noqa: E402
    CallAudit,
    CredentialError,
    HubConfig,
    HubPaths,
    credential_status,
    pid_alive,
    read_state,
    resolve_credential,
    sha256_path,
    setup_logging,
    utc_now,
    write_state,
)
from memory_store import KINDS, MemoryStore  # noqa: E402

CALLER_AGENT: contextvars.ContextVar[str] = contextvars.ContextVar("caller_agent", default="unknown")
CALLER_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar("caller_run", default=None)
CALLER_BRIDGE: contextvars.ContextVar[str | None] = contextvars.ContextVar("caller_bridge", default=None)

SAFE_PUBLIC_NAME = re.compile(r"[^A-Za-z0-9_-]")


def public_tool_name(namespace: str, raw: str, used: set[str]) -> str:
    """Stable, collision-free public name: <namespace>_<raw-without-repeated-prefix>."""
    stem = raw
    for sep in ("_", "-"):
        prefix = namespace + sep
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    candidate = SAFE_PUBLIC_NAME.sub("_", f"{namespace}_{stem}")[:60]
    if candidate not in used:
        return candidate
    base = candidate
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


def memory_tools() -> list[types.Tool]:
    def tool(name: str, title: str, description: str, properties: dict,
             required: list[str]) -> types.Tool:
        return types.Tool(
            name=name,
            title=title,
            description=description,
            inputSchema={"type": "object", "properties": properties, "required": required},
        )

    text = {"type": "string"}
    text_list = {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}
    return [
        tool(
            "project_bootstrap", "Project bootstrap",
            "First call in every finance task. Returns project_id, AGENTS.md path/hash, shared "
            "memory revision + MEMORY.md hash, allowed memory kinds, the caller's role, service "
            "status (configured vs authorized vs connected vs tools) and write boundaries. "
            "Does not read market data.",
            {"include_services": {"type": "boolean", "default": True}}, [],
        ),
        tool(
            "memory_search", "Shared memory search",
            "Search published shared memory. Structured filters (kind/entity/as_of) plus "
            "FTS5 for ASCII queries and substring matching for Chinese. as_of enforces point-in-"
            "time availability: records without a known available_at are excluded. Restricted "
            "records are only returned to callers with that role.",
            {"query": {"type": "string", "default": ""},
             "kind": {"type": "string", "enum": sorted(KINDS)},
             "entity": text,
             "as_of": {"type": "string", "description": "ISO-8601 with offset"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
             "include_history": {"type": "boolean", "default": False},
             "include_restricted": {"type": "boolean", "default": False}},
            [],
        ),
        tool(
            "memory_get", "Shared memory read",
            "Read one memory record including full content and source references. Candidates "
            "are only visible to memory managers.",
            {"memory_id": text, "include_candidates": {"type": "boolean", "default": False}},
            ["memory_id"],
        ),
        tool(
            "memory_propose", "Propose a memory candidate",
            "Idempotent candidate submission (engineering lesson, method index, research case "
            "index, handoff, failure lesson, decision index). Execution agents must propose "
            "instead of writing the database. Provide source_refs/artifact_refs; never include "
            "credentials, raw market dumps or whole conversations.",
            {"kind": {"type": "string", "enum": sorted(KINDS)},
             "summary": text,
             "content": {"type": "string", "default": ""},
             "entity_ids": text_list,
             "source_refs": text_list,
             "artifact_refs": text_list,
             "notion_refs": text_list,
             "visibility": {"type": "string", "default": "project:finance"},
             "available_at": {"type": "string"},
             "valid_from": {"type": "string"},
             "valid_to": {"type": "string"},
             "verification": {"type": "string", "enum": ["candidate", "verified", "disputed"],
                              "default": "candidate"},
             "supersedes": {"type": "string"},
             "conflicts_with": text_list,
             "idempotency_key": text},
            ["kind", "summary"],
        ),
        tool(
            "memory_changes", "Memory changes since revision",
            "Returns records published/superseded and audit events after a revision. Use after "
            "bootstrap to detect shared-memory updates.",
            {"since_revision": {"type": "integer", "minimum": 0, "default": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
             "include_restricted": {"type": "boolean", "default": False}},
            [],
        ),
        tool(
            "memory_publish", "Publish or reject a candidate (manager only)",
            "Memory-manager operation: publish a reviewed candidate (bumps the project revision "
            "and regenerates MEMORY.md) or reject it. Requires role.can_publish. Optimistic "
            "concurrency via expected_revision. Unresolved conflicts force 'disputed' unless a "
            "conflict_resolution is supplied.",
            {"memory_id": text,
             "decision": {"type": "string", "enum": ["publish", "reject"], "default": "publish"},
             "expected_revision": {"type": "integer"},
             "note": {"type": "string", "default": ""},
             "verification": {"type": "string", "enum": ["verified", "disputed", "candidate"],
                              "default": "verified"},
             "conflict_resolution": text},
            ["memory_id"],
        ),
        tool(
            "memory_status", "Shared memory status",
            "Live diagnostics of the shared memory database: revision, index hash, journal "
            "mode, connection transaction state, counts and integrity. Use it to detect a "
            "stale reader or an index/database mismatch before trusting recall.",
            {}, [],
        ),
        tool(
            "service_status", "Service status",
            "Per-service status: configured, credential reference state (never the value), "
            "connection state, tool count, environment/ownership and known limitations.",
            {}, [],
        ),
        tool(
            "service_discover", "Service tool discovery",
            "Returns the live tools (with original input schemas) of one upstream namespace or "
            "all of them, plus the hub's namespaced public names.",
            {"namespace": {"type": "string"}}, [],
        ),
    ]


class Upstream:
    """One hub-owned upstream MCP connection."""

    def __init__(self, name: str, cfg: dict, config: HubConfig, log, errlog):
        self.name = name
        self.cfg = cfg
        self.config = config
        self.log = log
        self.errlog = errlog
        self.namespace = cfg.get("namespace", name)
        self.tools: list[types.Tool] = []
        self.state = "configured"
        self.error: str | None = None
        self.connected_at: str | None = None
        self.connect_seconds: float | None = None
        self.credential_source: str | None = None
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        ref = cfg.get("credential_ref")
        self.credential = credential_status(ref) if ref else {"ref": None, "present": None,
                                                              "source": None,
                                                              "detail": "no credential required"}

    # ------------------------------------------------------------------ env
    def _child_env(self) -> dict[str, str]:
        # Only a minimal, explicit environment reaches upstream children.
        # Client/agent provider credentials are not inherited.
        keep = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "TERM", "SYSTEMROOT")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        env.update({str(k): str(v) for k, v in self.cfg.get("env", {}).items()})
        return env

    async def _authorization(self) -> dict[str, str]:
        ref = self.cfg.get("credential_ref")
        if not ref:
            return {}
        try:
            value, status = resolve_credential(ref)
        except CredentialError as primary_error:
            fallback = self.cfg.get("fallback_credential_ref")
            if not fallback:
                self.credential = credential_status(ref)
                raise
            value, status = resolve_credential(fallback)
            status = {**status, "primary_error": str(primary_error), "fallback": True}
            self.credential = status
            self.log(f"{self.name}: primary credential unavailable, using classified fallback")
        self.credential_source = status.get("source")
        return {"Authorization": value}

    # ---------------------------------------------------------------- connect
    async def connect(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            began = time.monotonic()
            self.state = "connecting"
            stack = AsyncExitStack()
            try:
                if self.cfg["transport"] == "stdio":
                    if self.cfg.get("runtime_ref"):
                        command, runtime = self.config.runtime_executable(self.cfg["runtime_ref"])
                    else:
                        command, runtime = self.cfg["command"], {}
                    params = StdioServerParameters(
                        command=command,
                        args=[str(a) for a in self.cfg.get("args", [])],
                        env=self._child_env(),
                        cwd=str(self.config.paths.root),
                    )
                    read, write = await stack.enter_async_context(
                        stdio_client(params, errlog=self.errlog)
                    )
                elif self.cfg["transport"] == "streamable-http":
                    headers = await self._authorization()
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=headers,
                            timeout=httpx.Timeout(30.0, read=300.0),
                            follow_redirects=True,
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(self.cfg["url"], http_client=client)
                    )
                else:
                    raise ValueError(f"unsupported transport: {self.cfg['transport']}")
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
                self.tools = list(listed.tools)
                self._stack = stack
                self._session = session
                self.state = "connected"
                self.error = None
                self.connected_at = utc_now()
                self.connect_seconds = round(time.monotonic() - began, 2)
                self.log(f"{self.name}: connected via {self.cfg['transport']}, "
                         f"{len(self.tools)} tools in {self.connect_seconds}s")
            except Exception as exc:  # keep the hub alive; report honestly
                self.state = "failed"
                self.error = f"{type(exc).__name__}: {exc}"[:800]
                self.tools = []
                await stack.aclose()
                self.log(f"{self.name}: connection failed: {self.error}")

    async def close(self) -> None:
        async with self._lock:
            stack, self._stack = self._stack, None
            self._session = None
            self.state = "closed"
            if stack is not None:
                try:
                    await stack.aclose()
                except Exception:
                    pass

    async def _recover(self) -> None:
        old = self._stack
        self._stack = None
        self._session = None
        self.state = "reconnecting"
        if old is not None:
            try:
                await old.aclose()
            except Exception:
                pass
        await self.connect()

    async def call(self, raw_name: str, arguments: dict) -> types.CallToolResult:
        if self._session is None:
            await self.connect()
        if self._session is None:
            raise RuntimeError(f"{self.name} unavailable: {self.error or self.state}")
        timeout = float(self.cfg.get("timeout_seconds", 150))
        try:
            return await asyncio.wait_for(
                self._session.call_tool(raw_name, arguments), timeout=timeout
            )
        except Exception as first_error:
            self.log(f"{self.name}: call failed ({type(first_error).__name__}); reconnecting once")
            await self._recover()
            if self._session is None:
                raise RuntimeError(
                    f"{self.name} unavailable after reconnect: {self.error or self.state}"
                ) from first_error
            return await asyncio.wait_for(
                self._session.call_tool(raw_name, arguments), timeout=timeout
            )

    def status(self) -> dict:
        payload = {
            "name": self.name,
            "namespace": self.namespace,
            "kind": self.cfg.get("kind", "mcp"),
            "enabled": bool(self.cfg.get("enabled", True)),
            "transport": self.cfg.get("transport"),
            "state": self.state,
            "connected": self._session is not None,
            "connected_at": self.connected_at,
            "connect_seconds": self.connect_seconds,
            "tool_count": len(self.tools),
            "error": self.error,
            "credential": self.credential,
            "credential_source": self.credential_source,
            "environment": self.cfg.get("environment"),
            "statefulness": self.cfg.get("statefulness"),
            "scope": self.cfg.get("scope"),
            "notes": self.cfg.get("notes"),
        }
        if self.cfg.get("transport") == "stdio":
            payload["command"] = self.cfg.get("command") or f"runtime:{self.cfg.get('runtime_ref')}"
        elif self.cfg.get("url"):
            payload["url"] = self.cfg["url"]
        return payload


class Hub:
    def __init__(self, config: HubConfig, log, errlog):
        self.config = config
        self.paths = config.paths
        self.paths.prepare()
        self.log = log
        self.errlog = errlog
        self.memory = MemoryStore(self.paths.root)
        self.audit = CallAudit(self.paths.audit_dir)
        self.token = secrets.token_hex(24)
        self.started_at = utc_now()
        self.upstreams: dict[str, Upstream] = {}
        self.public: dict[str, tuple[str, str, types.Tool]] = {}
        self.discovery: dict[str, Any] = {}
        self._tools_cache: list[types.Tool] | None = None
        self._tools_cache_key: str | None = None
        for name, cfg in config.services.items():
            if cfg.get("kind", "mcp") == "mcp" and cfg.get("enabled", True):
                self.upstreams[name] = Upstream(name, cfg, config, log, errlog)

    # --------------------------------------------------------------- lifecycle
    async def startup(self) -> None:
        if not self.paths.memory_md.exists():
            self.memory.render_index(actor="hub-startup")
        await self.discover()

    async def discover(self) -> None:
        timeout = float(self.config.hub.get("discovery_timeout_seconds", 90))
        self.log(f"discovering {len(self.upstreams)} upstream service(s)")
        results = await asyncio.gather(
            *(asyncio.wait_for(upstream.connect(), timeout) for upstream in self.upstreams.values()),
            return_exceptions=True,
        )
        for upstream, result in zip(self.upstreams.values(), results):
            if isinstance(result, BaseException):
                upstream.state = "failed"
                upstream.error = f"{type(result).__name__}: {result}"[:800]
                self.log(f"{upstream.name}: discovery error {upstream.error}")
        used: set[str] = set()
        self.public = {}
        for upstream in self.upstreams.values():
            for tool in upstream.tools:
                name = public_tool_name(upstream.namespace, tool.name, used)
                used.add(name)
                self.public[name] = (upstream.name, tool.name, tool)
        self._tools_cache = None
        self._tools_cache_key = None
        self.discovery = {
            "at": utc_now(),
            "services": {name: {"state": up.state, "tools": len(up.tools), "error": up.error,
                                "connect_seconds": up.connect_seconds}
                         for name, up in self.upstreams.items()},
            "public_tool_count": len(self.public),
        }
        catalog = {
            "schema_version": 1,
            "project_id": self.config.project_id,
            "generated_at": utc_now(),
            "public_tools": [
                {"public_name": name, "service": service, "upstream_tool": raw,
                 "description": (tool.description or "")[:500],
                 "executor_allowed": self._tool_allowed(service, raw, {"can_publish": False}),
                 "input_schema_sha256": _schema_digest(tool)}
                for name, (service, raw, tool) in sorted(self.public.items())
            ],
        }
        self.paths.catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        self.log(f"tool catalog: {len(self.public)} upstream tools; "
                 f"{len(self.memory_tool_list())} hub tools")

    async def shutdown(self) -> None:
        await asyncio.gather(*(up.close() for up in self.upstreams.values()),
                             return_exceptions=True)

    # -------------------------------------------------------------------- tools
    def caller(self) -> tuple[str, dict]:
        agent = CALLER_AGENT.get()
        return agent, self.config.agent_role(agent)

    def _tool_allowed(self, service: str, raw_name: str, role: dict) -> bool:
        cfg = self.config.service(service)
        if raw_name in set(cfg.get("deny_tools", [])):
            return False
        if not role.get("can_publish"):
            low = raw_name.lower()
            for pattern in cfg.get("executor_deny_patterns", []):
                if pattern.lower() in low:
                    return False
        return True

    def memory_tool_list(self) -> list[types.Tool]:
        return memory_tools()

    def tool_definitions(self) -> list[types.Tool]:
        _, role = self.caller()
        role_key = "manager" if role.get("can_publish") else "executor"
        tools = self.memory_tool_list()
        if not role.get("can_publish"):
            tools = [tool for tool in tools if tool.name != "memory_publish"]
        if self._tools_cache is None or self._tools_cache_key != role_key:
            cache: list[types.Tool] = []
            for name, (service, raw, tool) in sorted(self.public.items()):
                if not self._tool_allowed(service, raw, role):
                    continue
                cache.append(types.Tool(
                    name=name,
                    description=(f"[{service}] " + (tool.description or "")[:6000]).strip(),
                    inputSchema=tool.inputSchema,
                ))
            self._tools_cache = cache
            self._tools_cache_key = role_key
        tools.extend(self._tools_cache)
        return tools

    async def handle_call(self, name: str, arguments: dict) -> types.CallToolResult | dict:
        began = time.monotonic()
        agent, role = self.caller()
        bridge = CALLER_BRIDGE.get()
        run_id = CALLER_RUN.get()
        service = None
        status = "ok"
        detail: dict = {}
        try:
            if name in {tool.name for tool in self.memory_tool_list()}:
                result = self._memory_call(name, arguments, agent, role, run_id)
                detail = {"memory": True}
                return result
            if name not in self.public:
                raise ValueError(f"unknown tool: {name}")
            service, raw, _tool = self.public[name]
            if not self._tool_allowed(service, raw, role):
                raise PermissionError(
                    f"tool {name} ({service}:{raw}) is not permitted for role "
                    f"{role.get('role')}; formal writes follow the approval flow in AGENTS.md"
                )
            upstream = self.upstreams[service]
            result = await upstream.call(raw, arguments)
            detail = {"upstream_tool": raw, "is_error": bool(result.isError),
                      "content_blocks": len(result.content or [])}
            status = "error" if result.isError else "ok"
            return result
        except Exception as exc:
            status = "error"
            detail = {"error": f"{type(exc).__name__}: {exc}"[:500]}
            raise
        finally:
            self.audit.record(
                agent=agent, bridge=bridge, run_id=run_id, tool=name, service=service,
                arguments=arguments, status=status,
                duration_ms=(time.monotonic() - began) * 1000.0, detail=detail,
            )

    # ------------------------------------------------------------ memory calls
    def _memory_call(self, name: str, arguments: dict, agent: str, role: dict,
                     run_id: str | None) -> dict:
        include_restricted = bool(arguments.get("include_restricted"))
        if include_restricted and not role.get("can_read_restricted"):
            raise PermissionError(
                "include_restricted requires a role with can_read_restricted; "
                "personal holdings/behaviour memory is not returned to execution agents"
            )
        if name == "project_bootstrap":
            return self._bootstrap(agent, role, run_id,
                                   bool(arguments.get("include_services", True)))
        if name == "memory_search":
            return self.memory.search(
                arguments.get("query", ""),
                kind=arguments.get("kind"),
                entity=arguments.get("entity"),
                as_of=arguments.get("as_of"),
                limit=arguments.get("limit", 10),
                include_history=bool(arguments.get("include_history")),
                include_restricted=include_restricted,
            )
        if name == "memory_get":
            record = self.memory.get(
                arguments["memory_id"],
                include_candidates=bool(arguments.get("include_candidates"))
                and bool(role.get("can_publish")),
            )
            if not record:
                raise ValueError("memory not found or not visible to this caller")
            return {"record": record}
        if name == "memory_propose":
            result = self.memory.propose(
                kind=arguments["kind"], summary=arguments["summary"],
                content=arguments.get("content", ""),
                source_agent=agent, run_id=run_id,
                entity_ids=arguments.get("entity_ids"),
                source_refs=arguments.get("source_refs"),
                artifact_refs=arguments.get("artifact_refs"),
                notion_refs=arguments.get("notion_refs"),
                visibility=arguments.get("visibility", "project:finance"),
                available_at=arguments.get("available_at"),
                valid_from=arguments.get("valid_from"),
                valid_to=arguments.get("valid_to"),
                verification=arguments.get("verification", "candidate"),
                supersedes=arguments.get("supersedes"),
                conflicts_with=arguments.get("conflicts_with"),
                idempotency_key=arguments.get("idempotency_key"),
            )
            record = result["record"]
            return {
                "created": result["created"],
                "memory_id": record["memory_id"],
                "status": record["status"],
                "revision": self.memory.revision(),
                "note": "Candidate stored. A memory manager must publish before it appears in "
                        "MEMORY.md or default search.",
            }
        if name == "memory_changes":
            return self.memory.changes(
                int(arguments.get("since_revision", 0)),
                limit=arguments.get("limit", 50),
                include_restricted=include_restricted,
            )
        if name == "memory_publish":
            if not role.get("can_publish"):
                raise PermissionError("memory_publish requires role.can_publish")
            if arguments.get("decision", "publish") == "reject":
                return self.memory.reject(
                    arguments["memory_id"], actor=agent, note=arguments.get("note", ""),
                    run_id=run_id,
                )
            result = self.memory.publish(
                arguments["memory_id"], actor=agent,
                expected_revision=arguments.get("expected_revision"),
                run_id=run_id, note=arguments.get("note", ""),
                verification=arguments.get("verification", "verified"),
                conflict_resolution=arguments.get("conflict_resolution"),
            )
            result.pop("record", None)
            result["index"] = {"path": str(self.paths.memory_md),
                               "sha256": sha256_path(self.paths.memory_md)}
            return result
        if name == "memory_status":
            diag = self.memory.diagnostics()
            diag["index_path"] = str(self.paths.memory_md)
            diag["index_sha256"] = sha256_path(self.paths.memory_md)
            diag["index_revision"] = self.memory.meta("memory_md_revision")
            diag["counts"] = self.memory.counts(include_restricted=include_restricted)
            diag["kinds"] = KINDS
            return diag
        if name == "service_status":
            return self._service_status()
        if name == "service_discover":
            return self._service_discover(arguments.get("namespace"))
        raise ValueError(f"unknown memory tool: {name}")

    def _bootstrap(self, agent: str, role: dict, run_id: str | None,
                   include_services: bool) -> dict:
        counts = self.memory.counts(include_restricted=bool(role.get("can_read_restricted")))
        payload = {
            "project_id": self.config.project_id,
            "root": str(self.paths.root),
            "hub_version": self.config.hub_version,
            "hub_started_at": self.started_at,
            "caller": {"agent": agent, "role": role.get("role"), "run_id": run_id,
                       "bridge": CALLER_BRIDGE.get(),
                       "can_publish": bool(role.get("can_publish")),
                       "can_read_restricted": bool(role.get("can_read_restricted"))},
            "agents_md": {"path": str(self.paths.agents_md),
                          "sha256": sha256_path(self.paths.agents_md),
                          "enforcement": "read it at task start; this tool does not replace it"},
            "memory": {
                "revision": self.memory.revision(),
                "integrity": self.memory.integrity_check(),
                "db_path": str(self.paths.memory_db),
                "db_digest": self.memory.db_digest(),
                "index_path": str(self.paths.memory_md),
                "index_sha256": sha256_path(self.paths.memory_md),
                "counts": counts,
                "kinds": KINDS,
                "search_note": "FTS5 for ASCII queries, substring matching for Chinese; "
                               "as_of excludes records with unknown availability",
            },
            "write_boundaries": {
                "execution_agents": "memory_propose only; never edit memory/shared.sqlite3 or "
                                    "MEMORY.md directly",
                "manager": "memory_publish / memory_publish(decision=reject); Notion writes "
                           "still follow the per-candidate approval flow in AGENTS.md",
                "secrets": "no credential values are returned, logged or stored by the hub",
                "restricted": "personal holdings/behaviour memory requires can_read_restricted",
            },
            "next_steps": [
                "memory_search(query=..., kind=..., as_of=...) before relying on prior work",
                "memory_get(memory_id) for the full record and sources",
                "service_status() before assuming an upstream is authorized/connected",
            ],
        }
        if include_services:
            payload["services"] = self._service_status()["services"]
            payload["upstream_tools"] = len(self.public)
        return payload

    def _service_status(self) -> dict:
        services = []
        for name, cfg in self.config.services.items():
            kind = cfg.get("kind", "mcp")
            if kind == "mcp":
                upstream = self.upstreams.get(name)
                if upstream:
                    services.append(upstream.status())
                else:
                    services.append({"name": name, "kind": kind, "namespace":
                                     cfg.get("namespace", name),
                                     "enabled": bool(cfg.get("enabled")), "state": "disabled"})
            elif kind == "cli":
                entrypoint = self.paths.root / cfg.get("entrypoint", "")
                capabilities = self.paths.root / cfg.get("capabilities", "")
                services.append({
                    "name": name, "kind": "cli", "namespace": cfg.get("namespace"),
                    "enabled": bool(cfg.get("enabled", True)),
                    "state": "configured",
                    "entrypoint": str(entrypoint),
                    "entrypoint_present": entrypoint.exists(),
                    "capabilities": str(capabilities),
                    "capabilities_present": capabilities.exists(),
                    "callable_from_hub": bool(cfg.get("callable_from_hub")),
                    "scope": cfg.get("scope"), "environment": cfg.get("environment"),
                    "notes": cfg.get("notes"),
                    "call_path": ".venv/bin/python tools/easy_tdx_cli.py -- <native args>",
                })
        return {
            "generated_at": utc_now(),
            "revision": self.memory.revision(),
            "distinctions": ["configured", "credential_present", "connected", "tools_listed",
                             "data_fields_verified"],
            "services": services,
            "upstream_tools": len(self.public),
            "memory_tools": [tool.name for tool in self.memory_tool_list()],
        }

    def _service_discover(self, namespace: str | None) -> dict:
        if not namespace:
            return {
                "public_tools": sorted(self.public),
                "namespaces": {name: [tool.name for tool in up.tools]
                               for name, up in self.upstreams.items()},
                "note": "call with namespace=<service> for full input schemas",
            }
        match = [up for up in self.upstreams.values() if up.namespace == namespace or up.name == namespace]
        if not match:
            raise ValueError(f"unknown namespace: {namespace}")
        upstream = match[0]
        return {
            "namespace": upstream.namespace,
            "state": upstream.state,
            "error": upstream.error,
            "tools": [
                {"name": tool.name,
                 "public_name": next((pub for pub, (svc, raw, _t) in self.public.items()
                                      if svc == upstream.name and raw == tool.name), None),
                 "description": tool.description,
                 "input_schema": tool.inputSchema}
                for tool in upstream.tools
            ],
        }

    # ------------------------------------------------------------------ health
    def health_payload(self) -> dict:
        return {
            "schema_version": 1,
            "project_id": self.config.project_id,
            "hub_version": self.config.hub_version,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "phase": "ready",
            "memory_revision": self.memory.revision(),
            "index_sha256": sha256_path(self.paths.memory_md),
            "upstream_tools": len(self.public),
            "services": {name: up.state for name, up in self.upstreams.items()},
            "python": sys.version.split()[0],
        }


def _schema_digest(tool: types.Tool) -> str:
    import hashlib
    raw = json.dumps(tool.inputSchema, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HubApp:
    """ASGI wrapper: loopback token check, /healthz, caller identity, MCP transport."""

    def __init__(self, hub: Hub, manager: StreamableHTTPSessionManager):
        self.hub = hub
        self.manager = manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.manager.handle_request(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1")
                   for key, value in scope.get("headers", [])}
        if headers.get("x-finance-hub-token") != self.hub.token:
            await self._json(send, 401, {"error": "invalid or missing hub token"})
            return
        if scope.get("path") in ("/healthz", "/"):
            await self._json(send, 200, self.hub.health_payload())
            return
        tokens = [
            CALLER_AGENT.set(headers.get("x-finance-agent", "unknown")),
            CALLER_RUN.set(headers.get("x-finance-run")),
            CALLER_BRIDGE.set(headers.get("x-finance-bridge")),
        ]
        try:
            await self.manager.handle_request(scope, receive, send)
        finally:
            CALLER_RUN.reset(tokens[1])
            CALLER_BRIDGE.reset(tokens[2])
            CALLER_AGENT.reset(tokens[0])

    async def _json(self, send, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def pick_port(host: str, candidates: list[int]) -> int:
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, int(port)))
            except OSError:
                continue
            return int(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


async def run_hub(root: Path) -> int:
    paths = HubPaths(root)
    paths.prepare()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log, log_handle = setup_logging(paths.logs_dir / f"hub.{stamp}.log")
    existing = read_state(paths.state_file)
    if existing and pid_alive(existing.get("pid")):
        log(f"hub already running on pid {existing.get('pid')}; refusing to start a second one")
        return 3
    config = HubConfig(root)
    hub = Hub(config, log, log_handle)
    server = Server(
        "finance_hub",
        version=config.hub_version,
        instructions=(
            "finance project hub. Call project_bootstrap first, then memory_search before "
            "relying on prior work. Execution agents submit memory_propose candidates only. "
            "Upstream tools are namespaced (openbb_*, notion_*, qveris_*); the easy-tdx native "
            "CLI remains the primary data source. Never treat this server as approval to bypass "
            "AGENTS.md evidence rules or Notion per-candidate approval."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return hub.tool_definitions()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        return await hub.handle_call(name, arguments or {})

    await hub.startup()
    manager = StreamableHTTPSessionManager(app=server, json_response=False, stateless=False,
                                           session_idle_timeout=1800)
    app = HubApp(hub, manager)
    host = config.hub.get("host", "127.0.0.1")
    port = pick_port(host, config.hub.get("port_candidates", [8791]))
    uv_config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                               lifespan="off", access_log=False)
    uv = uvicorn.Server(uv_config)
    state = {
        "schema_version": 1,
        "project_id": config.project_id,
        "hub_version": config.hub_version,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/mcp",
        "health_url": f"http://{host}:{port}/healthz",
        "token": hub.token,
        "phase": "ready",
        "started_at": hub.started_at,
        "memory_revision": hub.memory.revision(),
        "tool_count": len(hub.public),
        "services": {name: up.state for name, up in hub.upstreams.items()},
        "root": str(paths.root),
        "python": sys.executable,
        "log": str(paths.logs_dir / f"hub.{stamp}.log"),
    }
    loop = asyncio.get_running_loop()

    def request_stop(*_args):
        uv.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            pass
    exit_code = 0
    async with manager.run():
        serve_task = asyncio.create_task(uv.serve())
        for _ in range(300):
            if uv.started:
                break
            if serve_task.done():
                break
            await asyncio.sleep(0.05)
        if not uv.started:
            log("uvicorn failed to start")
            uv.should_exit = True
            await serve_task
            await hub.shutdown()
            return 4
        write_state(paths.state_file, state)
        log(f"hub ready at http://{host}:{port}/mcp (pid {os.getpid()}, "
            f"revision {hub.memory.revision()}, {len(hub.public)} upstream tools)")
        try:
            await serve_task
        finally:
            await hub.shutdown()
            final = {**state, "phase": "stopped", "stopped_at": utc_now()}
            try:
                write_state(paths.state_file, final)
            except OSError:
                pass
            log("hub stopped")
            if log_handle:
                log_handle.close()
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "config" / "services.toml").exists():
        print(f"not a finance-hub root: {root}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run_hub(root))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
