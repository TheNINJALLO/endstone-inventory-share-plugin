"""Load the real plugin with Endstone's optional facade packages unavailable."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("missing", [(), ("level",), ("inventory",), ("level", "inventory")])
def test_entry_point_loads_without_facades(tmp_path, missing):
    source = Path(__file__).parents[1] / "src" / "endstone_inventory_share_plugin"
    shutil.copytree(source, tmp_path / source.name, ignore=shutil.ignore_patterns("__pycache__"))
    script = f"""
import importlib.abc
from importlib.metadata import EntryPoint
import sys

missing = {{'endstone.' + name for name in {missing!r}}}
class MissingFacades(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in missing:
            raise ModuleNotFoundError('No module named ' + fullname, name=fullname)
sys.meta_path.insert(0, MissingFacades())

entry = EntryPoint(name='inventory-share-plugin',
                  value='endstone_inventory_share_plugin:InventorySharePlugin', group='endstone')
plugin = entry.load()
from endstone_inventory_share_plugin.inventory_share_plugin import Location, ItemStack
from endstone import level, inventory
assert plugin.__name__ == 'InventorySharePlugin'
assert Location is level.Location
assert ItemStack is inventory.ItemStack
assert not missing.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
