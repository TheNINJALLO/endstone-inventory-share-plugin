"""Slot restore invariants; real BDS stack-ID regression lives in tests/live."""
import json
from types import SimpleNamespace

import pytest

from endstone_inventory_share_plugin import inventory_share_plugin as module


class Inventory:
    size = 3

    def __init__(self):
        self.items = ["old", "old", "old"]
        for attr in module.ARMOR_SLOTS.values():
            setattr(self, attr, "old")

    def set_item(self, slot, item):
        self.items[slot] = item


@pytest.fixture
def decode(monkeypatch):
    def deserialize(data, **kwargs):
        return None if data["type"] == "missing:item" else data
    monkeypatch.setattr(module, "deserialize_item", deserialize)


def test_restore_clears_absent_slots_and_keeps_all_equipment(decode):
    inv = Inventory()
    items = [{"slot": 1, "type": "minecraft:shield"}]
    items += [{"slot": slot, "type": f"item:{name}"} for slot, name in module.ARMOR_SLOTS.items()]
    assert module.load_inventory_from_json(json.dumps(items), inv) == []
    assert inv.items == [None, items[0], None]
    for item in items[1:]:
        assert getattr(inv, module.ARMOR_SLOTS[item["slot"]]) == item


def test_empty_snapshot_clears_equipment_without_nonempty_air_stacks(decode):
    inv = Inventory()
    module.load_inventory_from_json("[]", inv)
    assert inv.items == [None] * inv.size
    assert all(getattr(inv, attr) is None for attr in module.ARMOR_SLOTS.values())


def test_vaulted_item_can_fill_an_empty_slot_record(decode):
    inv = Inventory()
    item = {"slot": 0, "type": "minecraft:shield", "nbt": {"custom": "preserved"}}
    missing = {"slot": -1, "type": "missing:item"}
    outside = {"slot": 100, "type": "minecraft:diamond"}
    unresolved = module.load_inventory_from_json(json.dumps([
        {"slot": 0, "type": None}, item, missing, outside,
    ]), inv)
    assert inv.items == [item, None, None]
    assert inv.helmet is None
    assert unresolved == [missing, outside]


@pytest.mark.parametrize("payload", ['{}', '[{"slot": "bad"}]', 'invalid'])
def test_bad_snapshot_does_not_change_live_slots(payload):
    inv = Inventory()
    before = vars(inv).copy()
    with pytest.raises(ValueError):
        module.load_inventory_from_json(payload, inv)
    assert vars(inv) == before


def test_native_write_failure_propagates_to_join_guard(decode):
    def failed_write(slot, item):
        raise RuntimeError("native write failed")
    inv = SimpleNamespace(size=1, set_item=failed_write)
    with pytest.raises(RuntimeError, match="native write failed"):
        module.load_inventory_from_json('[{"slot":0,"type":"minecraft:shield"}]', inv)


def test_ender_chest_replaces_slots_and_preserves_unresolved_items(decode):
    inv = Inventory()
    item = {"slot": 2, "type": "minecraft:diamond"}
    missing = {"slot": 1, "type": "missing:item"}
    assert module.load_container_from_json(json.dumps([item, missing]), inv) == [missing]
    assert inv.items == [None, None, item]
