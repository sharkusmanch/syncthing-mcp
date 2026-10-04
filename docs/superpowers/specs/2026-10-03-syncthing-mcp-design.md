# Syncthing MCP design — 2026-10-03

## Outcome

Create public GitHub repository `sharkusmanch/syncthing-mcp`, under MIT, implementing a secure, independently maintained Syncthing MCP server. Publish tested, attested multi-architecture GHCR images and deploy via the existing home-ops GitOps repository to namespace `mcp`. Initial cluster deployment is read-only, as requested. Final validation is an all-encompassing Sol adversarial review, after deployment verification; any fixes it requires are reverified and rereviewed.

## Architecture and alternatives

Use Python 3.12+, official MCP SDK v2, HTTPX and Pydantic. Lock exact resolved dependencies in uv.lock. A registry of typed, named operations connects the MCP adapter to policy-enforced service methods and one bounded HTTP client per instance. This retains explicit input schemas without an arbitrary REST proxy.

Alternatives considered: FastMCP offers useful composition but adds framework surface unnecessary here; a generic REST/action-dispatch tool reduces discovery text but weakens action-specific schemas and permissions. Choose the official SDK with concise named tools and startup feature profiles.

Layers: immutable environment configuration -> operation registry -> policy and argument validation -> Syncthing service -> HTTP client -> mandatory redaction and bounded result projection. Every operation enforces policy in the service, even when not registered as an MCP tool. No session-driven tool activation.

## Transports and identity

- stdio default; stdout contains MCP only, diagnostics use stderr.
- Streamable HTTP `/mcp`, default loopback binding; container binds port 8080 on all interfaces.
- HTTP requires a separate, >=32-character MCP bearer token. No anonymous HTTP mode. Validate token using constant-time comparison. Static bearer mode is explicitly documented as private-deployment authentication, not a full OAuth authorization server.
- Explicit Host allowlist and Origin allowlist; missing Origin allowed for native clients, invalid supplied Origin denied. Do not trust forwarded headers by default. HTTPS terminates at cluster ingress.
- Unauthenticated `/healthz` and `/readyz` expose only readiness of this process, never instance URLs or credentials. Backend reachability is an authenticated operation; backend outages must not cause restart loops.
- Verify stdio and HTTP using modern and legacy SDK protocol paths, without introducing custom protocol implementations.
- Multiple named instances via JSON environment configuration (and single-instance convenience variables). Upstream API keys cannot equal the MCP-facing token. Callers cannot supply base URLs or credentials.

## Configuration and permissions

Prefix variables with `SYNCTHING_MCP_`, except convenience upstream `SYNCTHING_URL` and `SYNCTHING_API_KEY`.

- TRANSPORT: stdio|http, default stdio.
- HOST, PORT, AUTH_TOKEN (or AUTH_TOKEN_FILE), ALLOWED_HOSTS, ALLOWED_ORIGINS.
- INSTANCES: JSON array of name, url, api_key (or api_key_file), optional allowed_paths and path_style (posix|windows, default posix). Unique instance names required. A single instance may default; mutating calls require explicit instance when multiple are configured.
- PROFILE: core|full (default full read coverage); GROUPS and exact ENABLED_TOOLS/DISABLED_TOOLS filter at startup. Deny takes precedence. Unknown names fail startup.
- ALLOW_WRITES=false, ALLOW_DESTRUCTIVE=false, ALLOW_ADMIN=false. Destructive/admin permissions also require ALLOW_WRITES. Tools requiring unavailable permission are absent and remain uncallable internally. Configurability must never silently broaden authority.
- Request timeout, scan timeout, maximum upstream bytes, maximum output bytes, maximum list page size and concurrency are bounded and configurable. No unbounded response mode.
- Strict booleans: invalid values abort startup. Environment validation errors omit values containing secrets.

## Coverage

