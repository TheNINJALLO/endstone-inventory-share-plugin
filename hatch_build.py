"""Package the native bridge built for this release platform."""
import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class NativeBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        path = os.environ.get("INVSHARE_NATIVE_LIBRARY")
        if not path or not Path(path).is_file():
            raise RuntimeError("Build native/ first and set INVSHARE_NATIVE_LIBRARY to inventory_sync.dll or .so")
        library = Path(path).resolve()
        platforms = {"inventory_sync.dll": "win_amd64", "inventory_sync.so": "linux_x86_64"}
        if library.name not in platforms:
            raise RuntimeError("Unexpected inventory refresh library name")
        build_data["pure_python"] = False
        build_data["tag"] = "cp310-abi3-" + platforms[library.name]
        build_data["force_include"][str(library)] = "endstone_inventory_share_plugin/_native/" + library.name
