from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Barrier

import pytest

from endstone_inventory_share_plugin.persistence import InventoryStore, SessionBusy, StaleSession, recover_pending

pytestmark = pytest.mark.mysql


def row(plugin):
    conn, cursor = plugin._connect()
    try:
        cursor.execute("SELECT player_inv,player_enderchest,is_logged_in,session_token,"
                       "player_xp_level,player_money_score,player_tags,player_locations "
                       "FROM player_data WHERE player_xuid='123'")
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def test_final_save_and_new_server_restore(mysql, snapshot):
    mysql.store.claim("123", "first")
    mysql.store.save("123", "first", snapshot, release=True)
    saved = row(mysql)
    assert saved[:5] == (snapshot["inv_json"], snapshot["ec_json"], 0, None, 19)
    second = InventoryStore(mysql._connect, "second-server")
    restored = second.claim("123", "second")
    assert restored["player_inv"] == snapshot["inv_json"]
    assert restored["player_enderchest"] == snapshot["ec_json"]
    assert restored["player_xp_level"] == 19


def test_only_one_concurrent_server_can_claim(mysql):
    barrier = Barrier(2)

    def claim(token):
        barrier.wait(timeout=5)
        try:
            mysql.store.claim("123", token)
            return True
        except SessionBusy:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim, token) for token in ("first", "second")]
        assert sorted(f.result(timeout=10) for f in futures) == [False, True]


def test_rejected_connection_cannot_unlock_another_server(mysql):
    mysql.store.claim("123", "owner")
    with pytest.raises(SessionBusy):
        mysql.store.claim("123", "rejected")
    with pytest.raises(StaleSession):
        mysql.store.save("123", "rejected", release=True)
    assert row(mysql)[2:4] == (1, "owner")


def test_older_session_cannot_overwrite_new_owner(mysql, snapshot):
    mysql.store.claim("123", "old")
    mysql.store.save("123", "old", snapshot, release=True)
    mysql.store.claim("123", "new")
    newer = deepcopy(snapshot)
    newer["xp_level"] = 38
    mysql.store.save("123", "new", newer)
    with pytest.raises(StaleSession):
        mysql.store.save("123", "old", snapshot, release=True)
    assert row(mysql)[2:5] == (1, "new", 38)


def test_crash_recovery_replays_latest_local_snapshot(mysql, snapshot):
    mysql.store.claim("123", "crashed")
    mysql.journal.put("crashed", "123", snapshot)
    assert recover_pending(mysql.store, mysql.journal, mysql.logger) == 0
    assert row(mysql)[:5] == (snapshot["inv_json"], snapshot["ec_json"], 0, None, 19)
    assert mysql.journal.entries() == []


def test_recovery_discards_journal_after_commit_before_cleanup(mysql, snapshot):
    mysql.store.claim("123", "old")
    mysql.journal.put("old", "123", snapshot)
    mysql.store.save("123", "old", snapshot, release=True)
    mysql.store.claim("123", "new")
    newer = deepcopy(snapshot)
    newer["xp_level"] = 40
    mysql.store.save("123", "new", newer)
    assert recover_pending(mysql.store, mysql.journal, mysql.logger) == 0
    assert row(mysql)[2:5] == (1, "new", 40)
    assert mysql.journal.entries() == []


def test_crash_during_load_releases_only_its_own_lock(mysql, snapshot):
    mysql.store.claim("123", "previous")
    mysql.store.save("123", "previous", snapshot, release=True)
    mysql.journal.put("loading", "123")
    mysql.store.claim("123", "loading")
    assert recover_pending(mysql.store, mysql.journal, mysql.logger) == 0
    assert row(mysql)[:5] == (snapshot["inv_json"], snapshot["ec_json"], 0, None, 19)


def test_mid_transaction_failure_does_not_release_or_partially_save(mysql, snapshot):
    mysql.store.claim("123", "owner")
    mysql.store.save("123", "owner", snapshot)
    mysql.journal.put("owner", "123", snapshot)
    connect = mysql._connect

    class FailRelease:
        def __init__(self, cursor):
            self.cursor = cursor

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def execute(self, sql, args=None):
            if "SET is_logged_in=0" in sql:
                raise OSError("injected failure after inventory UPDATE")
            return self.cursor.execute(sql, args)

    def failing_connect():
        conn, cursor = connect()
        return conn, FailRelease(cursor)

    broken = InventoryStore(failing_connect, "test-server")
    newer = deepcopy(snapshot)
    newer["xp_level"] = 30
    with pytest.raises(OSError):
        broken.save("123", "owner", newer, release=True)
    assert row(mysql)[2:5] == (1, "owner", 19)


