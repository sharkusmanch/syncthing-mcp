# Syncthing MCP implementation plan

> For agentic workers: use subagent-driven-development for scoped work and independent reviews. The user explicitly approved autonomous execution through deployment with subagent reviews.

Goal: ship a secure, broad-coverage Syncthing MCP server, publish an attested image and deploy read-only.
Architecture: explicit typed operation registry with service-layer policy, bounded HTTP clients and mandatory result sanitization; official MCP SDK handles both transports.
Tech stack: Python >=3.12, official mcp 2.3.x, HTTPX, Pydantic, uv, pytest, Ruff, mypy, GitHub Actions, GHCR, Flux/bjw-s.
Spec: ../specs/2026-10-03-syncthing-mcp-design.md

## Global constraints

Read-only by default. HTTP always bearer authenticated. Distinct upstream/MCP credentials. Default bind loopback. No arbitrary upstream proxy. No secrets in output/logs. No retries of ambiguous writes. Explicit destructive/admin gates. Initial production deployment reads only. Final review by gpt-6.1-sol after deployment.

## Review focus

- Auth/Host/Origin and all alternative request paths: HTTP integration tests.
- Inherited defaults or nested patches bypassing policy: effective-config tests.
- Partial application, ambiguous timeout, readback failure: mutation outcome tests.
- Event/queue pagination and oversized nested output: bounded-result tests.
- Publication of wrong commit/platform or Renovate missing access: workflow/registry verification.

## Task 1: Core operation engine

Files: src/syncthing_mcp/{config,errors,registry,client,engine,reads,writes,safety}.py; tests/test_{config,engine,reads,writes,safety,client}.py.
Interface: Settings.from_env(env: Mapping[str,str]|None=None) -> Settings. Engine(settings: Settings, transport: httpx.AsyncBaseTransport|None=None). Engine.tools() -> list[ToolDefinition]. Engine.call(name:str, arguments:dict[str,Any]) -> dict[str,Any]. Engine.aclose(). PublicError.payload() -> dict. ToolDefinition fields name, description, input_schema, read_only, destructive, group.
Settings transport,host,port,auth_token,allowed_hosts,allowed_origins,max_request_bytes,max_output_bytes,http_rate_limit,concurrency,instances,profile and policy fields are explicit and tested.
- [x] Write failing tests for strict env parsing, secret-safe errors, fixed paths, finite requests and policy enforcement.
- [x] Implement typed registry and broad documented endpoint coverage with bounded reads.
- [x] Add write regression tests before implementation; implement verified mutations and distinct permission tiers.
- [x] Run whole core suite, lint/types; produce coverage table and report.
- [x] Independent adversarial review and resolve findings.

## Task 2: MCP adapters and integration

Files: src/syncthing_mcp/{server,__main__,__init__}.py; tests/test_server.py; scripts/legacy_smoke.py.
Consumes Task 1 interface; exposes console script syncthing-mcp.
- [x] Test default HTTP denial, exact health exceptions, duplicate/malformed bearer, Host/Origin and request budgets.
- [x] Implement official SDK integration; startup filters tools, call failures use isError and sanitized structured payloads; logs stderr.
- [x] Run actual stdio/HTTP tests with current and pinned v1 SDK clients against disposable backend.
- [x] Measure catalog and representative result bytes.

## Task 3: Supply chain

Files: pyproject.toml, uv.lock, Dockerfile, .github/workflows/{ci,release,codeql}.yml, renovate.json, README.md, SECURITY.md, LICENSE.
- [x] Lock dependencies; add formatting/lint/types/tests, package build and dependency audit to CI.
- [x] Pin actions/images; isolate untrusted CI from publishing credentials; require release version/commit validation.
- [ ] Build amd64/arm64, OCI SBOM/provenance and GitHub signed provenance; verify by digest.
- [ ] Enable Renovate via installed GitHub App and verify bot evidence or identify exact access blocker.
- [x] Review workflow trust boundaries independently.

## Task 4: Cluster rollout

Files in home-ops: clusters/home/apps/mcp/syncthing-mcp/{helm-release,external-secret,kustomization}.yaml; parent kustomization; reciprocal tools/syncthing policy.
- [x] Resolve existing backend key without logging it; store via authorized secret workflow. Generate separate MCP bearer through ESO.
- [ ] Render and validate manifests, digest pinned release, read-only/full profile, restricted pod, narrow networking, health checks and secret reload.
- [ ] Push GitOps change and reconcile; verify healthy deployment, auth failures, allowed reads, denied writes, health monitoring and egress boundaries.
- [ ] Update operator documentation; no production write testing.

## Task 5: Final encompassing Sol review

- [ ] Give fresh gpt-6.1-sol reviewer exact source commit, CI runs, image digest/provenance, docs and live manifest evidence.
- [ ] Resolve blockers and rerun affected validation; review any changed final artifacts.
- [ ] Report repository, image, endpoint, enabled permissions, test/review results and residual limitations.
