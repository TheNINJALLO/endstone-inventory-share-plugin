import os
import json
import pymysql

from endstone import ColorFormat
from endstone.event import event_handler, PlayerLoginEvent, PlayerJoinEvent, PlayerQuitEvent
from endstone.inventory import ItemStack
from endstone.plugin import Plugin

# NBT classes may live under endstone.nbt or directly under endstone
try:
    from endstone.nbt import (
        CompoundTag, ListTag, ByteTag, ShortTag, IntTag, LongTag,
        FloatTag, DoubleTag, StringTag, ByteArrayTag, IntArrayTag,
    )
except (ImportError, AttributeError):
    from endstone import (
        CompoundTag, ListTag, ByteTag, ShortTag, IntTag, LongTag,
        FloatTag, DoubleTag, StringTag, ByteArrayTag, IntArrayTag,
    )


# ---------------------------------------------------------------------------
# NBT <-> dict serialization helpers
# ---------------------------------------------------------------------------

def nbt_to_dict(tag):
    """Recursively convert any NBT Tag to a JSON-serializable Python object."""
    if isinstance(tag, CompoundTag):
        return {
            "_type": "compound",
            "value": {str(k): nbt_to_dict(v) for k, v in tag.items()}
        }
    elif isinstance(tag, ListTag):
        return {
            "_type": "list",
            "value": [nbt_to_dict(tag[i]) for i in range(tag.size())]
        }
    elif isinstance(tag, ByteTag):
        return {"_type": "byte", "value": tag.value}
    elif isinstance(tag, ShortTag):
        return {"_type": "short", "value": tag.value}
    elif isinstance(tag, IntTag):
        return {"_type": "int", "value": tag.value}
    elif isinstance(tag, LongTag):
        return {"_type": "long", "value": tag.value}
    elif isinstance(tag, FloatTag):
        return {"_type": "float", "value": tag.value}
    elif isinstance(tag, DoubleTag):
        return {"_type": "double", "value": tag.value}
    elif isinstance(tag, StringTag):
        return {"_type": "string", "value": tag.value}
    elif isinstance(tag, ByteArrayTag):
        return {"_type": "byte_array", "value": list(tag)}
    elif isinstance(tag, IntArrayTag):
        return {"_type": "int_array", "value": list(tag)}
    else:
        # Fallback - try to get a value attribute
        return {"_type": "unknown", "value": str(tag)}


def dict_to_nbt(data):
    """Recursively rebuild an NBT Tag from a dict produced by nbt_to_dict."""
    t = data.get("_type", "unknown")
    v = data.get("value")

    if t == "compound":
        tag = CompoundTag()
        for key, child in v.items():
            tag[key] = dict_to_nbt(child)
        return tag
    elif t == "list":
        tag = ListTag()
        for child in v:
            tag.append(dict_to_nbt(child))
        return tag
    elif t == "byte":
        return ByteTag(int(v))
    elif t == "short":
        return ShortTag(int(v))
    elif t == "int":
        return IntTag(int(v))
    elif t == "long":
        return LongTag(int(v))
    elif t == "float":
        return FloatTag(float(v))
    elif t == "double":
        return DoubleTag(float(v))
    elif t == "string":
        return StringTag(str(v))
    elif t == "byte_array":
        return ByteArrayTag(v)
    elif t == "int_array":
        return IntArrayTag(v)
    else:
        return StringTag(str(v))


def sanitize_for_json(obj):
    """Recursively ensure all dict keys are strings.
    Handles Enchantment objects and any other non-string keys
    that may appear in NBT-derived dicts."""
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


# Items that store sub-items (bundles, etc.) — used for diagnostic logging.
BUNDLE_LIKE_ITEMS = frozenset({"minecraft:bundle"})


# ---------------------------------------------------------------------------
# Item serialization / deserialization
# ---------------------------------------------------------------------------

