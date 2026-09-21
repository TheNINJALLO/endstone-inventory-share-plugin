from types import SimpleNamespace
from unittest.mock import Mock


def setup_join(plugin, *, inv_json=None):
    callbacks = []
    plugin._accepting = True
    player = SimpleNamespace(xuid="123", name="TestPlayer", is_valid=True, inventory=Mock(), kick=Mock(),
                             send_message=Mock(), exp_level=0, exp_progress=0.0, scoreboard_tags=[])
    plugin._get_or_create_money_objective = Mock(return_value=SimpleNamespace(
        get_score=lambda player: SimpleNamespace(value=0),
    ))
    plugin.fake_server.scheduler = SimpleNamespace(run_task=lambda owner, callback, **kwargs: callbacks.append(callback))
    plugin.fake_server.get_player = Mock(return_value=player)
    plugin.store = SimpleNamespace(save=Mock(), claim=Mock(return_value={
        "unresolved_items": None, "player_inv": inv_json, "player_enderchest": None,
        "player_xp_level": 0, "player_xp_progress": 0, "player_money_score": 0,
        "player_tags": None, "player_locations": None, "player_bundles": None,
    }))
    return player, callbacks


def drain(plugin):
    plugin.executor.submit(lambda: None).result(timeout=5)


def test_delayed_restore_cannot_affect_reconnected_session(plugin):
    player, callbacks = setup_join(plugin)
    plugin._begin_join(player)
    drain(plugin)
    plugin.on_player_quit(SimpleNamespace(player=player))
    plugin._sessions[player.xuid] = "new-session"
    plugin._loading_players.add(player.xuid)
    callbacks.pop(0)()
    plugin.fake_server.get_player.assert_not_called()
    assert player.xuid in plugin._loading_players
    assert "new-session" not in plugin._ready_players


def test_failed_database_load_never_allows_saving_local_inventory(plugin):
    player, callbacks = setup_join(plugin)
    plugin.store.claim.side_effect = OSError("database disconnected")
    plugin._extract_player_data = Mock()
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    player.kick.assert_called_once()
    plugin.on_player_quit(SimpleNamespace(player=player))
    drain(plugin)
    plugin._extract_player_data.assert_not_called()
    assert plugin.store.save.call_args.args[2] is None


def test_corrupt_restore_cannot_become_a_ready_inventory(plugin):
    player, callbacks = setup_join(plugin, inv_json="{invalid")
    plugin._extract_player_data = Mock()
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    assert plugin._ready_players == set()
    assert player.xuid in plugin._loading_players
    player.inventory.clear.assert_not_called()
    callbacks.pop(0)()
    player.kick.assert_called_once()
    plugin.on_player_quit(SimpleNamespace(player=player))
    drain(plugin)
    plugin._extract_player_data.assert_not_called()


def test_busy_transfer_retries_without_kick_then_restores(plugin):
    from endstone_inventory_share_plugin.persistence import SessionBusy
    player, callbacks = setup_join(plugin)
    row = plugin.store.claim.return_value
    plugin.store.claim.side_effect = [SessionBusy("previous save pending"), row]
    plugin._begin_join(player)
    drain(plugin)
    player.kick.assert_not_called()
    assert player.xuid in plugin._loading_players
    callbacks.pop(0)()  # One-second retry task; never sleeps on the SQL worker.
    drain(plugin)
    callbacks.pop(0)()  # Apply the successful load.
    assert plugin._sessions[player.xuid] in plugin._ready_players
    player.kick.assert_not_called()
    assert plugin.store.claim.call_count == 2


def test_temporary_database_disconnect_retries(plugin):
    import pymysql
    player, callbacks = setup_join(plugin)
    row = plugin.store.claim.return_value
    plugin.store.claim.side_effect = [pymysql.err.OperationalError(2013, "connection lost"), row]
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    drain(plugin)
    callbacks.pop(0)()
    player.kick.assert_not_called()
    assert plugin._sessions[player.xuid] in plugin._ready_players


def test_busy_retry_stops_at_deadline_and_never_releases_owner(plugin, monkeypatch):
    import endstone_inventory_share_plugin.inventory_share_plugin as module
    from endstone_inventory_share_plugin.persistence import SessionBusy
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    player, callbacks = setup_join(plugin)
    plugin.store.claim.side_effect = SessionBusy("other server online")
    plugin._begin_join(player)
    drain(plugin)
    clock[0] = 16
    callbacks.pop(0)()
    drain(plugin)
    callbacks.pop(0)()
    assert "INV-BUSY" in player.kick.call_args.args[0]
    plugin.store.save.assert_not_called()


