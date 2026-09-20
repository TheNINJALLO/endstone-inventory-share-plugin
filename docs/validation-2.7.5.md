# v2.7.5 validation

## Automated coverage

30 tests cover pre-stop capture when BDS removes players without a quit event, FIFO final saves, draining queued quit saves, loading/failed-restore protection, stale callbacks after reconnect, local journal reopening, backpressure on autosaves, and capture/NBT failures.

The suite includes 11 real MariaDB 11.4 integration tests: atomic save/release and restore, competing claims, rejected/stale owners, crash recovery, crash after commit but before journal cleanup, interrupted loads, mid-transaction rollback, zero Money/removed tags, per-server location retention, and legacy text-flag migration. The full release run has no skipped tests.

```sh
python -m pip install . pytest ruff build
# Use only a disposable database: tests reset invshare_test.player_data.
export INVSHARE_TEST_PORT=33419
python -m pytest -q
python -m ruff check src tests scripts
python -m build --wheel
```

## Real Bedrock lifecycle validation

Windows BDS 1.26.51.1, Endstone 0.11.11, Python 3.11.9, MariaDB 11.4, and one offline scripted gophertunnel client. The runner extracts the wheel's actual package and uses a small subclass to seed/read real Player, Inventory, ItemStack, NBT, XP, and scoreboard objects. It uses the production event handlers, journal, database transactions, and shutdown implementation.

1. Seed an older inventory and complete an autosave. Change diamond/emerald counts immediately before issuing `stop`. Verify the newer snapshot and released login lock directly in MySQL after the process exits.
2. Restart and join with deliberately wrong local inventory/ender-chest contents and XP. Verify the full database restore, including armor, offhand, named/lore/damaged item NBT, Money, and tags; stop and verify MySQL again.
3. Seed new items, inject a database connection failure, complete a durable local snapshot, and forcibly terminate the server. The failure is intentional; there is no graceful shutdown hook in this phase.
4. Restart with database access restored. Verify journal replay before login and the full inventory restore, then stop and verify the saved data and lock release.

The initial development runtime probe reproduced the shutdown gap: `stop` removed players without a quit callback, leaving the latest changes uncaptured by `on_disable`. Adding the command-time capture made the lifecycle check pass.

Run on disposable fixtures only:

```powershell
python scripts/test_live_shutdown.py --bds C:/fixtures/bds-1.26.51.1 `
  --server scratch/new-server --output scratch/new-results `
  --wheel dist/endstone_inventory_share_plugin-2.7.5-py3-none-any.whl `
  --client C:/fixtures/bedrock-client.exe --db-port 33419
```

Use a blank-password root account on an isolated loopback MariaDB fixture. The live runner uses the separate `invshare_live` database and requires a new server/output directory. The client source and pinned Go dependencies are available in [Paradox's acceptance fixture](https://github.com/TheNINJALLO/endstone-paradox/tree/v2.0.1/native/tests/bedrock-client). The server fixture names match that client's LAN discovery filter; Paradox itself is not loaded.

Release evidence and wheel digest: [Windows results](validation/2.7.5-windows.json).

## Limits

This is actual server/network validation with a scripted client, not a retail-client test or production-load benchmark. The four live phases do not test Linux BDS, OS shutdown signals, custom behavior-pack items, or the optional Script API bundle fallback. CI additionally runs the database and lifecycle regression tests on Linux. Forced termination recovers the last completed snapshot; it cannot preserve changes made after that snapshot.
