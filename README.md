<!-- endstone-professional-header:start -->
<p align="center">
  <img src="docs/assets/banner.svg" width="100%" alt="Endstone Inventory Share &mdash; Multi-server inventory sharing for Endstone 0.11.9">
</p>

<p align="center">
  <a href="https://github.com/TheNINJALLO/endstone-inventory-share-plugin/actions/workflows/wheel-release.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/TheNINJALLO/endstone-inventory-share-plugin/wheel-release.yml?branch=main&amp;style=for-the-badge&amp;logo=githubactions&amp;logoColor=white&amp;label=Build"></a>
  <a href="https://github.com/TheNINJALLO/endstone-inventory-share-plugin/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/TheNINJALLO/endstone-inventory-share-plugin?display_name=tag&amp;style=for-the-badge&amp;label=Release"></a>
</p>

<p align="center">
  <img alt="Endstone 0.11.9" src="https://img.shields.io/badge/Endstone-0.11.9-52b7a8?style=flat-square">
  <img alt="API 0.11" src="https://img.shields.io/badge/API-0.11-63b8ff?style=flat-square">
  <img alt="BDS 1.26.44" src="https://img.shields.io/badge/BDS-1.26.44-8b7dff?style=flat-square">
  <img alt="Python >=3.10" src="https://img.shields.io/badge/Python-%3E=3.10-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
</p>

<p align="center">
  <strong>Multi-server inventory sharing for Endstone 0.11.9.</strong>
</p>

<p align="center">
  <a href="#what-it-does">What it does</a> &bull;
  <a href="#how-to-use">How to use</a> &bull;
  <a href="#commands-and-permissions">Commands</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="https://github.com/TheNINJALLO/endstone-inventory-share-plugin/releases">Releases</a>
</p>

## Overview

Multi-server inventory sharing for Endstone 0.11.9. This release is aligned with Endstone 0.11.9 and Minecraft Bedrock Dedicated Server 1.26.44, and is distributed as a Python wheel for direct installation in an Endstone server.

## What it does

- Synchronizes player inventory and ender-chest contents across multiple Endstone servers.
- Preserves full item NBT in a shared MySQL database and coordinates login/join/quit save and load timing.
- Includes conflict handling and migration support for older storage formats.

## How to use

1. Run `create_db.sql` against a dedicated MySQL database using a least-privilege database account.
2. Start each server once, then add the same database connection settings to its local `config.toml`; never commit the password.
3. Restart all participating servers and test with a non-production player moving between two servers.
4. Stop or transfer players cleanly before database maintenance so the latest inventory is written.

## Commands and permissions

This plugin has no player commands. Inventory synchronization runs automatically during login, join, periodic updates, and disconnect events after the shared MySQL connection is configured.

## Compatibility

| Component | Supported version |
|---|---|
| Endstone | `0.11.9` |
| Endstone API | `0.11` |
| Bedrock Dedicated Server | `1.26.44` |
| Python | `>=3.10` |
| Plugin release | `v2.7.4` |

## Install

Download the wheel from the matching GitHub release:

```bash
gh release download v2.7.4 --repo TheNINJALLO/endstone-inventory-share-plugin --pattern "*.whl"
```

Copy the downloaded wheel into the server's `plugins/` directory, remove any older wheel for the same plugin, and restart Endstone.

> [!IMPORTANT]
> Use Endstone `0.11.9` with BDS `1.26.44`. Back up worlds and plugin data before upgrading a production server.

## Configuration and secrets

Runtime databases, logs, local `.env` files, server directories, and root `config.toml` files are excluded from source releases. When an example configuration is provided, copy it locally and keep live tokens, passwords, webhook URLs, and server identifiers out of Git.

## Release automation

Every `v*` tag runs [the wheel release workflow](.github/workflows/wheel-release.yml), builds the package in a clean GitHub runner, stores the wheel as a workflow artifact, and attaches it to the matching GitHub release.
<!-- endstone-professional-header:end -->

---

## Project guide

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
