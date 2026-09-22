"""Real Player/Inventory lifecycle probe loaded only by the disposable runner."""
import json
import os
from pathlib import Path
import traceback
import pymysql

from endstone.event import event_handler, PlayerJoinEvent, PacketReceiveEvent, EventPriority
from endstone.inventory import ItemStack

from endstone_inventory_share_plugin.inventory_share_plugin import InventorySharePlugin


class Probe(InventorySharePlugin):
    version = "1.0.0"
    api_version = "0.11"
    commands = InventorySharePlugin.commands

    def save_default_config(self):
        pass

    def load_config(self):
        self.sql_host, self.sql_port = "127.0.0.1", int(os.environ["INVSHARE_LIVE_DB_PORT"])
        self.sql_user, self.sql_pass = "root", ""
        self.sql_db_name = os.environ.get("INVSHARE_LIVE_DATABASE", "invshare_live")
        self.server_name, self.autosave_seconds = "test-server", 30

    def on_enable(self):
        self.output = Path(os.environ["INVSHARE_LIVE_OUTPUT"])
        self.phase = os.environ["INVSHARE_LIVE_PHASE"]
        self.stage = 0
        self.claim_attempts = 0
        self.blocked_packets = 0
        super().on_enable()
        self.probe_task = self.server.scheduler.run_task(self, self.tick_probe, delay=20, period=2)

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        # Make the local world inventory deliberately wrong. A passing restore
        # must come from MySQL, not from BDS's own player-data save.
        if self.phase in {"restore", "transient", "handoff", "recovery", "metadata", "legacy-null", "legacy-empty"}:
            event.player.inventory.clear()
            event.player.ender_chest.clear()
            event.player.inventory.set_item(0, ItemStack("minecraft:dirt", 1))
            event.player.exp_level = 1
        original_claim = self.store.claim
        if self.phase in {"transient", "handoff"}:
            def claim(xuid, token):
                self.claim_attempts += 1
                if self.phase == "transient" and self.claim_attempts <= 2:
                    raise pymysql.err.OperationalError(2013, "probe temporary connection loss")
                if self.phase == "handoff" and self.claim_attempts == 1:
                    row = original_claim(xuid, "previous-server")
                    data = self.snapshot_from_row(row, xuid)
                    data["xp_level"] += 1
                    expected_path = self.output.parent / "expected.json"
                    expected = json.loads(expected_path.read_text())
                    expected["xp_level"] = data["xp_level"]
                    expected_path.write_text(json.dumps(expected))
                    self.server.scheduler.run_task(
                        self, lambda: self.executor.submit(self.store.save, xuid, "previous-server", data, release=True),
                        delay=60,
                    )
                return original_claim(xuid, token)
            self.store.claim = claim
        elif self.phase == "recovery":
            xuid = event.player.xuid
            row = original_claim(xuid, "failed-quit")
            data = self.snapshot_from_row(row, xuid)
            self.journal.put("failed-quit", xuid, data)
            original_save = self.store.save
            def unavailable(*args, **kwargs):
                raise pymysql.err.OperationalError(2013, "probe failed disconnect save")
            self.store.save = unavailable
            assert self._persist_snapshot(xuid, "failed-quit", data, True) is False
            self.store.save = original_save
        elif self.phase in {"legacy-null", "legacy-empty"}:
            conn, cursor = self._connect()
            try:
                cursor.execute("UPDATE player_data SET is_logged_in=1,session_token=%s WHERE player_xuid=%s",
                               (None if self.phase == "legacy-null" else "", event.player.xuid))
                assert cursor.rowcount == 1
                conn.commit()
            finally:
                cursor.close()
                conn.close()
        elif self.phase == "metadata":
            conn, cursor = self._connect()
            try:
                cursor.execute("UPDATE player_data SET player_tags=%s WHERE player_xuid=%s",
                               ("invalid legacy tags", event.player.xuid))
                conn.commit()
            finally:
                cursor.close()
                conn.close()
            expected_path = self.output.parent / "expected.json"
            expected = json.loads(expected_path.read_text())
            expected["tags"] = list(event.player.scoreboard_tags)
            expected_path.write_text(json.dumps(expected))
        super().on_player_join(event)

    @staticmethod
    def snapshot_from_row(row, xuid):
        return {"xuid": xuid, "name": "InventoryTest", "inv_json": row["player_inv"],
                "ec_json": row["player_enderchest"], "xp_level": row["player_xp_level"],
                "xp_progress": row["player_xp_progress"], "money_score": row["player_money_score"],
                "tags": json.loads(row["player_tags"] or "[]"),
                "updated_vault": json.loads(row["unresolved_items"] or "{}"),
                "current_location": json.loads(row["player_locations"] or "{}").get("test-server", {}),
                "bundle_data": None}

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_loading_packet(self, event: PacketReceiveEvent):
        super().on_loading_packet(event)
        if event.is_cancelled:
            self.blocked_packets += 1

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
            if self.phase in {"restore", "transient", "handoff", "recovery", "metadata", "legacy-null", "legacy-empty"}:
                actual = self.read(player)
                expected = json.loads((self.output.parent / "expected.json").read_text())
                assert actual == expected, f"Restore differs: {actual!r} != {expected!r}"
                if self.phase in {"transient", "handoff"}:
                    assert self.claim_attempts >= 3
                    assert self.blocked_packets > 0
                if self.phase == "recovery":
                    assert all(token != "failed-quit" for token, _, _ in self.journal.entries())
                if self.phase == "metadata":
                    assert "tags" in self._preserved_fields[token]
                if self.phase in {"legacy-null", "legacy-empty"}:
                    conn, cursor = self._connect()
                    try:
                        cursor.execute("SELECT is_logged_in,session_token FROM player_data WHERE player_xuid=%s",
                                       (player.xuid,))
                        assert cursor.fetchone() == (1, token)
                    finally:
                        cursor.close()
                        conn.close()
                self.finish({"passed": True, "phase": self.phase, "restored": actual,
                             "claim_attempts": self.claim_attempts, "blocked_packets": self.blocked_packets})
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