Maintain a reviewed endpoint coverage table mapping all currently supported, non-deprecated official REST endpoints to implemented operations or explicit exclusion reasons. Cover:

- System status/version/health/connections/discovery/paths/errors/logs/log levels.
- Folder/device lists, config and statistics; pending offers and dismissals.
- Folder status/completion/errors, file metadata, browse, needed and remote-needed files, local changes, ignores, versions and restoration.
- Event polling and disk events, bounded by timeout/count, explicit gap/truncation handling.
- Configuration reads and updates for folders/devices/defaults/options/GUI/LDAP, with safe field projections and high-risk settings admin-gated.
- Scans, pause/resume devices and folders, error clearing, file priority.
- Administrative/destructive operations: override, revert, restart, shutdown, database reset and upgrade, with explicit confirmation and separate permissions.
- Service utilities (device-ID validation, language/report/random), and selected debug diagnostics only when documented and safe. No arbitrary debug URL/path proxy, runtime profiler dump or removal of protocol safeguards.

Read-only PROFILE=full exposes supported read tools except privileged diagnostic groups explicitly disabled by default. Core profile provides a smaller daily-monitoring schema. Full coverage means implemented and documented policy boundaries, not exposing every danger by default.

## Adversarial design amendments

- One bearer credential is one shared principal authorized for all configured instances. This release does not claim per-folder or per-user isolation. Do not implement partial folder ACLs that aggregate reads or device-wide operations could bypass. Operators needing distinct trust domains run separate deployments with separate upstream credentials and instance lists.
- Explicit safe configuration projections omit unknown fields and sensitive values before requested field selection. Raw logs, discovery addresses, host browsing, report and debug output belong to the `diagnostics` group, disabled by default even in full profile. Opting into diagnostics exposes potentially sensitive operational text; known-secret redaction is defense in depth, not a promise to recognize arbitrary secrets in log strings.
- Upstream client uses follow_redirects=False, trust_env=False, verified TLS and operator CA support. Base URLs must be http/https without userinfo, query or fragment. No insecure-TLS switch. Reject redirects; never pass arbitrary upstream error bodies to clients.
- Actual pinned SDK v1 clients must be tested in a separate environment on both transports; v2 legacy mode alone is insufficient compatibility evidence.
- Validate malformed/duplicate Authorization headers, exact health-path exemptions, trailing paths, supplied Host/Origin, request size, serialized MCP envelope size and nesting. Enforce bounded concurrent/in-flight requests and a configurable HTTP per-principal request-rate budget.
- confirm=true is an accidental-action guard, not proof of independent human consent.
- Runtime-only field policy is explicit: ordinary folder updates may change label, paused, rescanIntervalS, fsWatcherEnabled, fsWatcherDelayS; device updates may change name, paused, compression, maxSendKbps, maxRecvKbps. Paths, sharing/trust, encryption, versioning, permissions, introducers, auto-accept, network/listen addresses and security settings require admin authority. Other supported fields are enumerated in a reviewed policy table; unknown fields fail closed. Effective inherited defaults receive the same validation as explicit inputs. External-command versioning is excluded entirely in v0.1; standard versioning remains configurable behind admin gates.
- Destination path allowlists constrain configuration lexically, not physical access through remote symlinks. Required allowed roots are enforced on creates and path changes. Folder-relative paths reject absolute/drive/UNC/parent traversal forms. OS/container permissions at Syncthing remain the physical confinement boundary.

## Write semantics and data safety

