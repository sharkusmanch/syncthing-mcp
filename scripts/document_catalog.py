"""Generate reviewed-registry tables and reproducible discovery byte measurements."""

import asyncio
import json
from pathlib import Path

import mcp_types as types

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.registry import OPERATIONS


async def main():
    rows = [
        "# Tool and endpoint coverage",
        "",
        "Generated from the explicit operation registry with "
        "`uv run python scripts/document_catalog.py`. Syncthing **2.1.5** is the tested baseline. "
        "Each tool has a strict argument schema; inspect MCP discovery for inputs.",
        "",
        "All tool names below have the `syncthing_` prefix. `W` requires ALLOW_WRITES, "
        "`D` additionally requires ALLOW_DESTRUCTIVE, `A` additionally requires ALLOW_ADMIN. "
        "Diagnostics require explicit group/tool opt-in even in full profile. "
        "Per-field checks further restrict configuration mutations.",
        "",
        "| Tool | Primary upstream route | Group | Gates | Core |",
        "|---|---|---|---|---|",
    ]
    for op in OPERATIONS:
        gates = (
            "read"
            if op.read_only
            else "W" + (" D" if op.destructive else "") + (" A" if op.admin else "")
        )
        route = (
            "local metadata"
            if op.handler == "instances"
            else (
                "composite status + folders + folder status"
                if op.handler == "overview"
                else op.route
            )
        )
        rows.append(
            f"| `{op.name}` | `{route}` | {op.group} | {gates} | {'yes' if op.core else ''} |"
        )
    rows += [
        "",
        "## Endpoint coverage boundaries",
        "",
        "Reviewed against the [official REST index](https://docs.syncthing.net/dev/rest.html), "
        "[config family](https://docs.syncthing.net/rest/config.html), and "
        "[debug family](https://docs.syncthing.net/rest/debug.html). "
        "Tool count is not a count of distinct endpoints or supported arbitrary payloads.",
        "",
        "| Endpoint / capability | Coverage decision |",
        "|---|---|",
        "| GET system, cluster, folder, db, events, stats, svc and health routes | "
        "Named tools above; raw diagnostic routes explicitly opt-in |",
        "| GET `/rest/system/log.txt` | Excluded duplicate plaintext format; bounded JSON"
        " log tool provided |",
        "| POST `/rest/system/ping` | Excluded redundant mutation-shaped ping; GET supported |",
        "| POST `/rest/system/discovery` | Removed upstream route; no compatibility fallback |",
        "| Deprecated system/config, system/config/insync, folder/pullerrors | "
        "Excluded; current config and folder/errors routes used |",
        "| GET `/rest/config` and supported subresources | Safe field projections; "
        "credentials and unknown fields omitted |",
        "| PUT/PATCH root config and bulk folders/devices | Excluded whole-config/list "
        "replacement; explicit object operations preserve unrelated state |",
        "| Folder/device POST; individual PUT/PATCH/DELETE | Creates and controlled merge"
        " via PUT, explicit deletion; no raw arbitrary patch |",
        "| Defaults/options/GUI/LDAP mutations | Reviewed field policy; forbidden unsafe "
        "fields fail closed |",
        "| Persistent remote ignore/unignore requiring root replacement | Excluded; "
        "pending dismissal is temporary only |",
        "| Debug file | Diagnostic tool provided |",
        "| CPU/heap profiles and support archives | Excluded binary dumps, sensitive "
        "content and resource cost |",
        "| Undocumented debug/runtime/metrics endpoints | Excluded; use dedicated "
        "operational tooling |",
        "| External versioner commands; #include ignore files | Excluded; remote "
        "execution/confinement cannot be safely validated |",
        "| Changes to/from receiveencrypted; encrypted pending offers | Manual setup "
        "required; existing unrelated encryption fields preserved |",
        "| Reset-all / multi-folder reset | Excluded; explicit single-folder reset only "
        "because each request restarts Syncthing |",
        "",
        "Read-only means no mutation request is dispatched; some read endpoints (for example "
        "usage report or upgrade availability) may themselves perform upstream computation. "
        "No file-content read/write or synchronization transport is exposed.",
        "",
    ]
    Path("docs/coverage.md").write_text("\n".join(rows))
    efficiency = [
        "# Discovery size measurements",
        "",
        "Generated with "
        "`uv run python scripts/document_catalog.py`; UTF-8 bytes of compact "
        "SDK tool definitions including annotations. No tokenizer-specific savings claims.",
        "",
        "| Profile | Tools | Catalog bytes |",
        "|---|---:|---:|",
    ]
    for label, updates in [
        ("core read-only", {"SYNCTHING_MCP_PROFILE": "core"}),
        ("full read-only", {}),
        (
            "full all gates + diagnostics",
            {
                "SYNCTHING_MCP_ALLOW_WRITES": "true",
                "SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "true",
                "SYNCTHING_MCP_ALLOW_ADMIN": "true",
                "SYNCTHING_MCP_GROUPS": json.dumps(sorted({op.group for op in OPERATIONS})),
            },
        ),
    ]:
        settings = Settings.from_env(
            {"SYNCTHING_URL": "http://127.0.0.1:9", "SYNCTHING_API_KEY": "synthetic-fixture-key"}
            | updates
        )
        engine = Engine(settings)
        try:
            tools = [
                types.Tool(
                    name=t.name,
                    description=t.description,
                    input_schema=t.input_schema,
                    annotations=types.ToolAnnotations(
                        read_only_hint=t.read_only,
                        destructive_hint=t.destructive,
                        open_world_hint=True,
                    ),
                ).model_dump(by_alias=True, exclude_none=True)
                for t in sorted(engine.tools(), key=lambda t: t.name)
            ]
            size = len(json.dumps(tools, separators=(",", ":")).encode())
            efficiency.append(f"| {label} | {len(tools)} | {size:,} |")
        finally:
            await engine.aclose()
    fixture = {"instance": "fixture", "data": {"ping": "pong"}}
    compact = json.dumps(fixture, separators=(",", ":"))
    envelope = types.CallToolResult(
        content=[types.TextContent(type="text", text=compact)],
        structured_content=fixture,
        is_error=False,
    )
    envelope_bytes = len(envelope.model_dump_json(by_alias=True, exclude_none=True).encode())
    efficiency += [
        "",
        f"Synthetic ping payload: **{len(compact.encode())} bytes**; "
        f"dual structured/text CallToolResult: **{envelope_bytes} bytes** "
        "before JSON-RPC framing. The compatibility text duplicates payload bytes. "
        "Core profile, startup allowlists, field selection and bounded list pages reduce "
        "context use "
        "without replacing typed operations with an opaque dispatcher.",
        "",
    ]
    Path("docs/efficiency.md").write_text("\n".join(efficiency))


if __name__ == "__main__":
    asyncio.run(main())
