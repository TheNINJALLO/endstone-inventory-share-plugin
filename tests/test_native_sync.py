import hashlib
from unittest.mock import Mock

import pytest

from endstone_inventory_share_plugin import native_sync


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    binary = tmp_path / "bedrock_server"
    binary.write_bytes(b"test executable")
    monkeypatch.setattr(native_sync, "_library", None)
    monkeypatch.setattr(native_sync.sys, "platform", "linux")
    monkeypatch.setattr(native_sync.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(native_sync, "version", lambda name: "0.11.12")
    monkeypatch.setattr(native_sync, "_executable", lambda: binary)
    loader = Mock()
    loader.return_value.invshare_refresh.return_value = 1
    monkeypatch.setattr(native_sync.ctypes, "PyDLL", loader)
    return binary, loader


def test_unknown_server_binary_never_loads_native_code(runtime):
    _, loader = runtime
    with pytest.raises(RuntimeError, match="Unsupported Bedrock binary"):
        native_sync.ensure_native()
    loader.assert_not_called()


def test_unknown_endstone_version_never_loads_native_code(runtime, monkeypatch):
    _, loader = runtime
    monkeypatch.setattr(native_sync, "version", lambda name: "0.12.0")
    with pytest.raises(RuntimeError, match="requires Endstone"):
        native_sync.ensure_native()
    loader.assert_not_called()


def test_qualified_runtime_loads_once_and_propagates_native_failure(runtime, monkeypatch):
    binary, loader = runtime
    monkeypatch.setattr(native_sync, "PROFILES", {
        "linux": ("inventory_sync.so", hashlib.sha256(binary.read_bytes()).hexdigest()),
    })
    inventory = object()
    native_sync.refresh_inventory(inventory)
    native_sync.refresh_inventory(inventory)
    assert loader.call_count == 1
    assert loader.return_value.invshare_refresh.call_count == 2
    loader.return_value.invshare_refresh.return_value = -1
    with pytest.raises(RuntimeError, match="refresh failed"):
        native_sync.refresh_inventory(inventory)
