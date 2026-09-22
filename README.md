<p align="center"><img src="docs/assets/banner.svg" width="100%" alt="Endstone Inventory Share"></p>

# Inventory Share v2.7.7

Share inventories, armor, offhand, ender chests, XP, Money scores, tags, and per-server locations through MySQL/MariaDB. Item NBT and unresolved custom items are preserved in JSON storage.

**v2.7.7 automatically recovers legacy login locks on join.** Players previously kicked with `INV-LEGACY` can reconnect without an administrator command. The plugin atomically replaces the old tokenless flag with a protected session and restores the saved inventory. Existing session tokens remain protected, including pending saves from another server. Upgrade all servers sharing the database together.

[Download](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/releases/tag/v2.7.7) · [Recovery guide](docs/recovery.md) · [Validation](docs/validation-2.7.7.md) · [Changelog](CHANGELOG.md) · [日本語](README_JP.md)

## What changed

- Retries temporary load failures without blocking the server thread or allowing inventory actions before restore finishes.
- Recovers pending saves belonging to disconnected local sessions before joining and during periodic saves, without releasing active sessions.
- Keeps valid inventories accessible when optional XP, Money, or tags fail to restore; their original database fields are preserved through quit and recovery.
- Automatically adopts a legacy lock whose session token is NULL or empty, without clearing saved inventory fields or requiring a command. Competing joins cannot both claim it.
- Protects a nonempty session token even if an old writer changed its login flag, and avoids the reproduced duplicate-row claim deadlock.
- Captures inventories before the native `stop` / `minecraft:stop` command removes players.
- Saves complete snapshots every 30 seconds by default and on ordinary disconnect.
- Keeps the latest snapshot in `pending-inventories.sqlite3` until that session finishes successfully. Startup replays pending snapshots before accepting logins.
- Serializes database work so an older queued save cannot overwrite the final inventory.
- Commits inventory and login-lock release together. Session tokens prevent an old or rejected connection from overwriting or unlocking another server's inventory.
- Prevents loading or failed-restore inventories from being saved over good database data.
- Preserves the previous complete snapshot when an item or its NBT cannot be serialized, and logs the failure.

## Install or upgrade

1. Back up the shared database, worlds, and Inventory Share's plugin data directories.
2. Stop **all servers sharing the database** before upgrading. Replace the old wheel on every server with v2.7.7; do not mix older writers with this version.
3. Keep each server's existing plugin data directory and configuration. Start one server in maintenance mode to run the additive schema migration, then check the console for errors. Migration adds `session_token` and normalizes the old text login flag without deleting inventories.
4. Legacy flags left after an old reboot recover automatically when each affected player joins. No per-player command or configuration change is needed. The old flag cannot identify a live pre-token server, so those old servers must stay stopped until upgraded.
5. Start the other servers, allow players to reconnect, and use the console's `stop` command for planned restarts.

```sh
gh release download v2.7.7 --repo TheNINJALLO/endstone-inventory-share-plugin --pattern "*.whl"
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
join_wait_seconds = 15
```

`autosave_seconds` defaults to 30 for existing configurations and is clamped to a minimum of 5. All participating servers use the same database. Give them different `server-name` values in `server.properties` to keep their location histories separate. Keep database credentials private.

`join_wait_seconds` defaults to 15 and is clamped to 1–60 seconds. A busy handoff or transient MySQL connection/lock error is retried once per second during this window. Connection timeouts, queue delays, and server lag can extend elapsed time. Gameplay input, item pickup, and damage are blocked while loading; connection/control packets continue. Invalid database credentials require administrator action. Tokenless legacy locks recover automatically on the first successful claim.

## Load errors and legacy recovery

| Code | Meaning / action |
|---|---|
| `INV-LEGACY` (older releases) | Upgrade all sharing servers to v2.7.7. The next join automatically recovers this tokenless flag; v2.7.7 no longer emits this error. |
| `INV-BUSY` | The previous server still owns the inventory after the retry window. Check that server's pending saves and connectivity; do not forcibly clear its lock. |
| `INV-DB` | Database access failed. The console records the actual MySQL error. |
| `INV-DATA` | The inventory/vault could not be restored. The console now includes the underlying exception; keep the stored data for repair. |
| `INV-JOURNAL` | Local recovery storage is unavailable. Check disk space and filesystem permissions. |

Automatic recovery logs `Automatically recovered legacy inventory lock` with the player's name and XUID. It changes only the login flag/session token inside the claim transaction, then restores the saved inventory normally. If loading fails for another reason, incomplete local inventories still cannot overwrite saved data.

The older **server console** command remains available as an optional maintenance tool after the affected player has disconnected everywhere:

```text
invshare recoverlegacy AFFECTED_NUMERIC_XUID confirm-offline
```

The command preserves inventory data and refuses to clear token-owned sessions or a player currently connected locally. The explicit `confirm-offline` argument means the operator has checked the other servers. It cannot prove an old server is offline remotely. Never use it to allow simultaneous sessions. Full procedure: [recovery guide](docs/recovery.md).

If an optional XP, Money, or tags field fails to restore, that field remains unchanged in the database for the session. Changes to the affected field are not synchronized until its underlying error is fixed and it can be restored on a later join; the console identifies the field and cause.

## Restart and recovery behavior

For panel restarts, configure the panel to send `stop` and wait for the process to exit. Successful shutdown logs `Inventory shutdown flush complete; no pending saves.` Database failures retain the local journal and the shared login lock. The owning server retries disconnected sessions during periodic saves and before reconnect; startup also recovers its journal before accepting logins.

A forced kill, power loss, OS shutdown signal, or a plugin calling the shutdown API directly may bypass the command capture. Recovery then uses the last complete snapshot. Changes since that snapshot can be lost; the configured interval is not a guarantee during server stalls, slow storage, or capture errors. Back up and retain `pending-inventories.sqlite3` with the server's plugin data. Do not run two server processes against the same local plugin directory.

This update cannot reconstruct items already overwritten by an older release. Restore those from an existing backup if necessary.

## Compatibility and scope

| Component | Requirement / validation |
|---|---|
| Endstone | `>=0.11.9,<0.12`, API `0.11`; live validation on `0.11.11` |
| BDS | Version supported by your Endstone runtime; live validation on Windows `1.26.51.1` |
| Python | `>=3.10` |
| Database | MySQL/MariaDB with InnoDB; tests use MariaDB `11.4` |
| Commands | Saving/restoring is automatic; `invshare recoverlegacy` is console-only |

The optional bundle companion remains version/API dependent. Its Script API fallback and custom behavior-pack items were not part of this release's live validation; do not assume bundle contents are portable when the companion reports that they are inaccessible. Standard item NBT, names, lore, and durability are covered by the live test.

## Development and releases

Run `python -m pytest` after installing this project and pytest. Set `INVSHARE_TEST_PORT` (and optionally `INVSHARE_TEST_HOST`, `INVSHARE_TEST_USER`, `INVSHARE_TEST_PASSWORD`) to a disposable MariaDB instance to run the integration tests. **These tests reset the `invshare_test.player_data` table.** See [validation](docs/validation-2.7.7.md) for the real-server runner.

GitHub Actions runs the automated and database tests before building and uploading a tagged release wheel. The repository's `docs/` directory contains the maintained operational guides; this repository does not have a separate enabled GitHub wiki.

Licensed under Apache-2.0. Original plugin by Kuma3mccm.
