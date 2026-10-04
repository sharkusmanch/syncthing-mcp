# Security

Report vulnerabilities privately through this repository's GitHub **Security → Report a vulnerability** feature. Do not include credentials, file contents, or personal Syncthing configuration in public issues.

The MCP server holds a full-authority upstream Syncthing API key. Read-only mode is enforced by this application's registry and service policy, not by an upstream restricted credential. A process compromise can therefore exceed MCP permissions; use OS/container isolation and narrow network access.

HTTP requires an independent bearer token; one credential is one shared principal for every configured instance. There is no OAuth issuer, per-user authorization, or folder-level read isolation. Keep the endpoint private, terminate TLS for remote connections, and set exact Host/Origin allowlists. Headers from proxies are not trusted automatically. Health endpoints reveal only process readiness.

Configuration projections omit credential/unknown fields. Diagnostics are opt-in and can expose addresses, paths, logs and arbitrary remote text. Known-secret string redaction does not recognize every possible embedded secret. Treat remote content as untrusted data.

Writes are disabled by default, with separate destructive/admin gates. Path validation is lexical against remote-platform rules; Syncthing's filesystem permissions and symlink behavior remain the physical boundary. `confirm=true` prevents accidental invocation; it is not human approval or a separate authorization factor.

The service serializes its own writes, checks optional revisions and independently reads back changes. Syncthing has no atomic compare-and-swap/create-if-absent API: external writers can race these checks. Readback verifies runtime state, not disk durability. Ambiguous writes are never automatically retried.

Upstream URLs are operator-controlled, redirects are refused, environment proxies are ignored, and TLS verification is mandatory. Requests/responses are bounded. HTTP has concurrency/rate limits and full-envelope caps. Trusted-parent stdio uses the official SDK's unbounded line framing; tool argument/result bounds are applied after protocol parsing.

Only the current release is supported. Dependencies and Actions are locked/pinned, updates use Renovate App review, and release attestations bind images to repository/workflow/ref. See [release verification](docs/releases.md).
