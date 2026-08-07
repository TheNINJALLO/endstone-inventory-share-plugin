import os
import json
import pymysql
import threading
from concurrent.futures import ThreadPoolExecutor

from endstone import ColorFormat
from endstone.level import Location
from endstone.event import event_handler, PlayerLoginEvent, PlayerJoinEvent, PlayerQuitEvent, ScriptMessageEvent
from endstone.inventory import ItemStack
from endstone.plugin import Plugin
from endstone.scoreboard import Criteria

# Endstone 0.11 exports NBT tag classes from endstone.nbt.
from endstone.nbt import (
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
            "value": [nbt_to_dict(tag[i]) for i in range(len(tag))]
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
        return {"_type": "unknown", "value": str(tag)}


def dict_to_nbt(data):
    """Recursively rebuild an NBT Tag from a dict produced by nbt_to_dict."""
    if not isinstance(data, dict):
        return StringTag(str(data))

    t = data.get("_type", "unknown")
    v = data.get("value")

    if t == "compound":
        tag = CompoundTag()
        if isinstance(v, dict):
            for key, child in v.items():
                tag[str(key)] = dict_to_nbt(child)
        return tag
    elif t == "list":
        list_tag = ListTag()
        if isinstance(v, list):
            for child in v:
                list_tag.append(dict_to_nbt(child))
        return list_tag
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
        return StringTag(str(v if v is not None else ""))
    elif t == "byte_array":
        return ByteArrayTag(v if isinstance(v, list) else [])
    elif t == "int_array":
        return IntArrayTag(v if isinstance(v, list) else [])
    else:
        return StringTag(str(v if v is not None else data))


def sanitize_for_json(obj):
    """Recursively ensure all dict keys are strings."""
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Item serialization / deserialization
# ---------------------------------------------------------------------------

def serialize_item(item, slot_num, logger=None):
    """Serialize an ItemStack (or None/air) to a JSON-friendly dict."""
    try:
        if item is None or str(item.type) == "minecraft:air":
            return {"slot": slot_num, "type": None}

        item_type = str(item.type)

        result = {
            "slot": slot_num,
            "type": item_type,
            "amount": item.amount,
            "data": getattr(item, "data", 0),
        }

        try:
            nbt_tag = item.nbt
            if nbt_tag is not None:
                nbt_dict = sanitize_for_json(nbt_to_dict(nbt_tag))
                result["nbt"] = nbt_dict
        except Exception as nbt_err:
            if logger:
                logger.warning(f"[Inventory Save] Could not serialize NBT for slot {slot_num}: {nbt_err}")

        return result
    except Exception as e:
        if logger:
            logger.warning(f"[Inventory Save] Failed to serialize slot {slot_num}: {e}")
        return {"slot": slot_num, "type": None}


def deserialize_item(item_data, logger=None, context=""):
    """Recreate an ItemStack from a dict produced by serialize_item."""
    if not isinstance(item_data, dict) or item_data.get("type") is None:
        return None

    item_type = item_data["type"]
    amount = item_data.get("amount", 1)
    data = item_data.get("data", 0)
    nbt_data = item_data.get("nbt")

    try:
        item = ItemStack(item_type, amount, data)
    except Exception as e:
        if logger:
            logger.warning(
                f"[Inventory Load] Could not create item '{item_type}'{context}: {e}"
            )
        return None

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
    """Serialize an entire PlayerInventory to a JSON string."""
    items = []

    # Main inventory slots
    for i in range(size):
        items.append(serialize_item(inv.get_item(i), i, logger=logger))

    # Armor + offhand
    for slot_num, attr_name in ARMOR_SLOTS.items():
        items.append(serialize_item(getattr(inv, attr_name, None), slot_num, logger=logger))

    still_vaulted = []
    if vaulted_items:
        occupied = {d["slot"] for d in items if d.get("type") is not None}
        for vaulted in vaulted_items:
            slot = vaulted["slot"]
            if slot not in occupied:
                items.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Merged vaulted item '{vaulted.get('type')}' back into slot {slot}"
                    )
            else:
                still_vaulted.append(vaulted)
                if logger:
                    logger.info(
                        f"[Vault] Slot {slot} occupied, keeping '{vaulted.get('type')}' in vault"
                    )

    return json.dumps(sanitize_for_json(items), ensure_ascii=False), still_vaulted


