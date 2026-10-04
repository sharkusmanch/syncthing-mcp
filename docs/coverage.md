# Tool and endpoint coverage

Generated from the explicit operation registry with `uv run python scripts/document_catalog.py`. Syncthing **2.1.5** is the tested baseline. Each tool has a strict argument schema; inspect MCP discovery for inputs.

All tool names below have the `syncthing_` prefix. `W` requires ALLOW_WRITES, `D` additionally requires ALLOW_DESTRUCTIVE, `A` additionally requires ALLOW_ADMIN. Diagnostics require explicit group/tool opt-in even in full profile. Per-field checks further restrict configuration mutations.

| Tool | Primary upstream route | Group | Gates | Core |
|---|---|---|---|---|
| `instances` | `local metadata` | system | read | yes |
| `overview` | `composite status + folders + folder status` | system | read | yes |
| `system_status` | `/rest/system/status` | system | read | yes |
| `system_version` | `/rest/system/version` | system | read | yes |
| `system_ping` | `/rest/system/ping` | system | read | yes |
| `system_health` | `/rest/noauth/health` | system | read | yes |
| `system_connections` | `/rest/system/connections` | system | read | yes |
| `system_errors` | `/rest/system/error` | system | read |  |
| `system_error_messages` | `/rest/system/error` | diagnostics | read |  |
| `system_discovery` | `/rest/system/discovery` | diagnostics | read |  |
| `system_paths` | `/rest/system/paths` | diagnostics | read |  |
| `system_logs` | `/rest/system/log` | diagnostics | read |  |
| `log_levels` | `/rest/system/loglevels` | diagnostics | read |  |
| `host_browse` | `/rest/system/browse` | diagnostics | read |  |
| `upgrade_available` | `/rest/system/upgrade` | system | read |  |
| `config` | `/rest/config` | config | read |  |
| `restart_required` | `/rest/config/restart-required` | config | read | yes |
| `folders` | `/rest/config/folders` | config | read | yes |
| `devices` | `/rest/config/devices` | config | read | yes |
| `folder_config` | `/rest/config/folders/{folder}` | config | read |  |
| `device_config` | `/rest/config/devices/{device}` | config | read |  |
| `folder_defaults` | `/rest/config/defaults/folder` | config | read |  |
| `device_defaults` | `/rest/config/defaults/device` | config | read |  |
| `ignore_defaults` | `/rest/config/defaults/ignores` | config | read |  |
| `options` | `/rest/config/options` | config | read |  |
| `gui_config` | `/rest/config/gui` | config | read |  |
| `ldap_config` | `/rest/config/ldap` | config | read |  |
| `pending_devices` | `/rest/cluster/pending/devices` | cluster | read |  |
| `pending_folders` | `/rest/cluster/pending/folders` | cluster | read |  |
| `folder_status` | `/rest/db/status` | folder | read | yes |
| `folder_completion` | `/rest/db/completion` | folder | read | yes |
| `folder_errors` | `/rest/folder/errors` | folder | read |  |
| `folder_error_messages` | `/rest/folder/errors` | diagnostics | read |  |
| `file_metadata` | `/rest/db/file` | folder | read |  |
| `folder_browse` | `/rest/db/browse` | folder | read |  |
| `needed_files` | `/rest/db/need` | folder | read | yes |
| `remote_needed_files` | `/rest/db/remoteneed` | folder | read |  |
| `local_changes` | `/rest/db/localchanged` | folder | read |  |
| `ignores` | `/rest/db/ignores` | folder | read |  |
| `file_versions` | `/rest/folder/versions` | folder | read |  |
| `events` | `/rest/events` | events | read | yes |
| `disk_events` | `/rest/events/disk` | events | read |  |
| `device_statistics` | `/rest/stats/device` | stats | read | yes |
| `folder_statistics` | `/rest/stats/folder` | stats | read | yes |
| `validate_device_id` | `/rest/svc/deviceid` | utilities | read |  |
| `languages` | `/rest/svc/lang` | utilities | read |  |
| `random_string` | `/rest/svc/random/string` | utilities | read |  |
| `usage_report` | `/rest/svc/report` | diagnostics | read |  |
| `debug_file` | `/rest/debug/file` | diagnostics | read |  |
| `update_folder` | `/rest/config/folders/{folder}` | config | W | yes |
| `update_device` | `/rest/config/devices/{device}` | config | W | yes |
| `create_folder` | `/rest/config/folders` | config | W A |  |
| `create_device` | `/rest/config/devices` | config | W A |  |
| `accept_folder` | `/rest/config/folders` | config | W A |  |
| `accept_device` | `/rest/config/devices` | config | W A |  |
| `delete_folder` | `/rest/config/folders/{folder}` | config | W D A |  |
| `delete_device` | `/rest/config/devices/{device}` | config | W D A |  |
| `update_folder_defaults` | `/rest/config/defaults/folder` | config | W A |  |
| `update_device_defaults` | `/rest/config/defaults/device` | config | W A |  |
| `update_ignore_defaults` | `/rest/config/defaults/ignores` | config | W D A |  |
| `update_options` | `/rest/config/options` | config | W A |  |
| `update_gui` | `/rest/config/gui` | config | W A |  |
| `update_ldap` | `/rest/config/ldap` | config | W A |  |
| `pause_folder` | `/rest/config/folders/{folder}` | config | W | yes |
| `resume_folder` | `/rest/config/folders/{folder}` | config | W | yes |
| `pause_device` | `/rest/system/pause` | config | W | yes |
| `resume_device` | `/rest/system/resume` | config | W | yes |
| `scan_folder` | `/rest/db/scan` | folder | W | yes |
| `prioritize_file` | `/rest/db/prio` | folder | W |  |
| `clear_errors` | `/rest/system/error/clear` | system | W |  |
| `report_error` | `/rest/system/error` | diagnostics | W A |  |
| `update_log_levels` | `/rest/system/loglevels` | diagnostics | W A |  |
| `dismiss_pending_device` | `/rest/cluster/pending/devices` | cluster | W |  |
| `dismiss_pending_folder` | `/rest/cluster/pending/folders` | cluster | W |  |
| `replace_ignores` | `/rest/db/ignores` | folder | W D |  |
| `restore_versions` | `/rest/folder/versions` | folder | W D |  |
| `override_folder` | `/rest/db/override` | admin | W D A |  |
| `revert_folder` | `/rest/db/revert` | admin | W D A |  |
| `reset_database` | `/rest/system/reset` | admin | W D A |  |
| `restart` | `/rest/system/restart` | admin | W D A |  |
| `shutdown` | `/rest/system/shutdown` | admin | W D A |  |
| `upgrade` | `/rest/system/upgrade` | admin | W D A |  |