def test_legitimate_zero_money_and_removed_tags_persist(mysql, snapshot):
    mysql.store.claim("123", "owner")
    before = deepcopy(snapshot)
    before.update(money_score=500, tags=["old_tag"])
    mysql.store.save("123", "owner", before)
    mysql.store.save("123", "owner", snapshot, release=True)
    assert row(mysql)[5:7] == (0, "[]")


def test_locations_from_other_servers_survive_handoff(mysql, snapshot):
    mysql.store.claim("123", "one")
    mysql.store.save("123", "one", snapshot, release=True)
    other = InventoryStore(mysql._connect, "other-server")
    other.claim("123", "two")
    other.save("123", "two", snapshot, release=True)
    assert set(json.loads(row(mysql)[7])) == {"test-server", "other-server"}


def test_legacy_text_login_flag_migrates_without_unlocking(mysql):
    conn, cursor = mysql._connect()
    try:
        cursor.execute("ALTER TABLE player_data MODIFY is_logged_in TINYTEXT")
        cursor.execute("INSERT INTO player_data (player_xuid,is_logged_in) VALUES ('123','True')")
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    mysql._ensure_schema()
    assert row(mysql)[2] == 1
    with pytest.raises(SessionBusy):
        mysql.store.claim("123", "new")


def test_console_legacy_recovery_preserves_inventory(mysql, snapshot):
    mysql.store.claim("123", "old")
    mysql.store.save("123", "old", snapshot, release=True)
    conn, cursor = mysql._connect()
    try:
        cursor.execute("UPDATE player_data SET is_logged_in=1 WHERE player_xuid='123'")
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    assert mysql.store.release_legacy("123")
    assert row(mysql)[:5] == (snapshot["inv_json"], snapshot["ec_json"], 0, None, 19)
    restored = mysql.store.claim("123", "new")
    assert restored["player_inv"] == snapshot["inv_json"]


def test_console_legacy_recovery_cannot_unlock_token_owner(mysql):
    mysql.store.claim("123", "owner")
    assert not mysql.store.release_legacy("123")
    assert row(mysql)[2:4] == (1, "owner")


def test_failed_local_save_is_recovered_before_reconnect(mysql, snapshot):
    from types import SimpleNamespace
    mysql.store.claim("123", "previous")
    mysql.journal.put("previous", "123", snapshot)
    mysql.fake_server.scheduler = SimpleNamespace(run_task=lambda *args, **kwargs: None)
    mysql._accepting = True
    mysql._begin_join(SimpleNamespace(xuid="123", name="TestPlayer"))
    mysql.executor.submit(lambda: None).result(timeout=5)
    assert row(mysql)[:2] == (snapshot["inv_json"], snapshot["ec_json"])
    assert row(mysql)[2:5] == (1, mysql._sessions["123"], 19)
    assert all(token != "previous" for token, _, _ in mysql.journal.entries())


def test_background_recovery_does_not_unlock_active_players(mysql, snapshot):
    mysql.store.claim("123", "online")
    mysql.journal.put("online", "123", snapshot)
    mysql._sessions["123"] = "online"
    mysql._autosave()
    mysql.executor.submit(lambda: None).result(timeout=5)
    assert row(mysql)[2:4] == (1, "online")


def test_preserved_optional_fields_survive_saves_and_recovery(mysql, snapshot):
    mysql.store.claim("123", "owner")
    original = deepcopy(snapshot)
    original.update(money_score=800, tags=["keep"], xp_level=42)
    mysql.store.save("123", "owner", original)
    latest = deepcopy(snapshot)
    latest["preserve_fields"] = ["xp", "money", "tags"]
    latest["inv_json"] = "[]"
    mysql.journal.put("owner", "123", latest)
    assert recover_pending(mysql.store, mysql.journal, mysql.logger) == 0
    saved = row(mysql)
    assert saved[0] == "[]"
    assert saved[4:7] == (42, 800, '["keep"]')
