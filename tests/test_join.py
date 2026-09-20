from types import SimpleNamespace
from unittest.mock import Mock


def setup_join(plugin, *, inv_json=None):
    callbacks = []
    plugin._accepting = True
    player = SimpleNamespace(xuid="123", name="TestPlayer", is_valid=True, inventory=Mock(), kick=Mock())
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