## Endpoint coverage boundaries

Reviewed against the [official REST index](https://docs.syncthing.net/dev/rest.html), [config family](https://docs.syncthing.net/rest/config.html), and [debug family](https://docs.syncthing.net/rest/debug.html). Tool count is not a count of distinct endpoints or supported arbitrary payloads.

| Endpoint / capability | Coverage decision |
|---|---|
| GET system, cluster, folder, db, events, stats, svc and health routes | Named tools above; raw diagnostic routes explicitly opt-in |
| GET `/rest/system/log.txt` | Excluded duplicate plaintext format; bounded JSON log tool provided |
| POST `/rest/system/ping` | Excluded redundant mutation-shaped ping; GET supported |
| POST `/rest/system/discovery` | Removed upstream route; no compatibility fallback |
| Deprecated system/config, system/config/insync, folder/pullerrors | Excluded; current config and folder/errors routes used |
| GET `/rest/config` and supported subresources | Safe field projections; credentials and unknown fields omitted |
| PUT/PATCH root config and bulk folders/devices | Excluded whole-config/list replacement; explicit object operations preserve unrelated state |
| Folder/device POST; individual PUT/PATCH/DELETE | Creates and controlled merge via PUT, explicit deletion; no raw arbitrary patch |
| Defaults/options/GUI/LDAP mutations | Reviewed field policy; forbidden unsafe fields fail closed |
| Persistent remote ignore/unignore requiring root replacement | Excluded; pending dismissal is temporary only |
| Debug file | Diagnostic tool provided |
| CPU/heap profiles and support archives | Excluded binary dumps, sensitive content and resource cost |
| Undocumented debug/runtime/metrics endpoints | Excluded; use dedicated operational tooling |
| External versioner commands; #include ignore files | Excluded; remote execution/confinement cannot be safely validated |
| Changes to/from receiveencrypted; encrypted pending offers | Manual setup required; existing unrelated encryption fields preserved |
| Reset-all / multi-folder reset | Excluded; explicit single-folder reset only because each request restarts Syncthing |

Read-only means no mutation request is dispatched; some read endpoints (for example usage report or upgrade availability) may themselves perform upstream computation. No file-content read/write or synchronization transport is exposed.
