import json

import pytest
from endstone.nbt import CompoundTag, ListTag, StringTag, IntTag, ByteTag
from endstone_inventory_share_plugin import inventory_share_plugin as sharing


class Item:
    def __init__(self, kind, amount=1, data=0):
        self.type, self.amount, self.data = kind, amount, data
        self.nbt = CompoundTag()


def bundle():
    item = Item('minecraft:blue_bundle')
    item.nbt = CompoundTag({'storage_item_component_content': ListTag([
        CompoundTag({'Name': StringTag('minecraft:diamond'), 'Count': ByteTag(7),
                     'tag': CompoundTag({'display': CompoundTag({'Lore': ListTag([StringTag('§dEssentials item lore')])})})})
    ]), 'bundle_weight': IntTag(7), 'display': CompoundTag({'Lore': ListTag([StringTag('§aOwner: Ninja ✔')])})})
    return item


def test_bundle_and_custom_lore_survive_inventory_json(monkeypatch):
    monkeypatch.setattr(sharing, 'ItemStack', Item)
    original = bundle()
    record = json.loads(json.dumps(sharing.serialize_item(original, 1)))
    restored = sharing.deserialize_item(record)
    assert sharing.nbt_to_dict(restored.nbt) == record['nbt']
    assert record['slot'] == 1


def test_unknown_tag_is_vaulted_with_original_payload(monkeypatch):
    monkeypatch.setattr(sharing, 'ItemStack', Item)
    original = {'slot': 0, 'type': 'minecraft:blue_bundle', 'amount': 1,
                'nbt': {'_type': 'unknown', 'value': 'unreadable original'}}
    items, unresolved = sharing._prepare_restore([original], range(1))
    assert items == {0: None}
    assert unresolved == [original]


def test_nbt_write_readback_mismatch_preserves_unresolved_record(monkeypatch):
    class Broken(Item):
        @property
        def nbt(self):
            return CompoundTag()
        @nbt.setter
        def nbt(self, value):
            pass
    monkeypatch.setattr(sharing, 'ItemStack', Broken)
    original = sharing.serialize_item(bundle(), 0)
    items, unresolved = sharing._prepare_restore([original], range(1))
    assert items == {0: None}
    assert unresolved == [original]


def test_nbt_read_failure_aborts_snapshot_instead_of_saving_plain_bundle():
    class Broken:
        type, amount, data = 'minecraft:blue_bundle', 1, 0
        @property
        def nbt(self):
            raise OSError('native read failed')
    with pytest.raises(ValueError):
        sharing.serialize_item(Broken(), 0)
