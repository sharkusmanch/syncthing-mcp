"""Explicit field-policy matrix; invalid values must fail before upstream writes."""

import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.errors import PublicError
from syncthing_mcp.policy import validate_patch, versioning

ENV = {
    "SYNCTHING_URL": "http://example.test",
    "SYNCTHING_API_KEY": "key",
    "SYNCTHING_MCP_ALLOW_WRITES": "true",
    "SYNCTHING_MCP_ALLOW_ADMIN": "true",
    "SYNCTHING_MCP_ALLOWED_PATHS": '["/data"]',
}
SETTINGS = Settings.from_env(ENV)
INSTANCE = SETTINGS.instances[0]
SAFE = [
    (
        "folder",
        {
            "paused": True,
            "label": "Label",
            "rescanIntervalS": 30,
            "fsWatcherDelayS": 0.5,
            "path": "/data/new",
            "devices": [{"deviceID": "peer", "encryptionPassword": "opaque"}],
            "versioning": {
                "type": "trashcan",
                "params": {"cleanoutDays": "10"},
                "fsType": "basic",
                "fsPath": "versions",
                "cleanupIntervalS": 3600,
            },
            "minDiskFree": {"value": 1, "unit": "%"},
            "xattrFilter": {"entries": [{"match": "*", "permit": True}], "maxTotalSize": 512},
            "filesystemType": "basic",
            "markerName": ".stfolder",
            "type": "receiveonly",
        },
    ),
    (
        "device",
        {
            "name": "Peer",
            "paused": True,
            "compression": "metadata",
            "maxSendKbps": 100,
            "addresses": ["dynamic"],
            "allowedNetworks": ["192.0.2.0/24"],
            "ignoredFolders": [],
            "autoAcceptFolders": False,
            "introducer": False,
            "numConnections": 1,
        },
    ),
    (
        "options",
        {
            "natEnabled": False,
            "listenAddresses": ["tcp://127.0.0.1:22000"],
            "minHomeDiskFree": {"value": 1, "unit": "%"},
            "urAccepted": -1,
            "localAnnounceMCAddr": "::1",
            "urURL": "https://example.test",
            "auditFile": "/data/audit.log",
        },
    ),
    (
        "gui",
        {
            "user": "operator",
            "password": "password-test",
            "useTLS": True,
            "metricsWithoutAuth": False,
            "sessionCookieDurationS": 3600,
            "authMode": "static",
        },
    ),
    (
        "ldap",
        {
            "address": "ldap.test:636",
            "transport": "tls",
            "insecureSkipVerify": False,
            "bindDN": "uid=%s,dc=example,dc=test",
        },
    ),
]


@pytest.mark.parametrize("kind,patch", SAFE)
def test_supported_fields_validate(kind, patch):
    validate_patch(kind, patch, SETTINGS, INSTANCE, effective={"path": "/data/f", **patch})


UNSAFE = [
    ("folder", {"paused": "false"}),
    ("folder", {"rescanIntervalS": -1}),
    ("folder", {"label": 1}),
    ("folder", {"label": "bad\x00"}),
    ("folder", {"fsWatcherDelayS": float("inf")}),
    ("folder", {"path": "/outside"}),
    ("folder", {"devices": [{"deviceID": "x", "extra": True}]}),
    ("folder", {"devices": [{"deviceID": "x"}, {"deviceID": "x"}]}),
    ("folder", {"devices": "peer"}),
    ("folder", {"devices": [{"deviceID": 1}]}),
    ("folder", {"versioning": {"type": "external"}}),
    ("folder", {"minDiskFree": {"unknown": 1}}),
    ("folder", {"minDiskFree": {"unit": "bogus"}}),
    ("folder", {"xattrFilter": {"unknown": 1}}),
    ("folder", {"xattrFilter": {"entries": "invalid"}}),
    ("folder", {"xattrFilter": {"entries": [{"unknown": 1}]}}),
    ("folder", {"type": "invalid"}),
    ("folder", {"filesystemType": "fake"}),
    ("folder", {"markerName": "../outside"}),
    ("device", {"compression": "gzip"}),
    ("device", {"maxSendKbps": -10}),
    ("device", {"addresses": [1]}),
    ("device", {"addresses": "dynamic"}),
    ("device", {"ignoredFolders": [{"id": "ignored"}]}),
    ("options", {"minHomeDiskFree": {"unknown": 1}}),
    ("options", {"minHomeDiskFree": {"value": 1, "unit": "invalid"}}),
    ("options", {"auditFile": "/outside"}),
    ("options", {"listenAddresses": 4}),
    ("gui", {"password": ""}),
    ("gui", {"password": "x" * 73}),
    ("gui", {"metricsWithoutAuth": True}),
    ("gui", {"insecureSkipHostcheck": True}),
    ("gui", {"authMode": "anonymous"}),
    ("gui", {"sessionCookieDurationS": 0}),
    ("ldap", {"transport": "invalid"}),
    ("ldap", {"insecureSkipVerify": True}),
    ("unknown", {"label": "x"}),
]


@pytest.mark.parametrize("kind,patch", UNSAFE)
def test_invalid_field_matrix(kind, patch):
    with pytest.raises(PublicError):
        validate_patch(kind, patch, SETTINGS, INSTANCE, effective={"path": "/data/f", **patch})


@pytest.mark.parametrize(
    "value",
    [
        {"unknown": True},
        {"params": {"command": "evil"}},
        {"fsType": "fake"},
        {"cleanupIntervalS": -1},
        {"params": {"keep": "NaN"}},
        {"params": {"keep": "-1"}},
        {"params": {"versionsPath": "/outside"}},
        {"fsPath": "../escape"},
        {"fsPath": "versions"},
        {"params": {"keep": ""}},
    ],
)
def test_unsafe_versioning_defaults(value):
    with pytest.raises(PublicError):
        versioning(value, INSTANCE, None)


def test_absolute_archive_path_and_size_bounds():
    versioning(
        {"fsPath": "/data/archive", "type": "simple", "params": {"keep": "3"}}, INSTANCE, None
    )
    for patch in [
        {"rescanIntervalS": 2**32},
        {"label": "x" * 4097},
        {"xattrFilter": {"maxTotalSize": -1}},
    ]:
        with pytest.raises(PublicError):
            validate_patch("folder", patch, SETTINGS, INSTANCE)