def serialize_item(item, slot_num, logger=None):
    """Serialize an ItemStack (or None/air) to a JSON-friendly dict.
    Returns an empty-slot dict on any error so a single bad item
    never crashes the entire save."""
    try:
        if item is None or str(item.type) == "minecraft:air":
            return {"slot": slot_num, "type": None}

        item_type = str(item.type)
        result = {
            "slot": slot_num,
            "type": item_type,
            "amount": item.amount,
            "data": item.data,
        }

        # Save the full NBT compound tag - this preserves everything:
        # enchantments, lore, display name, shulker contents, bundle items, damage, etc.
        try:
            nbt_tag = item.nbt
            if nbt_tag is not None:
                nbt_dict = sanitize_for_json(nbt_to_dict(nbt_tag))
                result["nbt"] = nbt_dict

                # Debug: log bundle-like items so we can verify contents are captured
                if logger and item_type in BUNDLE_LIKE_ITEMS:
                    top_keys = list(nbt_dict.get("value", {}).keys())
                    logger.info(
                        f"[Bundle Save] Slot {slot_num}: {item_type}, "
                        f"data={item.data}, NBT top-level keys: {top_keys}"
                    )
                    # Dump full NBT (truncated to 3000 chars) so we can see the actual structure
                    try:
                        full_dump = json.dumps(nbt_dict, default=str)
                        logger.info(f"[Bundle Save] Full NBT: {full_dump[:3000]}")
                    except Exception:
                        logger.info(f"[Bundle Save] Could not dump NBT: {nbt_dict}")
        except Exception as nbt_err:
            if logger:
                logger.warning(f"[Inventory Save] Could not serialize NBT for slot {slot_num}: {nbt_err}")

        return result
    except Exception as e:
        if logger:
            logger.warning(f"[Inventory Save] Failed to serialize slot {slot_num}: {e}")
        return {"slot": slot_num, "type": None}


def deserialize_item(item_data, logger=None, context=""):
    """Recreate an ItemStack from a dict produced by serialize_item.
    Returns None on any error so a single bad/custom item never
    crashes the entire load."""
    if item_data.get("type") is None:
        return None

    item_type = item_data["type"]
    amount = item_data.get("amount", 1)
    data = item_data.get("data", 0)
    nbt_data = item_data.get("nbt")

    # ---- Normal item construction ----
    try:
        item = ItemStack(item_type, amount, data)
    except Exception as e:
        if logger:
            logger.warning(
                f"[Inventory Load] Could not create item '{item_type}'{context}: {e}  "
                f"(This item may be a custom/modded item that doesn't exist on this server.)"
            )
        return None

    # Restore the full NBT compound tag (preserves enchantments, bundle contents, etc.)
    if nbt_data is not None:
        try:
            tag = dict_to_nbt(nbt_data)
            if isinstance(tag, CompoundTag):
                item.nbt = tag
        except Exception as nbt_err:
            if logger:
                logger.warning(
                    f"[Inventory Load] Could not restore NBT for '{item_type}'{context}: {nbt_err}"
                )

    return item


# ---------------------------------------------------------------------------
# Inventory save / load helpers
# ---------------------------------------------------------------------------

ARMOR_SLOTS = {
    -1: "helmet",
    -2: "chestplate",
    -3: "leggings",
    -4: "boots",
    -5: "item_in_off_hand",
}


def save_inventory_to_json(inv, size, logger=None, vaulted_items=None):
    """Serialize an entire PlayerInventory (including armor + offhand) to a JSON string.
    If vaulted_items is provided, merge them back into empty slots so they survive
    the round-trip through servers that don't have those custom items."""
    items = []

    # Main inventory slots
    for i in range(size):
        items.append(serialize_item(inv.get_item(i), i, logger=logger))

    # Armor + offhand
    for slot_num, attr_name in ARMOR_SLOTS.items():
        items.append(serialize_item(getattr(inv, attr_name), slot_num, logger=logger))

    # Merge vaulted items back into slots that are currently empty
    still_vaulted = []
    if vaulted_items:
        occupied = {d["slot"] for d in items if d.get("type") is not None}
        for vaulted in vaulted_items:
            slot = vaulted["slot"]
            if slot not in occupied:
                # Slot is empty - merge the vaulted item into the save
                items.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Merged vaulted item '{vaulted.get('type')}' back into slot {slot}"
                    )
            else:
                # Slot is occupied by a new item - keep the vaulted item for next time
                still_vaulted.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Slot {slot} occupied, keeping '{vaulted.get('type')}' in vault"
                    )

    return json.dumps(sanitize_for_json(items), ensure_ascii=False), still_vaulted


