<p align="center"><img src="docs/assets/banner.svg" width="100%" alt="Endstone Inventory Share"></p>

# Inventory Share v2.7.5

Share inventories, armor, offhand, ender chests, XP, Money scores, tags, and per-server locations through MySQL/MariaDB. Item NBT and unresolved custom items are preserved in JSON storage.

**v2.7.5 fixes inventory rollback on server stop/reboot.** Bedrock can remove players before Endstone disables plugins, without a normal quit event. Inventory Share now captures inventories when the console or an operator issues `stop`, then drains its save queue and releases each inventory only after its save commits.

[Download](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/releases/tag/v2.7.5) · [Recovery guide](docs/recovery.md) · [Validation](docs/validation-2.7.5.md) · [Changelog](CHANGELOG.md) · [日本語](README_JP.md)

## What changed

- Captures inventories before the native `stop` / `minecraft:stop` command removes players.
- Saves complete snapshots every 30 seconds by default and on ordinary disconnect.
- Keeps the latest snapshot in `pending-inventories.sqlite3` until that session finishes successfully. Startup replays pending snapshots before accepting logins.
- Serializes database work so an older queued save cannot overwrite the final inventory.
- Commits inventory and login-lock release together. Session tokens prevent an old or rejected connection from overwriting or unlocking another server's inventory.
- Prevents loading or failed-restore inventories from being saved over good database data.
- Preserves the previous complete snapshot when an item or its NBT cannot be serialized, and logs the failure.

## Install or upgrade

1. Back up the shared database, worlds, and Inventory Share's plugin data directories.
2. Stop **all servers sharing the database** before upgrading. Replace the old wheel on every server with v2.7.5; do not mix older writers with this version.
3. Keep each server's existing plugin data directory and configuration. Start one server in maintenance mode to run the additive schema migration, then check the console for errors. Migration adds `session_token` and normalizes the old text login flag without deleting inventories.
4. If the previous version left players locked after a reboot, follow [legacy lock recovery](docs/recovery.md#locks-left-by-v274-or-earlier) before allowing joins. Existing locks are not indiscriminately cleared.
5. Start the other servers, allow players to reconnect, and use the console's `stop` command for planned restarts.

```sh
gh release download v2.7.5 --repo TheNINJALLO/endstone-inventory-share-plugin --pattern "*.whl"
```

For a new installation, place the wheel in `plugins/`, start once to create the configuration, enter your database settings, then restart. The plugin creates/migrates its schema; `create_db.sql` is also supplied for initial setup. Use an InnoDB table. The schema migration account needs CREATE/ALTER privileges as well as SELECT/INSERT/UPDATE.

## Configuration

Edit `plugins/inventory_share_plugin/config.toml`:

```toml
sql_host = "127.0.0.1"
sql_port = "3306"
sql_user = "inventory_share"
sql_pass = "replace-with-your-password"
sql_db_name = "player_data"
autosave_seconds = 30
```

`autosave_seconds` defaults to 30 for existing configurations and is clamped to a minimum of 5. All participating servers use the same database. Give them different `server-name` values in `server.properties` to keep their location histories separate. Keep database credentials private.

## Restart and recovery behavior

For panel restarts, configure the panel to send `stop` and wait for the process to exit. Successful shutdown logs `Inventory shutdown flush complete; no pending saves.` Database failures retain the local journal and the shared login lock; restore database access and restart the owning server so recovery can finish.

A forced kill, power loss, OS shutdown signal, or a plugin calling the shutdown API directly may bypass the command capture. Recovery then uses the last complete snapshot. Changes since that snapshot can be lost; the configured interval is not a guarantee during server stalls, slow storage, or capture errors. Back up and retain `pending-inventories.sqlite3` with the server's plugin data. Do not run two server processes against the same local plugin directory.

This update cannot reconstruct items already overwritten by an older release. Restore those from an existing backup if necessary.

## Compatibility and scope

| Component | Requirement / validation |
|---|---|
| Endstone | `>=0.11.9,<0.12`, API `0.11`; live validation on `0.11.11` |
| BDS | Version supported by your Endstone runtime; live validation on Windows `1.26.51.1` |
| Python | `>=3.10` |
| Database | MySQL/MariaDB with InnoDB; tests use MariaDB `11.4` |
| Commands | No custom player commands; saving/restoring is automatic |

The optional bundle companion remains version/API dependent. Its Script API fallback and custom behavior-pack items were not part of this release's live validation; do not assume bundle contents are portable when the companion reports that they are inaccessible. Standard item NBT, names, lore, and durability are covered by the live test.

## Development and releases

Run `python -m pytest` after installing this project and pytest. Set `INVSHARE_TEST_PORT` (and optionally `INVSHARE_TEST_HOST`, `INVSHARE_TEST_USER`, `INVSHARE_TEST_PASSWORD`) to a disposable MariaDB instance to run the integration tests. **These tests reset the `invshare_test.player_data` table.** See [validation](docs/validation-2.7.5.md) for the real-server runner.

GitHub Actions runs the automated and database tests before building and uploading a tagged release wheel. The repository's `docs/` directory contains the maintained operational guides; this repository does not have a separate enabled GitHub wiki.

Licensed under Apache-2.0. Original plugin by Kuma3mccm.
