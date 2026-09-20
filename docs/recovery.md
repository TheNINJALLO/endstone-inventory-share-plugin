# Shutdown and inventory recovery

## Planned reboots

Configure the control panel's stop action to send the native `stop` command and wait for BDS to exit. Inventory Share captures complete snapshots while players still exist, drains earlier saves, and commits each final snapshot with its login-lock release. Look for:

```text
Captured N inventory snapshot(s) before stop.
Inventory shutdown flush complete; no pending saves.
```

The ordinary player-disconnect path also captures before the player becomes unavailable. Never depend solely on `on_disable`: BDS can remove players before that callback without firing the ordinary quit event.

## Database outage or interrupted shutdown

The local `plugins/inventory_share_plugin/pending-inventories.sqlite3` file records the latest complete snapshot for every active/pending session. It is retained even after an autosave reaches MySQL, until the session is released. A restart replays snapshots only if their original session token still owns the corresponding shared row.

1. Preserve the owning server's plugin data directory and journal.
2. Restore database connectivity and write access.
3. Restart that server with v2.7.5. Startup recovery runs before logins are accepted.
4. Confirm that the console reports no pending saves, then reconnect the player.

If recovery fails, logins to that server stay blocked. Other servers also reject the affected player while its inventory is locked. Do not clear that lock to bypass a pending save: doing so can make the older shared inventory authoritative. If the journal is lost, restore from a known backup and reconcile the player's inventory during maintenance.

An older journal is discarded if a newer session owns the row or if the original session has already committed its release. This prevents a recovered server from overwriting a player who has moved elsewhere.

## Locks left by v2.7.4 or earlier

The old shutdown path can leave `is_logged_in` set even though the player is offline. Those rows have no `session_token` after migration. New versions preserve these locks because an older server might still be using the inventory.

Stop all servers sharing this database, back up the table, and upgrade every server. Start one server in maintenance mode with player joins blocked to run schema migration, then stop it. Inspect the affected player's row in your configured database:

```sql
SELECT player_xuid, is_logged_in, session_token
FROM player_data
WHERE player_xuid = 'REPLACE_WITH_AFFECTED_XUID';
```

Only after confirming the player is offline on every participating server and that this is a legacy row with a NULL token, release that specific legacy lock:

```sql
UPDATE player_data
SET is_logged_in = 0
WHERE player_xuid = 'REPLACE_WITH_AFFECTED_XUID'
  AND session_token IS NULL;
```

This does not recover inventories already rolled back by an earlier release. For missing items, restore the appropriate backup instead of deleting or blanking inventory columns.

## Other storage errors

- **Table is not InnoDB:** stop participating servers, back up the database, and convert `player_data` to InnoDB using your database administration tools before restarting. Transactions and row locks are required.
- **Cannot create/migrate schema:** grant the configured account the necessary database/schema privileges, or have the database administrator apply the changes.
- **Snapshot capture/serialization failed:** the plugin retains the previous complete snapshot and logs the affected player/slot. Resolve the underlying item/API error before relying on further saves.
- **Disk/journal write failure:** free space or restore filesystem permissions. Keep the existing journal and take a backup before changes.

## Limits

Force-killing the process does not run a shutdown hook. The last completed periodic snapshot is recoverable, but later changes may be lost. OS signals and third-party code calling the shutdown API directly can also bypass the `stop` command capture. Ask those integrations to issue the native console command. The autosave interval is measured in server ticks; lag, disk failures, and long database queues can extend it.

The companion's Script API bundle fallback is asynchronous and version dependent. It is not a substitute for a complete native NBT snapshot. Keep existing behavior packs and validate their custom items separately.
