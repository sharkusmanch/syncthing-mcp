import json

import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.errors import PublicError

KEY = "upstream-test-credential"
BASE = {"SYNCTHING_URL": "http://syncthing.test:8384", "SYNCTHING_API_KEY": KEY}


def test_defaults_and_secret_repr():
    settings = Settings.from_env(BASE)
    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert settings.allow_writes is False
    assert settings.profile == "full"
    assert KEY not in repr(settings)
    assert settings.instances[0].name == "default"


@pytest.mark.parametrize(
    "var,value",
    [
        ("ALLOW_WRITES", "yes"),
        ("PORT", "0"),
        ("REQUEST_TIMEOUT", "nan"),
        ("CONCURRENCY", "10000"),
        ("PROFILE", "everything"),
        ("TRANSPORT", "sse"),
    ],
)
def test_strict_values(var, value):
    with pytest.raises(PublicError):
        Settings.from_env(BASE | {"SYNCTHING_MCP_" + var: value})


def test_policy_dependencies():
    with pytest.raises(PublicError):
        Settings.from_env(BASE | {"SYNCTHING_MCP_ALLOW_ADMIN": "true"})


def test_http_separate_token():
    with pytest.raises(PublicError):
        Settings.from_env(BASE | {"SYNCTHING_MCP_TRANSPORT": "http"})
    with pytest.raises(PublicError):
        Settings.from_env(
            BASE | {"SYNCTHING_MCP_TRANSPORT": "http", "SYNCTHING_MCP_AUTH_TOKEN": KEY}
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@example.test",
        "ftp://example.test",
        "http://example.test?a=1",
        "http://example.test/#x",
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(PublicError) as error:
        Settings.from_env(BASE | {"SYNCTHING_URL": url})
    assert url not in str(error.value)


def test_instances_and_duplicates():
    instance = {
        "name": "one",
        "url": "http://example.test",
        "api_key": KEY,
        "allowed_paths": ["/data"],
    }
    settings = Settings.from_env({"SYNCTHING_MCP_INSTANCES": json.dumps([instance])})
    assert settings.instances[0].allowed_paths == ("/data",)
    with pytest.raises(PublicError):
        Settings.from_env({"SYNCTHING_MCP_INSTANCES": json.dumps([instance, instance])})


def test_unknown_config_fields_and_secret_safe_failures():
    with pytest.raises(PublicError) as error:
        Settings.from_env({"SYNCTHING_MCP_INSTANCES": KEY})
    assert KEY not in str(error.value)
    with pytest.raises(PublicError):
        Settings.from_env(BASE | {"SYNCTHING_MCP_ENABLED_TOOLS": "made_up_tool"})


def test_secret_file_and_conflicts(tmp_path):
    keyfile = tmp_path / "key"
    keyfile.write_text(KEY + "\n")
    settings = Settings.from_env(
        {"SYNCTHING_URL": BASE["SYNCTHING_URL"], "SYNCTHING_MCP_API_KEY_FILE": str(keyfile)}
    )
    assert settings.instances[0].api_key == KEY
    with pytest.raises(PublicError):
        Settings.from_env(BASE | {"SYNCTHING_MCP_API_KEY_FILE": str(keyfile)})