def load_inventory_from_json(json_str, inv, logger=None, server=None, player_name=None):
    """Restore items from a JSON string into a PlayerInventory."""
    items = json.loads(json_str)
    unresolved = []

    # Clear all main inventory slots
    for i in range(inv.size):
        inv.clear(i)

    # Clear armor and offhand slots
    for attr_name in ARMOR_SLOTS.values():
        setattr(inv, attr_name, ItemStack("minecraft:air", 1))

    for item_data in items:
        slot = item_data.get("slot", 0)
        try:
            result = deserialize_item(item_data, logger=logger, context=f" (slot {slot})")

            if result is None:
                if item_data.get("type") is not None:
                    unresolved.append(item_data)
                continue

            if slot >= 0 and slot < inv.size:
                inv.set_item(slot, result)
            elif slot in ARMOR_SLOTS:
                attr_name = ARMOR_SLOTS[slot]
                setattr(inv, attr_name, result)
        except Exception as e:
            if logger:
                logger.warning(f"[Inventory Load] Failed to restore slot {slot}: {e}")
            if item_data.get("type") is not None:
                unresolved.append(item_data)

    return unresolved


def save_container_to_json(container, size, logger=None, vaulted_items=None):
    """Serialize a generic container (e.g. ender chest) to a JSON string."""
    items = []
    for i in range(size):
        items.append(serialize_item(container.get_item(i), i, logger=logger))

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
    """Restore items from a JSON string into a generic container."""
    items = json.loads(json_str)
    unresolved = []
    container.clear()

    for item_data in items:
        slot = item_data.get("slot", 0)
        try:
            result = deserialize_item(item_data, logger=logger, context=f" (container slot {slot})")

            if result is not None and slot >= 0 and slot < container.size:
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
    cursor.execute(f"USE `{db_name}`")
    return conn, cursor