def test_legacy_lock_explains_admin_recovery_without_retry(plugin, caplog):
    from endstone_inventory_share_plugin.persistence import LegacySessionBusy
    player, callbacks = setup_join(plugin)
    plugin.store.claim.side_effect = LegacySessionBusy("legacy flag")
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    assert "INV-LEGACY" in player.kick.call_args.args[0]
    assert "invshare recoverlegacy 123 confirm-offline" in caplog.text
    plugin.store.claim.assert_called_once()
    plugin.store.save.assert_not_called()


def test_database_credentials_error_is_not_retried(plugin):
    import pymysql
    player, callbacks = setup_join(plugin)
    plugin.store.claim.side_effect = pymysql.err.OperationalError(1045, "access denied")
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    assert "INV-DB" in player.kick.call_args.args[0]
    plugin.store.claim.assert_called_once()


def test_quit_cancels_a_scheduled_join_retry(plugin):
    from endstone_inventory_share_plugin.persistence import SessionBusy
    player, callbacks = setup_join(plugin)
    plugin.store.claim.side_effect = SessionBusy("busy")
    plugin._begin_join(player)
    drain(plugin)
    plugin.on_player_quit(SimpleNamespace(player=player))
    callbacks.pop(0)()
    drain(plugin)
    plugin.store.claim.assert_called_once()
    assert player.xuid not in plugin._sessions


def test_bad_optional_tags_do_not_kick_or_overwrite_saved_tags(plugin):
    player, callbacks = setup_join(plugin)
    plugin.store.claim.return_value["player_tags"] = "not valid JSON"
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    token = plugin._sessions[player.xuid]
    assert token in plugin._ready_players
    assert plugin._preserved_fields[token] == {"tags"}
    player.kick.assert_not_called()


def test_bad_optional_xp_does_not_kick_or_overwrite_saved_xp(plugin):
    player, callbacks = setup_join(plugin)
    plugin.store.claim.return_value["player_xp_level"] = "invalid legacy XP"
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    token = plugin._sessions[player.xuid]
    assert token in plugin._ready_players
    assert "xp" in plugin._preserved_fields[token]
    player.kick.assert_not_called()


def test_unavailable_money_objective_does_not_replace_saved_money(plugin):
    player, callbacks = setup_join(plugin)
    plugin._get_or_create_money_objective.return_value = None
    plugin.store.claim.return_value["player_money_score"] = 800
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    token = plugin._sessions[player.xuid]
    assert token in plugin._ready_players
    assert "money" in plugin._preserved_fields[token]
    player.kick.assert_not_called()


def test_restore_error_log_includes_underlying_cause(plugin, caplog):
    player, callbacks = setup_join(plugin, inv_json="{invalid")
    plugin._begin_join(player)
    drain(plugin)
    callbacks.pop(0)()
    assert "JSONDecodeError" in caplog.text
    assert "INV-DATA" in caplog.text


def test_loading_blocks_gameplay_but_keeps_connection_packets(plugin):
    player, _ = setup_join(plugin)
    plugin._loading_players.add(player.xuid)
    for packet_id in (19, 30, 77, 144, 147):
        event = SimpleNamespace(player=player, packet_id=packet_id, is_cancelled=False)
        plugin.on_loading_packet(event)
        assert event.is_cancelled
    for packet_id in (0, 21, 115, 312):
        event = SimpleNamespace(player=player, packet_id=packet_id, is_cancelled=False)
        plugin.on_loading_packet(event)
        assert not event.is_cancelled
    plugin._loading_players.clear()
    event = SimpleNamespace(player=player, packet_id=147, is_cancelled=False)
    plugin.on_loading_packet(event)
    assert not event.is_cancelled


def test_loading_blocks_pickup_and_damage(plugin):
    player, _ = setup_join(plugin)
    plugin._loading_players.add(player.xuid)
    pickup = SimpleNamespace(player=player, is_cancelled=False)
    damage = SimpleNamespace(actor=player, is_cancelled=False)
    plugin.on_loading_pickup(pickup)
    plugin.on_loading_damage(damage)
    assert pickup.is_cancelled and damage.is_cancelled


def test_invalid_saved_inventory_shape_does_not_clear_items():
    import pytest
    from endstone_inventory_share_plugin.inventory_share_plugin import load_container_from_json
    for payload in ('{}', 'null', '[null]', '[{"slot":"wrong"}]'):
        inventory = Mock()
        with pytest.raises(ValueError):
            load_container_from_json(payload, inventory)
        inventory.clear.assert_not_called()