- Encode validated opaque IDs as individual path components. Reject control characters, slash/backslash, dot segments and ambiguous encoding. Validate paths according to remote-platform semantics; do not pretend local realpath can resolve remote symlinks.
- Generic dictionaries cannot change identity keys. No whole-config replace, arbitrary URL/method/body passthrough, or implicit external-versioner command execution.
- Create refuses an existing ID, reads defaults, creates paused when accepting a share or applying ignores, verifies current effective config, then unpauses only on explicit request. Accept requires an actual matching pending offer and explicit destination path. Existing shared folders are merged deliberately rather than replaced.
- Fetch current object before update/delete. Updates preserve unrelated nested fields through controlled merge; ordered arrays are explicit replacement operations. Support expected-revision fingerprints to reject stale client state. Serialize writes per instance; document that Syncthing has no atomic compare-and-swap against other clients.
- Independently read back create/update/delete. Successful HTTP is not evidence of persisted or completed state. Return verified, accepted, or outcome_unknown; never replay ambiguous writes automatically.
- Restart-required lookup failure returns unknown, never false.
- Destructive operations require confirm=true, relevant gate, explicit resource scope and preflight checks. Reset requires paused targets; bulk reset validates all targets before any mutation. Override/revert acknowledge asynchronous acceptance, then expose status for verification.
- Scan is synchronous upstream: use a finite longer timeout, cancellation-safe cleanup and honest unknown outcome on timeout. Do not fake an asynchronous upstream API.
- External versioning commands are excluded in v0.1; sensitive GUI/auth changes require admin permission in addition to write permission. Reject unsupported dangerous fields explicitly, including inherited unsafe defaults.
- Deletes remove configuration only where that is Syncthing semantics. Document override/revert/restore propagation and that synchronization is not backup.

### Additional Syncthing invariants

- Syncthing has no atomic create-if-absent. A duplicate-ID precheck protects normal use but cannot prevent another client creating that ID between preflight and POST. Document the residual external-writer race and recommend operational single-writer control for configuration changes; never claim an MCP-local lock eliminates it.
- Readback checks effective runtime state, not proof of disk durability. Return separate request outcome, readback verification, persistence status and restart requirement. An ambiguous/failed write followed by a matching GET remains persistence-unknown.
- Empty allowed_paths denies destination changes; missing allowed_paths also denies create/path-changing tools until configured. POSIX paths must be absolute with no tilde or parent traversal. Windows requires explicit path_style=windows and absolute drive-root paths; reject drive-relative, device-namespace and UNC forms in v0.1. Lexical containment applies to archive paths too. Host glob browsing is disabled when its containment cannot be established.
- Reset preflight can race with other clients. A failure may mean partial reset; never retry or automatically resume after failure. Report affected scope and unknown/partial outcome.
- Restore validates requested timestamps against available versions and parses per-file errors even on HTTP 200. Report restored, failed and unknown separately. Restore requires destructive permission.
- Ignore replacement preserves ordered raw ignore lines, never expanded lines; remains behind destructive permission because it can expose previously excluded content or permit deletions. Reject #include in v0.1; new-folder setup remains paused until successful write/readback.
- Creation selects intended peers explicitly rather than inheriting default sharing lists. Validate effective configuration and inherited defaults for paths, versioning and unsafe fields. Reject changing an existing folder to/from receiveencrypted. Pending-offer DELETE is temporary dismissal, not persistent blocking.
- Exclude deprecated routes, removed discovery POST, binary profiler/support dumps, root configuration replacement and persistent ignore workflows requiring whole-root replacement. Record exclusions rather than claim unsupported endpoint coverage. Initial tested backend is Syncthing 2.1.5; no fallback to broader deprecated endpoints.

## Token and resource efficiency

- Short deterministic descriptions and schemas; avoid copying entire upstream manuals into discovery. No giant opaque action parameter.
- Summary projections by default; allow validated detail selection after mandatory secret redaction. Include identifiers and state needed for follow-up.
- Lists use bounded pages with items, returned, next_cursor and truncated where appropriate. Distinguish upstream pagination from local result slicing and document consistency. Never invent totals.
- Cap response bytes while streaming upstream and cap serialized output without breaking JSON. Oversized single objects return an actionable error, not silent data loss.
- Event cursors advance over the processed upstream boundary; locally omitted events must remain retrievable or be explicitly reported as skipped. Report upstream retention/limit gaps separately from local output truncation; never claim completeness from cursor existence.
- Typed structured output plus compact JSON text fallback for older clients. Tool failures set isError with code, sanitized message, retryable and outcome.
- Measure discovery/result bytes for core/full profiles and representative fixtures; document measured values rather than unverified token savings claims.