_REQUIRED_COLUMNS = [
    ("player_xuid",         None),
    ("player_inv",          "player_inv MEDIUMTEXT DEFAULT NULL"),
    ("player_enderchest",   "player_enderchest MEDIUMTEXT DEFAULT NULL"),
    ("is_logged_in",        "is_logged_in TINYINT DEFAULT 0"),
    ("unresolved_items",    "unresolved_items MEDIUMTEXT DEFAULT NULL"),
    ("player_xp_level",     "player_xp_level INT DEFAULT 0"),
    ("player_xp_progress",  "player_xp_progress FLOAT DEFAULT 0.0"),
    ("player_money_score",  "player_money_score INT DEFAULT 0"),
    ("player_tags",         "player_tags MEDIUMTEXT DEFAULT NULL"),
    ("player_locations",    "player_locations MEDIUMTEXT DEFAULT NULL"),
    ("player_bundles",      "player_bundles MEDIUMTEXT DEFAULT NULL"),
]


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
        self.server_name = "lobby"
        self._unresolved = {}
        self.executor = None
        self._bundle_cache = {}
        self._bundle_chunks = {}
        self._loading_players = set()
        self._kicked_players = set()

    # -----------------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------------

    def load_config(self):
        self.sql_host = self.config["sql_host"]
        self.sql_port = self.config["sql_port"]
        self.sql_user = self.config["sql_user"]
        self.sql_pass = self.config["sql_pass"]
        self.sql_db_name = self.config["sql_db_name"]
        self.server_name = self._get_server_name()

    def _get_server_name(self):
        """Extract the server-name from server.properties."""
        try:
            prop_path = os.path.join(os.getcwd(), "server.properties")
            if os.path.exists(prop_path):
                with open(prop_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("server-name="):
                            return line.split("=", 1)[1].strip()
        except Exception as e:
            self.logger.warning(f"Could not read server.properties: {e}")
        return "lobby"

    # -----------------------------------------------------------------------
    # Login status tracking
    # -----------------------------------------------------------------------

    def set_login_status(self, xuid, status: bool):
        """Update the player's login-status flag in the database."""
        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )

            cursor.execute(
                "SELECT is_logged_in FROM player_data WHERE player_xuid = %s", (xuid,)
            )
            result = cursor.fetchone()

            if result:
                cursor.execute(
                    "UPDATE player_data SET is_logged_in = %s WHERE player_xuid = %s",
                    (1 if status else 0, xuid),
                )
            else:
                cursor.execute(
                    "INSERT INTO player_data (player_xuid, is_logged_in) VALUES (%s, %s)",
                    (xuid, 1 if status else 0),
                )

            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            self.logger.error(f"Failed to update login status for {xuid}: {e}")

    def get_login_status(self, xuid) -> bool:
        """Check whether a player is flagged as logged-in on another server."""
        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )
            cursor.execute(
                "SELECT is_logged_in FROM player_data WHERE player_xuid = %s", (xuid,)
            )
            result = cursor.fetchone()
            conn.close()
            return result[0] == 1 if result else False
        except Exception as e:
            self.logger.error(f"Failed to get login status for {xuid}: {e}")
            return False

    # -----------------------------------------------------------------------
    # Scoreboard helpers
    # -----------------------------------------------------------------------

    def _get_or_create_money_objective(self):
        """Return the 'Money' scoreboard objective, creating it if missing."""
        scoreboard = self.server.scoreboard
        money_obj = scoreboard.get_objective("Money")
        if money_obj is None:
            try:
                money_obj = scoreboard.add_objective("Money", Criteria.DUMMY)
                self.logger.info(
                    "[Money] 'Money' scoreboard objective was missing — created it automatically."
                )
            except Exception as create_err:
                self.logger.warning(
                    f"[Money] Could not create 'Money' scoreboard objective: {create_err}"
                )
        return money_obj

    # -----------------------------------------------------------------------
    # Save / Load vault (unresolved items)
    # -----------------------------------------------------------------------

    def _load_vault(self, xuid):
        """Load the unresolved items vault from the database for a player."""
        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )
            cursor.execute(
                "SELECT unresolved_items FROM player_data WHERE player_xuid = %s",
                (xuid,),
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            if result and result[0]:
                return json.loads(result[0])
        except Exception as e:
            self.logger.warning(f"[Vault] Could not load vault for {xuid}: {e}")
        return {"inventory": [], "enderchest": []}

    def _save_vault(self, xuid, vault_data, cursor):
        """Write the unresolved items vault to the database."""
        has_items = bool(vault_data.get("inventory") or vault_data.get("enderchest"))
        vault_json = json.dumps(vault_data, ensure_ascii=False) if has_items else None
        cursor.execute(
            "UPDATE player_data SET unresolved_items = %s WHERE player_xuid = %s",
            (vault_json, xuid),
        )

    # -----------------------------------------------------------------------
    # Shared save helper
    # -----------------------------------------------------------------------

    def _extract_player_data(self, player):
        """Synchronously extract all data needed for saving."""
        xuid = player.xuid
        name = player.name
        
        vault = self._unresolved.get(xuid, {"inventory": [], "enderchest": []})

        inv = player.inventory
        inv_json, inv_still_vaulted = save_inventory_to_json(
            inv, inv.size, logger=self.logger,
            vaulted_items=vault.get("inventory", [])
        )
        
        ec = player.ender_chest
        ec_json, ec_still_vaulted = save_container_to_json(
            ec, ec.size, logger=self.logger,
            vaulted_items=vault.get("enderchest", [])
        )

        xp_level = player.exp_level
        xp_progress = player.exp_progress

        money_score = 0
        try:
            money_obj = self._get_or_create_money_objective()
            if money_obj is not None:
                money_score = money_obj.get_score(player).value
        except Exception as e:
            self.logger.warning(f"[Money Save] Could not extract Money score for {name}: {e}")

        tags = [str(t) for t in player.scoreboard_tags]
        
        loc = player.location
        current_location = {
            "x": loc.x,
            "y": loc.y,
            "z": loc.z,
            "pitch": loc.pitch,
            "yaw": loc.yaw,
            "dimension": loc.dimension.name
        }

        updated_vault = {
            "inventory": inv_still_vaulted,
            "enderchest": ec_still_vaulted,
        }

        bundle_data = self._bundle_cache.pop(name, None)

        return {
            "xuid": xuid,
            "name": name,
            "inv_json": inv_json,
            "ec_json": ec_json,
            "xp_level": xp_level,
            "xp_progress": xp_progress,
            "money_score": money_score,
            "tags": tags,
            "updated_vault": updated_vault,
            "vaulted_count": len(inv_still_vaulted) + len(ec_still_vaulted),
            "current_location": current_location,
            "bundle_data": bundle_data,
        }

    def _save_player_data_async(self, data):
        """Background thread method to save extracted player data to the DB."""
        xuid = data["xuid"]
        name = data["name"]

        try:
            conn, cursor = connect_db(
                self.sql_host, self.sql_port, self.sql_user,
                self.sql_pass, self.sql_db_name
            )

            cursor.execute(
                "UPDATE player_data SET player_inv = %s WHERE player_xuid = %s",
                (data["inv_json"], xuid),
            )

            cursor.execute(
                "UPDATE player_data SET player_enderchest = %s WHERE player_xuid = %s",
                (data["ec_json"], xuid),
            )

            cursor.execute(
                "UPDATE player_data SET player_xp_level = %s, player_xp_progress = %s WHERE player_xuid = %s",
                (data["xp_level"], data["xp_progress"], xuid),
            )

            cursor.execute(
                "SELECT player_money_score FROM player_data WHERE player_xuid = %s",
                (xuid,),
            )
            db_money = cursor.fetchone()
            db_money_val = db_money[0] if db_money and db_money[0] is not None else 0

            if data["money_score"] != 0 or db_money_val == 0:
                cursor.execute(
                    "UPDATE player_data SET player_money_score = %s WHERE player_xuid = %s",
                    (data["money_score"], xuid),
                )

            tags = data["tags"]
            cursor.execute(
                "SELECT player_tags FROM player_data WHERE player_xuid = %s",
                (xuid,),
            )
            db_tag_result = cursor.fetchone()
            db_has_tags = db_tag_result and db_tag_result[0] is not None and db_tag_result[0] != ''

            if tags:
                tags_json = json.dumps(tags, ensure_ascii=False)
                cursor.execute(
                    "UPDATE player_data SET player_tags = %s WHERE player_xuid = %s",
                    (tags_json, xuid),
                )
            elif not db_has_tags:
                cursor.execute(
                    "UPDATE player_data SET player_tags = %s WHERE player_xuid = %s",
                    (None, xuid),
                )

            self._save_vault(xuid, data["updated_vault"], cursor)

            cursor.execute(
                "SELECT player_locations FROM player_data WHERE player_xuid = %s",
                (xuid,),
            )
            loc_result = cursor.fetchone()
            try:
                locations = json.loads(loc_result[0]) if loc_result and loc_result[0] else {}
            except Exception:
                locations = {}
            
            locations[self.server_name] = data["current_location"]
            locations_json = json.dumps(locations, ensure_ascii=False)
            
            cursor.execute(
                "UPDATE player_data SET player_locations = %s WHERE player_xuid = %s",
                (locations_json, xuid),
            )

            bundle_data = data.get("bundle_data")
            if bundle_data is not None:
                bundle_json = json.dumps(bundle_data, ensure_ascii=False)
                cursor.execute(
                    "UPDATE player_data SET player_bundles = %s WHERE player_xuid = %s",
                    (bundle_json, xuid),
                )

            conn.commit()

            if data["vaulted_count"] > 0:
                self.logger.info(f"Saved inventory for {name} ({data['vaulted_count']} item(s) still in vault)")
            else:
                self.logger.info(f"Saved inventory for {name}")

        except Exception as e:
            self.logger.error(f"Failed to save inventory to DB for {name}: {e}")
        finally:
            if 'cursor' in locals(): cursor.close()
            if 'conn' in locals(): conn.close()

    def _save_player_sync(self, player):
        """Synchronous save used only during server shutdown."""
        data = self._extract_player_data(player)
        self._save_player_data_async(data)

    # -----------------------------------------------------------------------
    # Schema bootstrap
    # -----------------------------------------------------------------------

    def _ensure_schema(self):
        """Create database and tables safely."""
        try:
            conn = pymysql.connect(
                host=self.sql_host,
                port=int(self.sql_port),
                user=self.sql_user,
                password=self.sql_pass,
                charset="utf8mb4",
            )
        except Exception as e:
            self.logger.error(f"[Schema] Cannot connect to MySQL: {e}")
            return

        cursor = conn.cursor()

        try:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.sql_db_name}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            cursor.execute(f"USE `{self.sql_db_name}`")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `player_data` (
                    `player_xuid`        VARCHAR(64)  NOT NULL PRIMARY KEY,
                    `player_inv`         MEDIUMTEXT   DEFAULT NULL,
                    `player_enderchest`  MEDIUMTEXT   DEFAULT NULL,
                    `is_logged_in`       TINYINT      NOT NULL DEFAULT 0,
                    `unresolved_items`   MEDIUMTEXT   DEFAULT NULL,
                    `player_xp_level`    INT          NOT NULL DEFAULT 0,
                    `player_xp_progress` FLOAT        NOT NULL DEFAULT 0.0,
                    `player_money_score` INT          NOT NULL DEFAULT 0,
                    `player_tags`        MEDIUMTEXT   DEFAULT NULL,
                    `player_locations`   MEDIUMTEXT   DEFAULT NULL,
                    `player_bundles`     MEDIUMTEXT   DEFAULT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            conn.commit()
            self.logger.info("[Schema] player_data table is ready.")

            cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'player_data'",
                (self.sql_db_name,),
            )
            existing_cols = {row[0].lower() for row in cursor.fetchall()}

            for col_name, col_def in _REQUIRED_COLUMNS:
                if col_def is None:
                    continue
                if col_name.lower() not in existing_cols:
                    try:
                        cursor.execute(
                            f"ALTER TABLE `player_data` ADD COLUMN {col_def}"
                        )
                        conn.commit()
                        self.logger.info(
                            f"[Schema] Added missing column '{col_name}' to player_data."
                        )
                    except Exception as alter_err:
                        self.logger.warning(
                            f"[Schema] Could not add column '{col_name}': {alter_err}"
                        )

        except Exception as e:
            self.logger.error(f"[Schema] Schema bootstrap failed: {e}")
        finally:
            cursor.close()
            conn.close()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def on_enable(self):
        self.logger.info(
            f"{ColorFormat.AQUA}InventorySharePlugin enabled (v2.7.2, API 0.11.6)!{ColorFormat.RESET}"
        )
        self.save_default_config()
        self.load_config()

        self.executor = ThreadPoolExecutor(max_workers=5)
        self._ensure_schema()

        for player in self.server.online_players:
            self.set_login_status(player.xuid, True)

        self.register_events(self)

    def on_disable(self):
        self.logger.info("Saving all online player inventories before shutdown...")
        for player in self.server.online_players:
            try:
                self._save_player_sync(player)
            except Exception as e:
                self.logger.error(f"Failed to save {player.name} during shutdown: {e}")
            self.set_login_status(player.xuid, False)
        
        if self.executor:
            self.executor.shutdown(wait=True)

        self.logger.info(
            f"{ColorFormat.AQUA}InventorySharePlugin disabled!{ColorFormat.RESET}"
        )

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    @event_handler
    def on_player_login(self, event: PlayerLoginEvent):
        """Prevent double-login across servers safely."""
        target = event.player
        xuid = target.xuid
        name = target.name
        
        def check_login_task():
            try:
                conn, cursor = connect_db(
                    self.sql_host, self.sql_port, self.sql_user,
                    self.sql_pass, self.sql_db_name
                )
                
                cursor.execute(
                    "SELECT is_logged_in FROM player_data WHERE player_xuid = %s", (xuid,)
                )
                result = cursor.fetchone()
                is_logged_in = result[0] == 1 if result else False
                
                if is_logged_in:
                    self._kicked_players.add(xuid)
                    def kick_player():
                        p = self.server.get_player(name)
                        if p:
                            p.kick("You cannot connect because you are already logged in on another server.")
                    self.server.scheduler.run_task(self, kick_player)
                else:
                    if result:
                        cursor.execute(
                            "UPDATE player_data SET is_logged_in = 1 WHERE player_xuid = %s",
                            (xuid,),
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO player_data (player_xuid, is_logged_in) VALUES (%s, 1)",
                            (xuid,),
                        )
                    conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                self.logger.error(f"Failed to check login status for {name}: {e}")

        if self.executor:
            self.executor.submit(check_login_task)

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        """Restore the player's inventory and ender chest safely from the database."""
        target = event.player
        name = target.name
        xuid = target.xuid

        self._loading_players.add(xuid)

        def load_inventory_task():
            try:
                conn, cursor = connect_db(
                    self.sql_host, self.sql_port, self.sql_user,
                    self.sql_pass, self.sql_db_name
                )

                cursor.execute(
                    "SELECT is_logged_in FROM player_data WHERE player_xuid = %s",
                    (xuid,),
                )
                result = cursor.fetchone()
                if result:
                    cursor.execute(
                        "UPDATE player_data SET is_logged_in = 1 WHERE player_xuid = %s",
                        (xuid,),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO player_data (player_xuid, is_logged_in) VALUES (%s, 1)",
                        (xuid,),
                    )

                db_vault_data = {}
                cursor.execute("SELECT unresolved_items FROM player_data WHERE player_xuid = %s", (xuid,))
                res = cursor.fetchone()
                if res and res[0]:
                    try:
                        db_vault_data = json.loads(res[0])
                    except Exception:
                        db_vault_data = {}
                
                cursor.execute("SELECT player_inv FROM player_data WHERE player_xuid = %s", (xuid,))
                inv_res = cursor.fetchone()
                inv_json = inv_res[0] if inv_res else None

                cursor.execute("SELECT player_enderchest FROM player_data WHERE player_xuid = %s", (xuid,))
                ec_res = cursor.fetchone()
                ec_json = ec_res[0] if ec_res else None

                cursor.execute("SELECT player_xp_level, player_xp_progress FROM player_data WHERE player_xuid = %s", (xuid,))
                xp_res = cursor.fetchone()
                
                cursor.execute("SELECT player_money_score FROM player_data WHERE player_xuid = %s", (xuid,))
                money_res = cursor.fetchone()

                cursor.execute("SELECT player_tags FROM player_data WHERE player_xuid = %s", (xuid,))
                tags_res = cursor.fetchone()

                cursor.execute("SELECT player_locations FROM player_data WHERE player_xuid = %s", (xuid,))
                loc_res = cursor.fetchone()
                locations_json = loc_res[0] if loc_res else None

                cursor.execute("SELECT player_bundles FROM player_data WHERE player_xuid = %s", (xuid,))
                bundles_res = cursor.fetchone()
                bundles_json = bundles_res[0] if bundles_res else None

                conn.commit()
                cursor.close()
                conn.close()

                def apply_inventory_sync():
                    try:
                        if xuid in self._kicked_players:
                            self.logger.info(f"[Join Sync] Skipping inventory sync for {name} (player kicked).")
                            return

                        p = self.server.get_player(name)
                        if not p or not p.is_valid:
                            self.logger.info(f"[Join Sync] Player {name} is no longer online/valid; skipping restore.")
                            return

                        inv_unresolved = list(db_vault_data.get("inventory", []))
                        ec_unresolved = list(db_vault_data.get("enderchest", []))

                        if inv_json:
                            try:
                                new_unresolved = load_inventory_from_json(
                                    inv_json, p.inventory, logger=self.logger,
                                    server=self.server, player_name=p.name
                                )
                                inv_unresolved.extend(new_unresolved)
                            except Exception as e:
                                self.logger.error(f"Failed to restore inventory for {name}: {e}")
                        
                        if ec_json:
                            try:
                                new_unresolved = load_container_from_json(
                                    ec_json, p.ender_chest, logger=self.logger,
                                    server=self.server, player_name=p.name
                                )
                                ec_unresolved.extend(new_unresolved)
                            except Exception as e:
                                self.logger.error(f"Failed to restore ender chest for {name}: {e}")

                        # Restore XP safely without redundant C++ mutations
                        if xp_res:
                            try:
                                xp_level = int(xp_res[0]) if xp_res[0] is not None else 0
                                xp_progress = float(xp_res[1]) if xp_res[1] is not None else 0.0
                                if p.exp_level != xp_level:
                                    p.exp_level = xp_level
                                if abs(p.exp_progress - xp_progress) > 0.01:
                                    p.exp_progress = xp_progress
                                self.logger.info(f"Restored XP for {p.name}: level={xp_level}, progress={xp_progress:.2f}")
                            except Exception as e:
                                self.logger.error(f"Failed to restore XP for {name}: {e}")

                        # Restore Money score safely
                        if money_res:
                            try:
                                db_money = money_res[0] if money_res[0] is not None else 0
                                if db_money != 0:
                                    money_obj = self._get_or_create_money_objective()
                                    if money_obj is not None:
                                        score = money_obj.get_score(p)
                                        if score.value != int(db_money):
                                            score.value = int(db_money)
                                        self.logger.info(f"Restored Money score for {p.name}: {db_money}")
                            except Exception as e:
                                self.logger.error(f"Failed to restore Money score for {name}: {e}")

                        # Restore Tags safely without C++ memory corruption (double free prevention)
                        if tags_res and tags_res[0]:
                            try:
                                stored_tags = json.loads(tags_res[0])
                                if isinstance(stored_tags, list):
                                    target_tags = set(str(t) for t in stored_tags)
                                    current_tags = set(str(t) for t in p.scoreboard_tags)
                                    
                                    # Only remove tags that are no longer present
                                    for t in (current_tags - target_tags):
                                        p.remove_scoreboard_tag(t)
                                    # Only add tags that are new
                                    for t in (target_tags - current_tags):
                                        p.add_scoreboard_tag(t)
                                        
                                    self.logger.info(f"Restored {len(target_tags)} tag(s) for {p.name}: {list(target_tags)}")
                            except Exception as e:
                                self.logger.error(f"Failed to restore tags for {name}: {e}")

                        # Restore Location safely
                        if locations_json:
                            try:
                                locations = json.loads(locations_json)
                                if self.server_name in locations:
                                    loc_data = locations[self.server_name]
                                    dim_name = loc_data.get("dimension", "minecraft:overworld")
                                    dim = None
                                    try:
                                        dim = self.server.level.get_dimension(dim_name)
                                    except Exception:
                                        dim = None
                                    
                                    if dim is None:
                                        dim = p.location.dimension

                                    curr_loc = p.location
                                    target_x = float(loc_data.get("x", curr_loc.x))
                                    target_y = float(loc_data.get("y", curr_loc.y))
                                    target_z = float(loc_data.get("z", curr_loc.z))
                                    target_pitch = float(loc_data.get("pitch", curr_loc.pitch))
                                    target_yaw = float(loc_data.get("yaw", curr_loc.yaw))

                                    # Teleport only if position or dimension actually changed
                                    if (abs(curr_loc.x - target_x) > 0.5 or 
                                        abs(curr_loc.y - target_y) > 0.5 or 
                                        abs(curr_loc.z - target_z) > 0.5 or
                                        curr_loc.dimension.name != dim.name):
                                        
                                        new_loc = Location(
                                            dim,
                                            target_x,
                                            target_y,
                                            target_z,
                                            target_pitch,
                                            target_yaw
                                        )
                                        p.teleport(new_loc)
                                        self.logger.info(f"Restored location for {p.name} on server '{self.server_name}'")
                            except Exception as e:
                                self.logger.error(f"Failed to restore location for {name}: {e}")

                        if inv_unresolved or ec_unresolved:
                            self._unresolved[xuid] = {
                                "inventory": inv_unresolved,
                                "enderchest": ec_unresolved,
                            }
                            total = len(inv_unresolved) + len(ec_unresolved)
                            self.logger.info(
                                f"[Vault] {p.name} has {total} unresolved item(s) in vault "
                                f"(inv: {len(inv_unresolved)}, ec: {len(ec_unresolved)})"
                            )

                        if bundles_json:
                            try:
                                bundle_payload = json.loads(bundles_json)
                                if bundle_payload.get("bundles"):
                                    bundle_payload["playerName"] = p.name
                                    restore_cmd = (
                                        f'scriptevent invshare:bundle_load '
                                        f'{json.dumps(bundle_payload, ensure_ascii=False)}'
                                    )
                                    self.server.dispatch_command(
                                        self.server.command_sender, restore_cmd
                                    )
                                    self.logger.info(
                                        f"[Bundle Sync] Dispatched {len(bundle_payload['bundles'])} "
                                        f"bundle(s) for restore to {p.name}"
                                    )
                            except Exception as bundle_err:
                                self.logger.warning(
                                    f"[Bundle Sync] Failed to dispatch bundle restore for {p.name}: {bundle_err}"
                                )

                    finally:
                        self._loading_players.discard(xuid)

                # Delay execution by 2 ticks (100ms) after PlayerJoinEvent
                self.server.scheduler.run_task(self, apply_inventory_sync, delay=2)

            except Exception as e:
                self._loading_players.discard(xuid)
                self.logger.error(f"Failed to load inventory for player {name}: {e}")
        
        if self.executor:
            self.executor.submit(load_inventory_task)

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        """Save the player's inventory and ender chest to the database safely."""
        target = event.player
        name = target.name
        xuid = target.xuid

        is_loading = xuid in self._loading_players
        is_kicked = xuid in self._kicked_players

        self._loading_players.discard(xuid)
        self._kicked_players.discard(xuid)

        if is_loading or is_kicked:
            self.logger.warning(
                f"[Inventory Save] Player {name} quit while inventory was loading or kicked — "
                f"skipping save to protect database inventory from corruption."
            )
            if self.executor:
                self.executor.submit(self.set_login_status, xuid, False)
            return

        try:
            data = self._extract_player_data(target)
            self._unresolved.pop(xuid, None)
            
            if self.executor:
                self.executor.submit(self._save_player_data_async, data)
                self.executor.submit(self.set_login_status, xuid, False)
            else:
                self.logger.error("Executor is not running, cannot save player async!")
        except Exception as e:
            self.logger.error(f"Failed to extract inventory for {name}: {e}")

    # -----------------------------------------------------------------------
    # Companion Addon Communication (ScriptMessageEvent)
    # -----------------------------------------------------------------------

    @event_handler
    def on_script_message(self, event: ScriptMessageEvent):
        """Handle messages from the InvShare Bundle Companion addon."""
        msg_id = event.message_id

        if msg_id == "invshare:bundle_save":
            try:
                payload = json.loads(event.message)
                player_name = payload.get("playerName", "")
                if player_name:
                    self._bundle_cache[player_name] = payload
                    bundle_count = len(payload.get("bundles", []))
                    accessible = sum(
                        1 for b in payload.get("bundles", []) if b.get("accessible")
                    )
                    self.logger.info(
                        f"[Bundle Sync] Received {bundle_count} bundle(s) for {player_name} "
                        f"({accessible} with accessible contents)"
                    )
            except Exception as e:
                self.logger.warning(f"[Bundle Sync] Failed to parse bundle_save: {e}")

        elif msg_id == "invshare:bundle_chunk":
            try:
                chunk_info = json.loads(event.message)
                player_name = chunk_info.get("_playerName", "")
                chunk_index = chunk_info.get("_chunkIndex", 0)
                chunk_total = chunk_info.get("_chunkTotal", 1)
                chunk_data = chunk_info.get("_data", "")

                if player_name not in self._bundle_chunks:
                    self._bundle_chunks[player_name] = {
                        "chunks": {}, "total": chunk_total
                    }

                self._bundle_chunks[player_name]["chunks"][chunk_index] = chunk_data

                received = self._bundle_chunks[player_name]["chunks"]
                if len(received) == chunk_total:
                    full_json = "".join(
                        received[i] for i in range(chunk_total)
                    )
                    payload = json.loads(full_json)
                    payload["playerName"] = player_name
                    self._bundle_cache[player_name] = payload
                    del self._bundle_chunks[player_name]
                    self.logger.info(
                        f"[Bundle Sync] Reassembled chunked bundle data for {player_name} "
                        f"({chunk_total} chunks)"
                    )
            except Exception as e:
                self.logger.warning(f"[Bundle Sync] Failed to process bundle_chunk: {e}")

        elif msg_id == "invshare:diagnostic":
            try:
                diag = json.loads(event.message)
                accessible = diag.get("accessible", False)
                player_name = diag.get("playerName", "unknown")
                bundle_type = diag.get("bundleType", "unknown")
                item_count = diag.get("itemCount", -1)

                if accessible:
                    self.logger.info(
                        f"[Bundle Companion] ✓ DIAGNOSTIC PASS: {player_name}'s {bundle_type} "
                        f"has {item_count} readable item(s). Cross-server bundle sync is ACTIVE."
                    )
                else:
                    self.logger.warning(
                        f"[Bundle Companion] ✗ DIAGNOSTIC FAIL: Cannot read contents of "
                        f"{player_name}'s {bundle_type}. The Script API on this Bedrock version "
                        f"does not expose bundle container data. Bundles remain server-bound."
                    )
            except Exception as e:
                self.logger.warning(f"[Bundle Sync] Failed to parse diagnostic: {e}")
