# Discovery size measurements

Generated with `uv run python scripts/document_catalog.py`; UTF-8 bytes of compact SDK tool definitions including annotations. No tokenizer-specific savings claims.

| Profile | Tools | Catalog bytes |
|---|---:|---:|
| core read-only | 16 | 9,708 |
| full read-only | 40 | 24,355 |
| full all gates + diagnostics | 82 | 49,684 |

Synthetic ping payload: **45 bytes**; dual structured/text CallToolResult: **200 bytes** before JSON-RPC framing. The compatibility text duplicates payload bytes. Core profile, startup allowlists, field selection and bounded list pages reduce context use without replacing typed operations with an opaque dispatcher.
