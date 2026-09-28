"""Invoke the wheel's real restore helpers on a disposable native player."""
import json
import os
from pathlib import Path
import traceback

from endstone.inventory import ItemStack
from endstone.plugin import Plugin

from endstone_inventory_share_plugin.inventory_share_plugin import (
    ARMOR_SLOTS, load_inventory_from_json, save_inventory_to_json,
)


class Probe(Plugin):
    api_version = "0.11"

    def on_enable(self):
        self.root = Path(os.environ["EQUIPMENT_PROBE_OUTPUT"])
        self.last = 0
        self.saved = None
        self.server.scheduler.run_task(self, self.tick, delay=20, period=2)

    def tick(self):
        try:
            players = list(self.server.online_players)
            if not players:
                return
            player = players[0]
            inv = player.inventory
            command = json.loads((self.root / "control.json").read_text())
            if command["id"] != self.last:
                self.last = command["id"]
                action = command["action"]
                if action == "seed":
                    inv.clear()
                    for attr in ARMOR_SLOTS.values():
                        setattr(inv, attr, None)
                    for slot in range(6, inv.size):
                        item = ItemStack("minecraft:diamond", slot + 1)
                        meta = item.item_meta
                        meta.display_name = f"Preserve slot {slot}"
                        meta.lore = ["Inventory Share equipment regression"]
                        item.set_item_meta(meta)
                        inv.set_item(slot, item)
                    # Native commands publish actual stack IDs to the client.
                    # No invented IDs or synthetic inventory packets are used.
                    for slot, item_type in enumerate([
                        "totem_of_undying", "diamond_helmet", "shield",
                        "diamond_chestplate", "diamond_leggings", "diamond_boots",
                    ]):
                        self.server.dispatch_command(self.server.command_sender,
                            f'replaceitem entity "{player.name}" slot.hotbar {slot} {item_type}')
                elif action == "save":
                    self.saved, unresolved = save_inventory_to_json(inv, inv.size)
                    assert not unresolved
                elif action == "scramble":
                    # A different local inventory simulates transfer from another server.
                    for slot in range(inv.size):
                        inv.set_item(slot, ItemStack("minecraft:dirt", 64))
                    for attr in ARMOR_SLOTS.values():
                        setattr(inv, attr, None)
                    self.server.dispatch_command(self.server.command_sender,
                        f'replaceitem entity "{player.name}" slot.hotbar 0 dirt 64')
                elif action == "restore":
                    assert self.saved is not None
                    assert not load_inventory_from_json(self.saved, inv, logger=self.logger, server=self.server)
                    restored, _ = save_inventory_to_json(inv, inv.size)
                    assert json.loads(restored) == json.loads(self.saved), "Items/NBT changed during restore"
                elif action == "empty":
                    self.saved = "[]"
                    assert not load_inventory_from_json(self.saved, inv, logger=self.logger, server=self.server)
                else:
                    raise AssertionError(f"Unknown probe action {action}")
            contents, _ = save_inventory_to_json(inv, inv.size)
            result = {"id": self.last, "items": json.loads(contents),
                      "location": [player.location.x, player.location.y, player.location.z]}
            (self.root / "snapshot.json").write_text(json.dumps(result))
        except (FileNotFoundError, json.JSONDecodeError):
            return  # The test driver may be replacing its small control file.
        except Exception:
            (self.root / "error.txt").write_text(traceback.format_exc())
