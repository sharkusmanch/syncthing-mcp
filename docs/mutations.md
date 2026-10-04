# Mutation policy and outcomes

Every mutation requires `ALLOW_WRITES=true`. Destructive and administrative operations also require their corresponding gates, regardless of discovery filters. Destructive operations require explicit `confirm=true`; that is an accidental-action guard, not proof of human consent. Synchronization is not backup: changes can propagate to every peer.

## Fields

Unknown fields, identity changes in generic patches and invalid nested shapes are rejected. The authoritative reviewed allowlists and type checks are in [`policy.py`](../src/syncthing_mcp/policy.py), derived from Syncthing 2.1.5.

| Object | Ordinary write fields | Additional admin fields / restrictions |
|---|---|---|
| Folder | `label`, `paused`, `rescanIntervalS`, `fsWatcherEnabled`, `fsWatcherDelayS` | Paths, explicit peers, filesystem/type, versioning, permission/ownership/xattr flags, resource and scan settings; destination roots enforced |
| Device | `name`, `paused`, `compression`, `maxSendKbps`, `maxRecvKbps` | Addresses, certificate/trust, introduction, auto-accept, network and connection settings |
| Defaults | None | Explicit field policy; inherited defaults validated when creating |
| Options | None | Enumerated network/discovery, bandwidth, reporting and runtime settings |
| GUI / LDAP | None | Enumerated security settings; no API-key rotation through this server, unsafe bypass flags rejected; effective UNIX GUI addresses require allowed destination roots, destructive authority and confirmation |

No root configuration replacement, external-command versioner, arbitrary method/URL/body proxy, or ignored-device workflow requiring root replacement exists. Simple, trashcan and staggered versioning are supported with reviewed parameters and archive destination checks. `#include` ignores and transitions to/from `receiveencrypted` are excluded.

## Writes

Updates fetch current state, compare optional `expected_revision`, preserve unrelated nested properties, and PUT the controlled merge. Arrays are explicit replacement values, not implicit append operations. Revisions hash current upstream objects; obtain them from individual configuration reads. Local locks serialize this server's writes only. Other API/UI clients can race revision and duplicate-create checks because Syncthing has no atomic compare-and-swap or create-if-absent.

For version restoration, `expected_revision` refers to the raw folder configuration fingerprint returned by `syncthing_folder_config`. The server fetches that configuration and rejects a stale revision before fetching archived versions or submitting restoration. This guard does not lock the archive inventory or prevent another client from changing configuration after preflight.

Syncthing treats raw GUI addresses beginning with `/` as UNIX socket paths and removes the destination before binding. Every GUI configuration change restarts its listener, including theme and socket-permission changes. An update whose effective GUI address is a UNIX socket therefore requires that path to pass the instance's `allowed_paths`, `ALLOW_DESTRUCTIVE=true`, and explicit `confirm=true`. TCP GUI updates retain their ordinary write/admin requirements. These path checks are lexical; they do not resolve remote symlinks. Syncthing's operating-system permissions remain the physical confinement boundary. Listener changes can interrupt API access, leaving readback and the overall outcome unknown.

GUI updates also require a successful `/rest/system/status` preflight with boolean `guiAddressOverridden=false`. Runtime address overrides such as `STGUIADDRESS` or `--gui-address` can make the active listener differ from stored configuration, so this server refuses every GUI mutation while an override is active; use manual administration instead. Missing, malformed or unavailable override status fails closed before any GUI write.

Creation refuses an existing ID, selects peers explicitly, validates inherited settings, and creates paused. Ignore initialization/readback must succeed before a requested resume. Pending acceptance requires an actual matching offer. Dismissing an offer is temporary; it does not permanently block a peer or folder. Destination allowlists are required for creation/path changes; empty roots deny them.

Results distinguish `request_outcome`, `readback_verified`, `outcome`, `persistence`, and `restart_required`. `verified` means the requested effective runtime state was independently observed, not that a disk durability check was performed. `accepted` means an asynchronous operation was accepted. A failed request with matching subsequent state remains ambiguous. `restart_required=null` means unknown. Timeouts and ambiguous writes are never automatically replayed.

Scanning is synchronous upstream with a longer deadline. Override/revert are asynchronous and can propagate destructive changes. Version restore checks availability and inspects per-file errors even on HTTP200. Removing a folder removes configuration, not its existing local files. Database reset accepts one explicitly named paused folder per invocation because Syncthing restarts after each reset; reset-all is excluded. External clients can race preflight, so failures can still represent partial effects.

The initial cluster deployment enables no mutations. Real write integration tests use an isolated temporary Syncthing profile with no remote peers.
