import pytest

from syncthing_mcp.config import Instance
from syncthing_mcp.errors import PublicError
from syncthing_mcp.safety import destination, opaque_id, redact, relative_path, revision


@pytest.mark.parametrize("value", ["..", ".", "a/b", "a\\b", "a%2fb", "x\x00"])
def test_id_rejects_ambiguous_components(value):
    with pytest.raises(PublicError):
        opaque_id(value)


@pytest.mark.parametrize(
    "value", ["/etc/passwd", "../x", "a/../x", "C:\\x", "\\\\host\\x", "a%2f..%2fx", "a\x00b"]
)
def test_relative_paths(value):
    with pytest.raises(PublicError):
        relative_path(value)


def test_safe_relative_and_id():
    assert relative_path("photos/a b.jpg") == "photos/a b.jpg"
    assert opaque_id("folder name") == "folder%20name"


@pytest.mark.parametrize("value", ["/database", "/data/../other", "~/data", "relative"])
def test_destinations_cannot_escape(value):
    instance = Instance("default", "http://example.test", "key", ("/data",))
    with pytest.raises(PublicError):
        destination(value, instance)


def test_no_roots_denies_and_windows_semantics():
    with pytest.raises(PublicError):
        destination("/data/new", Instance("x", "http://example.test", "key"))
    windows = Instance("x", "http://example.test", "key", ("D:\\Sync",), "windows")
    assert destination("d:\\sync\\folder", windows)
    for value in ["D:relative", "D:\\SyncExtra", "\\\\host\\share", "\\\\?\\D:\\Sync"]:
        with pytest.raises(PublicError):
            destination(value, windows)


def test_recursive_redaction_and_stable_revision():
    result = redact(
        {"apiKey": "secret", "nested": {"password": "x", "text": "my secret"}}, ("secret",)
    )
    assert "secret" not in str(result)
    assert result["nested"]["password"] == "[REDACTED]"
    assert revision({"x": 1, "y": 2}) == revision({"y": 2, "x": 1})


def test_redacts_secrets_in_object_keys():
    assert "credential" not in str(redact({"credential": "x"}, ("credential",)))


def test_peer_readback_handles_added_fields_and_canonical_order():
    from syncthing_mcp.safety import matches

    assert matches(
        {"devices": [{"deviceID": "a", "introducedBy": ""}, {"deviceID": "b"}]},
        {"devices": [{"deviceID": "b"}, {"deviceID": "a"}]},
    )
    assert not matches(
        {"devices": [{"deviceID": "a"}]}, {"devices": [{"deviceID": "a"}, {"deviceID": "b"}]}
    )


@pytest.mark.parametrize(
    "path",
    ["D:\\Sync\\.. \\escape", "D:\\Sync\\file:stream", "D:\\Sync\\CON", "D:\\Sync\\trailing."],
)
def test_windows_ambiguous_components_denied(path):
    with pytest.raises(PublicError):
        destination(path, Instance("x", "http://example.test", "key", ("D:\\Sync",), "windows"))
