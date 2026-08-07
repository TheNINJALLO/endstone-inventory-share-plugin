# Inventory Share Plugin

A multi-server inventory sharing plugin for [Endstone](https://github.com/EndstoneMC/endstone) that uses MySQL to synchronize player inventories across servers.

## Features

- **Full inventory sync** — Main inventory, armor, and offhand items are saved and restored across servers
- **Ender chest sync** — Ender chest contents are shared between servers
- **Complete NBT preservation** — All item data is preserved, including:
  - Enchantments
  - Custom names and lore
  - Shulker box contents
  - Damage / durability
  - Repair cost, unbreakable flags, and all other NBT data
- **Scoreboard sync** — The "Money" scoreboard objective score is saved and restored across servers
- **Player tag sync** — All player tags (set via `/tag`) are saved and restored across servers
- **Double-login protection** — Prevents players from connecting to multiple servers simultaneously

## Setup

1. Place the `.whl` file into your Endstone server's `plugins` folder and start the server once.
2. Edit the generated config at `plugins/inventory_share_plugin/config.toml` with your MySQL connection details.
3. Run `create_db.sql` on your MySQL server to create the database and tables.
4. Restart or reload the server.
5. 🎉

## Configuration

Edit `plugins/inventory_share_plugin/config.toml`:

```toml
sql_host = "your-mysql-host.com"
sql_port = "3306"
sql_user = "your_user"
sql_pass = "your_password"
sql_db_name = "player_data"
```

## Upgrading from v1.x

v2.0.0 uses a new JSON-based storage format with full NBT data. If you are upgrading from v1.x, run the following SQL on your database:

```sql
ALTER TABLE player_data
  MODIFY player_inv MEDIUMTEXT,
  MODIFY player_enderchest MEDIUMTEXT;

-- Clear old incompatible data (players will start with empty inventories on first join)
UPDATE player_data SET player_inv = NULL, player_enderchest = NULL;
```

## Requirements

- [Endstone](https://github.com/EndstoneMC/endstone) (API 0.11+)
- MySQL server
- Python packages: `PyMySQL`, `pycryptodome`

## License

inventory-share-plugin by Kuma3mccm is licensed under the Apache License, Version 2.0
