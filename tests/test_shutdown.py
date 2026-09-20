from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from endstone_inventory_share_plugin.inventory_share_plugin import serialize_item
from endstone_inventory_share_plugin.persistence import SnapshotJournal


def ready(plugin, snapshot):
    player = SimpleNamespace(xuid="123", name="TestPlayer")
    plugin.fake_server.online_players = [player]
    plugin._sessions["123"] = "session"
    plugin._ready_players.add("session")
    plugin.journal.put("session", "123", snapshot)
    plugin._extract_player_data = Mock(return_value=snapshot)
    plugin.store = SimpleNamespace(save=Mock())
    plugin._accepting = True
    return player


def test_shutdown_orders_final_capture_after_older_save(plugin, snapshot):
    ready(plugin, snapshot)
    entered, resume = Event(), Event()
    saved = []

    def save(xuid, token, data, *, release=False):
        if data["xp_level"] == 1:
            entered.set()
            assert resume.wait(5)
        saved.append((data["xp_level"], release))

    plugin.store.save = save
    old = deepcopy(snapshot)
    old["xp_level"] = 1
    plugin.executor.submit(plugin._persist_snapshot, "123", "session", old)
    assert entered.wait(5)
    # Release the older worker as soon as shutdown queues its new snapshot.
    original = plugin._queue_snapshot

    def final(*args, **kwargs):
        future = original(*args, **kwargs)
        resume.set()
        return future

    plugin._queue_snapshot = final
    plugin.on_disable()
    assert saved == [(1, False), (19, True)]
    assert plugin.journal.entries() == []


def test_shutdown_drains_quit_when_no_players_remain(plugin, snapshot):
    player = ready(plugin, snapshot)
    plugin.on_player_quit(SimpleNamespace(player=player))
    plugin.fake_server.online_players = []
    plugin.on_disable()
    plugin.store.save.assert_called_once_with("123", "session", snapshot, release=True)
    assert plugin.journal.entries() == []


@pytest.mark.parametrize("command", ["stop", " /stop ", "minecraft:stop"])
def test_stop_captures_before_bds_removes_players_without_quit(plugin, snapshot, command):
    ready(plugin, snapshot)
    plugin.on_server_command(SimpleNamespace(command=command))
    plugin.fake_server.online_players = []  # Observed real BDS stop lifecycle.
    plugin.on_disable()
    plugin._extract_player_data.assert_called_once()
    assert plugin.store.save.call_args_list[-1].args == ("123", "session", snapshot)
    assert plugin.store.save.call_args_list[-1].kwargs == {"release": True}
    assert plugin.journal.entries() == []


def test_stop_capture_does_not_unlock_if_command_does_not_stop(plugin, snapshot):
    ready(plugin, snapshot)
    plugin.on_server_command(SimpleNamespace(command="stop"))
    plugin.executor.submit(lambda: None).result(timeout=5)
    plugin.store.save.assert_called_once_with("123", "session", snapshot, release=False)
    assert plugin._accepting
    assert plugin.journal.entries()


def test_other_commands_do_not_capture(plugin, snapshot):
    ready(plugin, snapshot)
    plugin.on_server_command(SimpleNamespace(command="stop invalid_argument"))
    plugin.on_server_command(SimpleNamespace(command="say stop"))
    plugin._extract_player_data.assert_not_called()


def test_shutdown_never_captures_loading_inventory(plugin, snapshot):
    ready(plugin, snapshot)
    plugin._ready_players.clear()
    plugin.journal.put("session", "123")
    plugin.on_disable()
    plugin._extract_player_data.assert_not_called()
    plugin.store.save.assert_called_once_with("123", "session", None, release=True)


def test_failed_save_survives_shutdown_and_journal_reopen(plugin, snapshot):
    ready(plugin, snapshot)
    plugin.store.save.side_effect = OSError("database unavailable")
    plugin.on_disable()
    reopened = SnapshotJournal(plugin.journal.path)
    assert reopened.entries() == [("session", "123", snapshot)]
    assert plugin.store.save.call_count == 2  # original final save plus drain retry


def test_autosave_is_durable_without_releasing_login(plugin, snapshot):
    ready(plugin, snapshot)
    plugin._autosave()
    plugin._pending_autosaves["session"].result(timeout=5)
    assert plugin.journal.entries() == [("session", "123", snapshot)]
    plugin.store.save.assert_called_once_with("123", "session", snapshot, release=False)


def test_slow_autosave_does_not_create_unbounded_queue(plugin, snapshot):
    ready(plugin, snapshot)
    entered, resume = Event(), Event()

    def save(*args, **kwargs):
        entered.set()
        assert resume.wait(5)

    plugin.store.save = save
    try:
        plugin._autosave()
        assert entered.wait(5)
        for _ in range(10):
            plugin._autosave()
        plugin._extract_player_data.assert_called_once()
    finally:
        resume.set()


def test_capture_failure_keeps_last_complete_snapshot(plugin, snapshot):
    ready(plugin, snapshot)
    plugin._extract_player_data.side_effect = RuntimeError("unavailable inventory")
    plugin.on_disable()
    plugin.store.save.assert_called_once_with("123", "session", snapshot, release=True)


def test_serialization_failure_cannot_be_saved_as_air():
    class BrokenItem:
        @property
        def type(self):
            raise RuntimeError("invalid item")

    with pytest.raises(ValueError, match="Failed to serialize slot 8"):
        serialize_item(BrokenItem(), 8)


def test_nbt_failure_cannot_silently_strip_metadata():
    class BrokenNBT:
        type, amount, data = "minecraft:diamond_sword", 1, 0

        @property
        def nbt(self):
            raise RuntimeError("NBT unavailable")

    with pytest.raises(ValueError, match="Could not serialize NBT"):
        serialize_item(BrokenNBT(), 0)


def test_journal_retains_distinct_sessions_for_same_player(plugin, snapshot):
    plugin.journal.put("old", "123", snapshot)
    plugin.journal.put("new", "123")
    plugin.journal.remove("old")
    assert plugin.journal.entries() == [("new", "123", None)]


def test_storage_not_ready_rejects_login(plugin):
    event = SimpleNamespace(is_cancelled=False, kick_message="")
    plugin.on_player_login(event)
    assert event.is_cancelled
    assert "storage is unavailable" in event.kick_message
