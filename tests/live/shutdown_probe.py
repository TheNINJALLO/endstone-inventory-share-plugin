"""Real Player/Inventory lifecycle probe loaded only by the disposable runner."""
import json
import os
from pathlib import Path
import traceback

from endstone.event import event_handler, PlayerJoinEvent
from endstone.inventory import ItemStack

from endstone_inventory_share_plugin.inventory_share_plugin import InventorySharePlugin


class Probe(InventorySharePlugin):
    version = "1.0.0"
    api_version = "0.11"

    def save_default_config(self):
        pass

    def load_config(self):
        self.sql_host, self.sql_port = "127.0.0.1", int(os.environ["INVSHARE_LIVE_DB_PORT"])
        self.sql_user, self.sql_pass, self.sql_db_name = "root", "", "invshare_live"
        self.server_name, self.autosave_seconds = "test-server", 30

    def on_enable(self):
        self.output = Path(os.environ["INVSHARE_LIVE_OUTPUT"])
        self.phase = os.environ["INVSHARE_LIVE_PHASE"]
        self.stage = 0
        super().on_enable()
        self.probe_task = self.server.scheduler.run_task(self, self.tick_probe, delay=20, period=2)

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        # Make the local world inventory deliberately wrong. A passing restore
        # must come from MySQL, not from BDS's own player-data save.
        if self.phase == "restore":
            event.player.inventory.clear()
            event.player.ender_chest.clear()
            event.player.inventory.set_item(0, ItemStack("minecraft:dirt", 1))
            event.player.exp_level = 1
        super().on_player_join(event)

    def read(self, player):
        data = self._extract_player_data(player)
        return {key: json.loads(data[key]) if key in ("inv_json", "ec_json") else data[key]
                for key in ("xuid", "inv_json", "ec_json", "xp_level", "xp_progress", "money_score", "tags")}

    def seed(self, player, count):
        player.inventory.clear()
        player.ender_chest.clear()
        player.inventory.set_item(0, ItemStack("minecraft:diamond", count))
        sword = ItemStack("minecraft:diamond_sword", 1)
        meta = sword.item_meta
        meta.display_name = "Survives restart"
        meta.lore = ["NBT lifecycle regression"]
        meta.damage = 7
        sword.set_item_meta(meta)
        player.inventory.set_item(8, sword)
        player.inventory.helmet = ItemStack("minecraft:diamond_helmet", 1)
        player.inventory.item_in_off_hand = ItemStack("minecraft:shield", 1)
        player.ender_chest.set_item(4, ItemStack("minecraft:emerald", count - 3))
        player.exp_level, player.exp_progress = 23, 0.25
        self._get_or_create_money_objective().get_score(player).value = 0
        for tag in list(player.scoreboard_tags):
            player.remove_scoreboard_tag(tag)
        player.add_scoreboard_tag("restart_checked")

    def tick_probe(self):
        try:
            players = list(self.server.online_players)
            if not players or self._sessions.get(players[0].xuid) not in self._ready_players:
                return
            player = players[0]
            token = self._sessions[player.xuid]
            if self.phase == "restore":
                actual = self.read(player)
                expected = json.loads((self.output.parent / "expected.json").read_text())
                assert actual == expected, f"Restore differs: {actual!r} != {expected!r}"
                self.finish({"passed": True, "phase": self.phase, "restored": actual})
            elif self.stage == 0:
                self.seed(player, 17 if self.phase == "seed" else 45)
                if self.phase == "crash":
                    def unavailable():
                        raise OSError("probe: database unavailable after snapshot")
                    self.store.connect = unavailable
                self._autosave()
                self.stage = 1
            elif self._pending_autosaves[token].done():
                if self.phase == "seed":
                    assert self._pending_autosaves[token].result() is True
                    # Latest changes have NOT autosaved: shutdown must capture them.
                    self.seed(player, 37)
                else:
                    assert self._pending_autosaves[token].result() is False
                    assert self.journal.entries()
                expected = self.read(player)
                (self.output.parent / "expected.json").write_text(json.dumps(expected))
                self.finish({"passed": True, "phase": self.phase, "expected": expected})
        except Exception:
            self.finish({"passed": False, "error": traceback.format_exc()})

    def finish(self, result):
        self.probe_task.cancel()
        (self.output / "probe.json").write_text(json.dumps(result, indent=2))