def load_inventory_from_json(json_str, inv, logger=None, server=None, player_name=None):
    """Restore items from a JSON string into a PlayerInventory.
    Returns a list of item dicts that could not be deserialized (unresolved)."""
    items = json.loads(json_str)
    unresolved = []

    # Clear everything first
    inv.clear()
    for attr_name in ARMOR_SLOTS.values():
        setattr(inv, attr_name, ItemStack("minecraft:air", 1))

    for item_data in items:
        slot = item_data.get("slot", 0)
        try:
            result = deserialize_item(item_data, logger=logger, context=f" (slot {slot})")

            if result is None:
                # If the item had a type but failed to deserialize, vault it
                if item_data.get("type") is not None:
                    unresolved.append(item_data)
                continue

            if slot >= 0:
                inv.set_item(slot, result)
            elif slot in ARMOR_SLOTS:
                setattr(inv, ARMOR_SLOTS[slot], result)
        except Exception as e:
            if logger:
                logger.warning(f"[Inventory Load] Failed to restore slot {slot}: {e}")
            # If this slot had data, vault it so we don't lose it
            if item_data.get("type") is not None:
                unresolved.append(item_data)

    return unresolved


def save_container_to_json(container, size, logger=None, vaulted_items=None):
    """Serialize a generic container (e.g. ender chest) to a JSON string.
    If vaulted_items is provided, merge them back into empty slots."""
    items = []
    for i in range(size):
        items.append(serialize_item(container.get_item(i), i, logger=logger))

    # Merge vaulted items back into slots that are currently empty
    still_vaulted = []
    if vaulted_items:
        occupied = {d["slot"] for d in items if d.get("type") is not None}
        for vaulted in vaulted_items:
            slot = vaulted["slot"]
            if slot not in occupied:
                items.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Merged vaulted ender chest item '{vaulted.get('type')}' back into slot {slot}"
                    )
            else:
                still_vaulted.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Ender chest slot {slot} occupied, keeping '{vaulted.get('type')}' in vault"
                    )

    return json.dumps(sanitize_for_json(items), ensure_ascii=False), still_vaulted


def load_container_from_json(json_str, container, logger=None, server=None, player_name=None):
    """Restore items from a JSON string into a generic container.
    Returns a list of item dicts that could not be deserialized (unresolved)."""
    items = json.loads(json_str)
    unresolved = []
    container.clear()

    for item_data in items:
        slot = item_data.get("slot", 0)
        try:
            result = deserialize_item(item_data, logger=logger, context=f" (container slot {slot})")

            if result is not None and slot >= 0:
                container.set_item(slot, result)
            elif result is None and item_data.get("type") is not None:
                unresolved.append(item_data)
        except Exception as e:
            if logger:
                logger.warning(f"[Inventory Load] Failed to restore container slot {slot}: {e}")
            if item_data.get("type") is not None:
                unresolved.append(item_data)

    return unresolved


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def connect_db(host, port, user, password, db_name):
    """Open a MySQL connection and select the database."""
    conn = pymysql.connect(host=host, port=int(port), user=user, password=password, charset="utf8mb4")
    cursor = conn.cursor()
    cursor.execute(f"USE {db_name}")
    return conn, cursor


# ===========================================================================
# Plugin
# ===========================================================================