## Supply chain and maintenance

- GitHub Actions CI: locked Python dependencies, lint/format/type checks, unit + actual MCP integration + disposable Syncthing tests, package build, coverage floor with direct security-path assertions.
- Tests must cover the audited upstream failures: anonymous HTTP, credential exposure, path traversal, replacement on duplicate create, disabled POST timeout, false restart state and bogus acceptance.
- Public PRs get read-only tokens; no pull_request_target execution of untrusted changes. SHA-pin Actions; persist-credentials false.
- Release tags must match package version, pass CI at the exact commit, and originate from main. Trusted publishing job only gets packages/id-token/attestations write permissions.
- Build GHCR linux/amd64 and linux/arm64; nonroot UID 10001, read-only root filesystem, no capabilities. Digest-pin base and builder images.
- BuildKit SBOM + maximum provenance per platform; GitHub actions/attest signed provenance for published multiarch digest; independent gh attestation verification before deployment. Do not claim an AMD64 SBOM covers ARM64.
- Renovate GitHub App, config:recommended, action SHA pinning, Docker digests, weekly uv lock maintenance, automerge disabled. Verify app access and onboarding/check evidence; config file alone is insufficient.
- MIT license, README env/tool reference, SECURITY.md, documented verification and release procedure. No real endpoints, data or credentials in tests/examples.

## Cluster deployment

Use existing bjw-s app-template 5.2.1, namespace mcp, one stateless replica. Image is release tag plus verified digest. CPU request 25m/limit 500m; memory request 128Mi/limit 256Mi, adjusted only with evidence. No database, PVC or sync-data mount. Optional bounded /tmp emptyDir. automountServiceAccountToken=false; worker scheduling; nonroot, RuntimeDefault seccomp, no privilege escalation, drop ALL.

Ingress `syncthing-mcp.${PUBLIC_DOMAIN}` with native bearer authentication and TLS, no browser OAuth redirects. Explicit allowed hosts include ingress, service discovery names and probe-compatible health behavior. Blackbox /healthz plus liveness/readiness probes. Secret material supplied by ESO/OpenBao, bearer generated independently; reloader annotations cover consumed secrets.

Allow ingress only from nginx and monitoring, and egress only to DNS and the selected tools/syncthing API on port 8384. Add reciprocal Syncthing ingress allowance scoped to the MCP pod. No Internet access at runtime. Start with the existing tools/syncthing hub only; multiple instances are supported but require explicit configuration/network policy.

Verify Flux/Helm/pod readiness, valid and invalid bearer behavior, core reads against the real hub, absence/rejection of writes, denied egress, blackbox health, image identity and provenance. Do not mutate production Syncthing to test writes.

## Reviews and completion

Adversarial reviews challenge design first, then implementation/security and supply chain. The final step is a fresh encompassing gpt-6.1-sol adversarial review of exact source commit, published digest, workflow results and live manifests. Fix findings, rerun checks and obtain review of changed artifacts before reporting completion. Report residual limitations honestly.

## Primary research

- https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- https://py.sdk.modelcontextprotocol.io/whats-new/
- https://py.sdk.modelcontextprotocol.io/run/deploy/
- https://docs.syncthing.net/dev/rest.html
- https://docs.syncthing.net/rest/config.html
- https://github.com/syncthing/syncthing/blob/v2.1.5/lib/api/confighandler.go
- https://github.com/actions/attest
- https://docs.docker.com/build/ci/github-actions/attestations/
- https://docs.renovatebot.com/modules/manager/pep621/
