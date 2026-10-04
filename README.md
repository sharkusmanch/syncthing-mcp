# Syncthing MCP

A configurable [Model Context Protocol](https://modelcontextprotocol.io/) server for Syncthing, using the official Python MCP SDK. Supports stdio and authenticated Streamable HTTP, multiple instances, typed operations, bounded responses, and opt-in writes. Tested against Syncthing **2.1.5**.

**Read-only by default.** Destructive and administrative operations require separate environment gates. Disabled tools are absent from discovery and rejected by the service layer. There is no arbitrary REST proxy.

## Run

Python 3.12 or newer; install the locked release from this repository:

```sh
uv sync --locked --no-dev
export SYNCTHING_URL=http://127.0.0.1:8384
export SYNCTHING_MCP_API_KEY_FILE=/run/secrets/syncthing-api-key
uv run --no-sync syncthing-mcp
```

The default transport is stdio. Configure your MCP client to launch that command with these environment variables. Standard output is reserved for MCP messages.

For HTTP, add:

```sh
export SYNCTHING_MCP_TRANSPORT=http
export SYNCTHING_MCP_HOST=127.0.0.1
export SYNCTHING_MCP_PORT=8080
export SYNCTHING_MCP_AUTH_TOKEN_FILE=/run/secrets/mcp-bearer-token
export SYNCTHING_MCP_ALLOWED_HOSTS='["127.0.0.1:8080"]'
uv run --no-sync syncthing-mcp
```

Connect at `http://127.0.0.1:8080/mcp` with `Authorization: Bearer <mcp-token>`. Generate an independent random token of at least 32 characters; never reuse Syncthing's key. HTTP is stateless with JSON responses; standalone SSE GET and subscriptions are not supported. Both modern SDK v2 and actual SDK v1 clients are tested.

This static bearer mode is for trusted private deployments, not a full MCP OAuth authorization server. Use HTTPS at a reverse proxy for remote access, pass the Authorization header, set the exact external Host allowlist, and restrict network access. `/healthz` and `/readyz` are public, process-only health checks. They intentionally do not check Syncthing availability.

Published container: `ghcr.io/sharkusmanch/syncthing-mcp`. Use a release tag **and verified digest**, bind HTTP to `0.0.0.0` inside the container, run as UID/GID 10001, with a read-only filesystem and no capabilities. No Syncthing data volume is needed. The digest-pinned Chainguard Python runtime contains no shell or package manager; use `python` for operational probes.

## Configure coverage and authority

All settings below use the `SYNCTHING_MCP_` prefix unless shown otherwise. Lists accept JSON arrays (preferred) or comma-separated names. Unknown tool/group names and invalid booleans fail startup. Booleans accept exactly `true` or `false`.

| Setting | Default / purpose |
|---|---|
| `SYNCTHING_URL`, `SYNCTHING_API_KEY` | Single backend URL and key; alternatively `API_KEY_FILE` |
| `INSTANCES` | JSON list of `{name,url,api_key}` or `api_key_file`; optional `allowed_paths`, `path_style` |
| `TRANSPORT` | `stdio` or `http` |
| `HOST`, `PORT` | `127.0.0.1`, `8080` |
| `AUTH_TOKEN`, `AUTH_TOKEN_FILE` | HTTP client credential; supply only one |
| `ALLOWED_HOSTS` | Exact HTTP Host values, including port when present; set explicitly for HTTP clients |
| `ALLOWED_ORIGINS` | Empty; supplied Origin must match exactly, absent Origin is allowed |
| `PROFILE` | `full`; `core` reduces discovery to common monitoring/operational tools |
| `GROUPS` | Optional group allowlist; diagnostics excluded unless explicitly enabled |
| `ENABLED_TOOLS` | Optional exact tool allowlist, replacing profile selection but never bypassing permissions |
| `DISABLED_TOOLS` | Exact denylist, always wins |
| `ALLOW_WRITES` | `false`; permits ordinary mutations |
| `ALLOW_DESTRUCTIVE` | `false`; also requires writes; destructive calls require `confirm=true` |
| `ALLOW_ADMIN` | `false`; also requires writes; trust, sharing, security and global administration |
| `ALLOWED_PATHS`, `PATH_STYLE` | Single-instance destination roots; empty denies destination changes; `posix` default or `windows` |
| `CA_FILE` | Optional CA bundle for upstream HTTPS; certificate validation cannot be disabled |
| `REQUEST_TIMEOUT`, `SCAN_TIMEOUT` | 30 / 300 seconds; scan has a longer finite deadline |
| `MAX_REQUEST_BYTES` | 262144; HTTP body and tool argument budget |
| `MAX_OUTPUT_BYTES` | 262144; HTTP response and tool-result budget |
| `MAX_UPSTREAM_BYTES` | 4194304; maximum streamed upstream response |
| `MAX_PAGE_SIZE` | 100; ceiling for list operations |
| `CONCURRENCY` | 8; upstream calls and active HTTP request ceiling |
| `HTTP_RATE_LIMIT` | 120 authenticated requests per minute, shared-principal token bucket |

Examples:

```sh
# Small monitoring catalog:
export SYNCTHING_MCP_PROFILE=core
# Broader reads are the default. Exact exclusions can narrow them:
export SYNCTHING_MCP_DISABLED_TOOLS='["syncthing_events","syncthing_disk_events"]'
# Ordinary writes, without destructive or administrative authority:
export SYNCTHING_MCP_ALLOW_WRITES=true
```

Multiple instances:

```json
[
  {"name":"hub","url":"https://syncthing.example:8384","api_key_file":"/run/secrets/hub-key"},
  {"name":"lab","url":"http://syncthing-lab:8384","api_key_file":"/run/secrets/lab-key","allowed_paths":["/data"],"path_style":"posix"}
]
```

One bearer authorizes **all configured instances**. Read calls without an instance select the first configured instance; writes require an explicit instance when more than one exists. There are no per-user or per-folder read ACLs. Use separate deployments for separate trust domains. Path roots constrain destination changes, not data visibility; they are lexical checks, not protection against symlinks on the remote host.

See [coverage](docs/coverage.md) for tool names and exclusions, [mutation policy](docs/mutations.md) for accepted fields and outcomes, and [security](SECURITY.md) for the trust boundary.

## Results and token use

Discovery is deterministic and paginated. Lists return bounded pages with `returned`, `next_cursor`, `truncated`, and pagination semantics. `fields` selects top-level fields **after** safe configuration projection; it cannot recover hidden secrets. Offset pages reflect live state and are not stable snapshots. Event retention can create gaps; event results report completeness limitations explicitly.

Configuration credentials and unknown configuration fields are omitted. Diagnostic tools expose potentially sensitive operational text and are off by default. Known-secret redaction is defense in depth; arbitrary remote text is untrusted data, never an instruction to the client.

Tool output includes structured content and compact JSON text for older clients. Errors use `isError` and sanitized codes. Oversized results return an actionable error instead of malformed/truncated JSON. Complete HTTP envelopes are capped, including SDK metadata and reflected request IDs. The official stdio transport reads complete lines before validation: its framing and request IDs are **not** protected by the HTTP byte cap. Stdio is intended for a trusted local parent process; tool argument/result limits still apply.

Measured catalog/result sizes and the reproducible measurement command are recorded in [efficiency](docs/efficiency.md). Bytes are reported directly; token counts depend on the client's tokenizer.

## Build, verify and maintain

```sh
uv sync --locked --group dev --group build
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=syncthing_mcp --cov-branch --cov-fail-under=80
uv run --project tests/legacy-client --locked python scripts/legacy_smoke.py --server-python "$PWD/.venv/bin/python"
sh scripts/install-test-syncthing.sh /tmp/syncthing-fixture
SYNCTHING_TEST_BINARY=/tmp/syncthing-fixture/syncthing-linux-amd64-v2.1.5/syncthing uv run pytest tests/test_live_syncthing.py
uv sync --locked --group dev --group build
uv build --no-build-isolation
```

The live test creates a temporary Syncthing profile, disables discovery/relays/NAT/upgrades, removes default folders, and only mutates disposable data. CI gates releases on those tests, Python 3.12/3.14, lint, types, coverage, runtime dependency auditing, and a restricted container smoke test.

Release workflow builds linux/amd64 and linux/arm64 images, emits per-platform BuildKit SBOM/provenance, scans both platform digests, signs the multiarch index with GitHub artifact attestations, verifies it, then promotes that exact digest to release tags. [Release verification](docs/releases.md) explains independent verification. Renovate GitHub App configuration maintains dependencies, lockfiles, Action SHAs and image digests; automerge is disabled.

MIT licensed. This project is independently maintained and is not an official Syncthing project.
