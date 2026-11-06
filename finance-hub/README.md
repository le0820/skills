# finance-hub

A local, shared MCP gateway for finance research agents. It provides a SQLite-backed memory store, a stdio bridge, an HTTP hub bound to loopback, and optional namespaced MCP upstreams. Agent configuration distinguishes a memory manager from executors. The native easy-tdx CLI is a separate data source; this package does not expose it as an MCP tool.

## Quick start

Requires Python 3.13, SQLite with FTS5, and a Unix-like system (the bridge uses `fcntl`). The lock file records the original project's dependencies and includes easy-tdx; it is not a portable guarantee that all providers or external runtimes work on another machine.

```sh
cd finance-hub
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python tools/memory_admin.py rebuild
.venv/bin/python tools/doctor_shared.py --start
.venv/bin/python tools/doctor_shared.py
```

The rebuild initializes an **empty** memory database and generated `MEMORY.md`. Replace `AGENTS.md` with your own collaboration rules. The default `config/services.toml` disables external services. To enable one, review its settings, configure its local executable and credentials, and independently verify its access and behavior. OpenBB needs a separately installed `openbb-mcp` executable in `config/runtimes.toml`; Notion needs Node.js, `npx`, `mcp-remote` and authorization; QVeris needs a valid credential reference. The built-in keychain resolver is macOS-specific. Do not put credential values into configuration or Git.

Register `tools/hub_client.py` as the MCP stdio command with the Python executable and set `FINANCE_AGENT` to the intended identity. `tools/render_agent_config.py --print-adapters` prints examples; review paths and client configuration before using them. In an agent session call `project_bootstrap`, then `memory_search` and `memory_get` for matching records. Managers can review and publish candidates with `tools/memory_admin.py`; `--help` lists its commands. `tools/hub_recall.py --help` describes the evidence-producing recall helper.

## Boundaries and limitations

- The service catalog is a template. No external connection, data quality, account entitlement, or current tool count is implied by its presence. Verify each enabled service before relying on it. The `doctor_shared.py` checks also include optional easy-tdx and client setup, so warnings may be expected in a standalone installation.
- Local role labels and the loopback bearer token help coordinate trusted local processes; they are **not** isolation against a user or process that can read the state file, choose `FINANCE_AGENT`, change configuration, or access the database. Use OS-level account and file permissions for a real security boundary. Do not expose the hub to a network.
- `memory/shared.sqlite3`, `MEMORY.md`, runtime state, logs, credentials, and research results are local and excluded. A fresh copy does not contain the original project's memory or access. Back up or migrate private data separately through an authorized process.
- The original hub relies on local tools and provider-specific authentication; example adapters and integrations require review. This package is a sanitized source export, not an automatic migration of an existing deployment.

## Checks

```sh
.venv/bin/python -m unittest discover -s tools/tests -v
.venv/bin/python tools/doctor_shared.py
```

The included bridge tests cover startup and proxy handling. Passing them does not verify live upstreams, client registrations, market data, or investment rules.