class InventorySharePlugin(Plugin):
    api_version = "0.11"

    def __init__(self):
        super().__init__()
        self.sql_host = ""
        self.sql_port = 0
        self.sql_user = ""
        self.sql_pass = ""
        self.sql_db_name = ""
        # Per-player vault of items that couldn't be deserialized on this server
        # Maps xuid -> {"inventory": [item_dicts], "enderchest": [item_dicts]}
        self._unresolved = {}

    # -----------------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------------

    def load_config(self):
        self.sql_host = self.config["sql_host"]
        self.sql_port = self.config["sql_port"]
        self.sql_user = self.config["sql_user"]
        self.sql_pass = self.config["sql_pass"]
        self.sql_db_name = self.config["sql_db_name"]

    # -----------------------------------------------------------------------
    # Login status tracking (prevents double-connection)
    # -----------------------------------------------------------------------

    def set_login_status(self, xuid, status: bool):
        """Update the player's login-status flag in the database."""
        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )

        cursor.execute(
            "SELECT is_logged_in FROM player_data WHERE player_xuid = %s", xuid
        )
        result = cursor.fetchone()

        if result:
            cursor.execute(
                "UPDATE player_data SET is_logged_in = %s WHERE player_xuid = %s",
                (str(status), xuid),
            )
        else:
            cursor.execute(
                "INSERT INTO player_data (player_xuid, is_logged_in) VALUES (%s, 'True')",
                xuid,
            )

        conn.commit()
        conn.close()

    def get_login_status(self, xuid) -> bool:
        """Check whether a player is flagged as logged-in on another server."""
        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )
        cursor.execute(
            "SELECT is_logged_in FROM player_data WHERE player_xuid = %s", xuid
        )
        result = cursor.fetchone()
        conn.close()
        return result[0] == 1 if result else False

    # -----------------------------------------------------------------------
    # Save / Load vault (unresolved items)
    # -----------------------------------------------------------------------

    def _load_vault(self, xuid):
        """Load the unresolved items vault from the database for a player."""
        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )
        try:
            cursor.execute(
                "SELECT unresolved_items FROM player_data WHERE player_xuid = %s",
                (xuid,),
            )
            result = cursor.fetchone()
            if result and result[0]:
                return json.loads(result[0])
        except Exception as e:
            self.logger.warning(f"[Vault] Could not load vault for {xuid}: {e}")
        finally:
            cursor.close()
            conn.close()
        return {"inventory": [], "enderchest": []}

    def _save_vault(self, xuid, vault_data, cursor):
        """Write the unresolved items vault to the database (uses existing cursor)."""
        has_items = bool(vault_data.get("inventory") or vault_data.get("enderchest"))
        vault_json = json.dumps(vault_data, ensure_ascii=False) if has_items else None
        cursor.execute(
            "UPDATE player_data SET unresolved_items = %s WHERE player_xuid = %s",
            (vault_json, xuid),
        )

    # -----------------------------------------------------------------------
    # Shared save helper (used by on_player_quit and on_disable)
    # -----------------------------------------------------------------------

    def _save_player(self, player):
        """Save a player's inventory, ender chest, and vault to the database."""
        xuid = player.xuid

        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )

        try:
            # Get the current vault for this player
            vault = self._unresolved.get(xuid, {"inventory": [], "enderchest": []})

            # Save main inventory (slots + armor + offhand)
            inv = player.inventory
            inv_json, inv_still_vaulted = save_inventory_to_json(
                inv, inv.size, logger=self.logger,
                vaulted_items=vault.get("inventory", [])
            )
            cursor.execute(
                "UPDATE player_data SET player_inv = %s WHERE player_xuid = %s",
                (inv_json, xuid),
            )

            # Save ender chest
            ec = player.ender_chest
            ec_json, ec_still_vaulted = save_container_to_json(
                ec, ec.size, logger=self.logger,
                vaulted_items=vault.get("enderchest", [])
            )
            cursor.execute(
                "UPDATE player_data SET player_enderchest = %s WHERE player_xuid = %s",
                (ec_json, xuid),
            )

            # Save XP level and progress
            try:
                xp_level = player.exp_level
                xp_progress = player.exp_progress
                cursor.execute(
                    "UPDATE player_data SET player_xp_level = %s, player_xp_progress = %s WHERE player_xuid = %s",
                    (xp_level, xp_progress, xuid),
                )
            except Exception as xp_err:
                self.logger.warning(f"[XP Save] Could not save XP for {player.name}: {xp_err}")

            # Save any items that are STILL unresolved (slot was occupied)
            updated_vault = {
                "inventory": inv_still_vaulted,
                "enderchest": ec_still_vaulted,
            }
            self._save_vault(xuid, updated_vault, cursor)

            conn.commit()

            vaulted_count = len(inv_still_vaulted) + len(ec_still_vaulted)
            if vaulted_count > 0:
                self.logger.info(
                    f"Saved inventory for {player.name} ({vaulted_count} item(s) still in vault)"
                )
            else:
                self.logger.info(f"Saved inventory for {player.name}")

        except Exception as e:
            self.logger.error(f"Failed to save inventory for {player.name}: {e}")
        finally:
            # Clean up in-memory vault
            self._unresolved.pop(xuid, None)
            cursor.close()
            conn.close()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def on_load(self):
        self.logger.info(
            f"{ColorFormat.AQUA}InventorySharePlugin loaded!{ColorFormat.RESET}"
        )

    def on_enable(self):
        self.logger.info(
            f"{ColorFormat.AQUA}InventorySharePlugin enabled!{ColorFormat.RESET}"
        )
        self.save_default_config()
        self.load_config()

        # Auto-migrate: ensure the unresolved_items column exists
        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )
            cursor.execute(
                "ALTER TABLE player_data ADD COLUMN unresolved_items MEDIUMTEXT DEFAULT NULL"
            )
            conn.commit()
            self.logger.info("[Migration] Added 'unresolved_items' column to player_data table.")
        except Exception:
            pass  # Column already exists

        # Auto-migrate: ensure XP columns exist
        for col_def in [
            "player_xp_level INT DEFAULT 0",
            "player_xp_progress FLOAT DEFAULT 0.0",
        ]:
            try:
                conn, cursor = connect_db(
                    self.sql_host, self.sql_port, self.sql_user,
                    self.sql_pass, self.sql_db_name
                )
                col_name = col_def.split()[0]
                cursor.execute(f"ALTER TABLE player_data ADD COLUMN {col_def}")
                conn.commit()
                self.logger.info(f"[Migration] Added '{col_name}' column to player_data table.")
                cursor.close()
                conn.close()
            except Exception:
                pass  # Column already exists

        # Auto-migrate: ensure table supports full Unicode (emojis, special chars)
        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )
            cursor.execute(
                "ALTER TABLE player_data CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            self.logger.info("[Migration] Converted player_data table to utf8mb4.")
            cursor.close()
            conn.close()
        except Exception:
            pass  # Already utf8mb4 or non-critical error

        # Mark all currently online players as logged-in
        for player in self.server.online_players:
            self.set_login_status(player.xuid, True)

        if not os.path.exists("plugins/inventory_share_plugin/config.toml"):
            self.logger.error("config.toml not found")

        self.register_events(self)

    def on_disable(self):
        # Save ALL online players' inventories before stopping
        self.logger.info("Saving all online player inventories before shutdown...")
        for player in self.server.online_players:
            try:
                self._save_player(player)
            except Exception as e:
                self.logger.error(f"Failed to save {player.name} during shutdown: {e}")
            self.set_login_status(player.xuid, False)

        self.logger.info(
            f"{ColorFormat.AQUA}InventorySharePlugin disabled!{ColorFormat.RESET}"
        )

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    @event_handler
    def on_player_login(self, event: PlayerLoginEvent):
        """Prevent double-login across servers."""
        self.logger.info("Login event")
        target = event.player
        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )

        if self.get_login_status(target.xuid):
            target.kick(
                "You cannot connect because you are already logged in on another server."
            )
            cursor.close()
            conn.close()
            return

        self.set_login_status(target.xuid, True)
        conn.commit()
        cursor.close()
        conn.close()

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        """Restore the player's inventory and ender chest from the database."""
        self.logger.info("Join event")
        target = event.player
        self.set_login_status(target.xuid, False)

        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )

        # Upsert login status
        cursor.execute(
            "SELECT is_logged_in FROM player_data WHERE player_xuid = %s",
            (target.xuid,),
        )
        result = cursor.fetchone()

        if result:
            cursor.execute(
                "UPDATE player_data SET is_logged_in = 'True' WHERE player_xuid = %s",
                (target.xuid,),
            )
        else:
            cursor.execute(
                "INSERT INTO player_data (player_xuid, is_logged_in) VALUES (%s, 'True')",
                (target.xuid,),
            )

        # Load the existing vault from the DB
        db_vault = self._load_vault(target.xuid)
        inv_unresolved = list(db_vault.get("inventory", []))
        ec_unresolved = list(db_vault.get("enderchest", []))

        # --- Restore main inventory ---
        cursor.execute(
            "SELECT player_inv FROM player_data WHERE player_xuid = %s",
            (target.xuid,),
        )
        result = cursor.fetchone()

        if result and result[0]:
            try:
                player = self.server.get_player(target.name)
                new_unresolved = load_inventory_from_json(
                    result[0], player.inventory, logger=self.logger,
                    server=self.server, player_name=target.name
                )
                inv_unresolved.extend(new_unresolved)
            except Exception as e:
                self.logger.error(f"Failed to restore inventory: {e}")

        # --- Restore ender chest ---
        cursor.execute(
            "SELECT player_enderchest FROM player_data WHERE player_xuid = %s",
            (target.xuid,),
        )
        result = cursor.fetchone()

        if result and result[0]:
            try:
                player = self.server.get_player(target.name)
                new_unresolved = load_container_from_json(
                    result[0], player.ender_chest, logger=self.logger,
                    server=self.server, player_name=target.name
                )
                ec_unresolved.extend(new_unresolved)
            except Exception as e:
                self.logger.error(f"Failed to restore ender chest: {e}")

        # --- Restore XP level and progress ---
        try:
            cursor.execute(
                "SELECT player_xp_level, player_xp_progress FROM player_data WHERE player_xuid = %s",
                (target.xuid,),
            )
            xp_result = cursor.fetchone()
            if xp_result:
                player = self.server.get_player(target.name)
                xp_level = xp_result[0] if xp_result[0] is not None else 0
                xp_progress = xp_result[1] if xp_result[1] is not None else 0.0
                player.exp_level = int(xp_level)
                player.exp_progress = float(xp_progress)
                self.logger.info(
                    f"Restored XP for {target.name}: level={xp_level}, progress={xp_progress:.2f}"
                )
        except Exception as e:
            self.logger.error(f"Failed to restore XP: {e}")

        # Store the combined vault in memory for this player
        if inv_unresolved or ec_unresolved:
            self._unresolved[target.xuid] = {
                "inventory": inv_unresolved,
                "enderchest": ec_unresolved,
            }
            total = len(inv_unresolved) + len(ec_unresolved)
            self.logger.info(
                f"[Vault] {target.name} has {total} unresolved item(s) in vault "
                f"(inv: {len(inv_unresolved)}, ec: {len(ec_unresolved)})"
            )

        cursor.close()
        conn.close()

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        """Save the player's inventory and ender chest to the database."""
        target = event.player

        if self.get_login_status(target.xuid):
            self.logger.info(
                f"{target.name} was kicked (connected to another server)."
            )
            self.set_login_status(target.xuid, False)
            return

        conn, cursor = connect_db(
            self.sql_host, self.sql_port, self.sql_user,
            self.sql_pass, self.sql_db_name
        )
        cursor.execute(
            "UPDATE player_data SET is_logged_in = 'False' WHERE player_xuid = %s",
            (target.xuid,),
        )
        conn.commit()
        cursor.close()
        conn.close()

        try:
            player = self.server.get_player(target.name)
            self._save_player(player)
        except Exception as e:
            self.logger.error(f"Failed to save inventory: {e}")