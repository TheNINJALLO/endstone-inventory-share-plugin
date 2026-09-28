"""Publish BDS inventory contents with native stack IDs after a shared restore."""
import ctypes
import hashlib
from importlib.metadata import version
from pathlib import Path
import platform
import sys


# Exact server binaries used by the release's live tests. Private BDS virtual
# calls must not run on an unqualified binary merely because an API version fits.
PROFILES = {
    "linux": ("inventory_sync.so", "e93e739f373a84edfff7c9cd76fcb090c2176744b412e1143f1b38e91a49bed4"),
    "win32": ("inventory_sync.dll", "76d547f82e02c18d0986c30b47132c9cc4171d0f2df1c00649e50ff35788b321"),
}
_library = None


def _executable():
    if sys.platform == "linux":
        return Path("/proc/self/exe")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_name = kernel.GetModuleFileNameW
    get_name.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_name.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    size = get_name(None, buffer, len(buffer))
    if not size or size == len(buffer):
        raise RuntimeError("Cannot identify the running Bedrock executable")
    return Path(buffer.value)


def ensure_native():
    global _library
    if _library is not None:
        return _library
    if sys.platform not in PROFILES or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Inventory Share requires Windows/Linux x86-64 BDS 1.26.51.1")
    if version("endstone") not in {"0.11.11", "0.11.12"}:
        raise RuntimeError("Inventory refresh requires Endstone 0.11.11 or 0.11.12 with BDS 1.26.51.1")
    filename, expected = PROFILES[sys.platform]
    digest = hashlib.sha256()
    with _executable().open("rb") as executable:
        for chunk in iter(lambda: executable.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError("Unsupported Bedrock binary for native inventory refresh; use the qualified BDS 1.26.51.1 build")
    # PyDLL retains the GIL, propagates CPython errors, and allows native send
    # callbacks to enter Endstone's Python packet listeners on the server thread.
    library = ctypes.PyDLL(str(Path(__file__).parent / "_native" / filename))
    library.invshare_refresh.argtypes = [ctypes.py_object]
    library.invshare_refresh.restype = ctypes.c_int
    _library = library
    return library


def refresh_inventory(inventory):
    if ensure_native().invshare_refresh(inventory) != 1:
        raise RuntimeError("Native inventory refresh failed")
