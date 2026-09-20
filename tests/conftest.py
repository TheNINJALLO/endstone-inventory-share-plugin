import logging
import os
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from endstone_inventory_share_plugin.inventory_share_plugin import InventorySharePlugin
from endstone_inventory_share_plugin.persistence import InventoryStore, SnapshotJournal


class Harness(InventorySharePlugin):
    @property
    def logger(self):
        return logging.getLogger("inventory-share-test")

    @property
    def server(self):
        return self.fake_server


@pytest.fixture
def plugin(tmp_path):
    plugin = Harness()
    plugin.fake_server = SimpleNamespace(online_players=[])
    plugin.journal = SnapshotJournal(tmp_path / "pending.sqlite3")
    plugin.executor = ThreadPoolExecutor(max_workers=1)
    yield plugin
    if plugin.executor is not None:
        plugin.executor.shutdown(wait=True)


@pytest.fixture
def snapshot():
    return {"xuid": "123", "name": "TestPlayer", "inv_json": '[{"slot":0,"type":"minecraft:diamond","amount":17}]',
            "ec_json": '[{"slot":0,"type":"minecraft:emerald","amount":23}]',
            "xp_level": 19, "xp_progress": 0.25, "money_score": 0, "tags": [],
            "updated_vault": {"inventory": [], "enderchest": []}, "vaulted_count": 0,
            "current_location": {"x": 8, "y": 80, "z": 12, "dimension": "Overworld"},
            "bundle_data": {"bundles": []}}


@pytest.fixture
def mysql(plugin):
    if "INVSHARE_TEST_PORT" not in os.environ:
        pytest.skip("Set INVSHARE_TEST_PORT to an isolated test MySQL/MariaDB")
    plugin.sql_host = os.environ.get("INVSHARE_TEST_HOST", "127.0.0.1")
    plugin.sql_port = int(os.environ["INVSHARE_TEST_PORT"])
    plugin.sql_user = os.environ.get("INVSHARE_TEST_USER", "root")
    plugin.sql_pass = os.environ.get("INVSHARE_TEST_PASSWORD", "")
    plugin.sql_db_name = "invshare_test"
    plugin._ensure_schema()
    conn, cursor = plugin._connect()
    try:
        cursor.execute("DELETE FROM player_data")
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    plugin.store = InventoryStore(plugin._connect, "test-server")
    return plugin
