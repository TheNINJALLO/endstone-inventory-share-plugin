# v2.7.6 validation

The automated suite contains 52 tests, including 16 MariaDB integration cases. The original shutdown/recovery regressions remain included. New checks cover handoff and transient connection retries, bounded retry deadlines, legacy/auth error classification, cancellation on quit, optional-field preservation through disconnect/recovery, input protection while loading, pending-save recovery before reconnect, protection of newer journal markers, skipping active inventory payloads during join recovery, and safe console-only legacy recovery.

```powershell
$env:INVSHARE_TEST_PORT = '33420'
python -m pytest -q
python -m ruff check src tests scripts
```

Use a disposable MariaDB instance: automated tests reset `invshare_test.player_data`.

## Real-server acceptance

The wheel is exercised on Windows BDS 1.26.51.1 / Endstone 0.11.11 with MariaDB 11.4 and one connected scripted client. The first four phases are the original save-before-stop, deliberately wrong local inventory on restart, forced crash after a failed database save, and journal recovery tests. Four additional phases exercise:

1. Two injected MySQL connection failures before a successful load, without a disconnect.
2. A simulated previous-server session retaining its MySQL lock for three seconds, then committing a newer XP value and releasing it. The joining player waits and restores the newer state.
3. A failed local disconnect save left in the journal, recovered before the next claim.
4. Invalid legacy tags: inventory/XP load successfully, and the original tags field remains unchanged after shutdown.

The retry phases also assert that incoming gameplay packets were actually blocked while the scripted client waited. The fixture uses real Endstone inventory/NBT objects and the wheel's production persistence and event handlers; only fault injection and assertions live in the probe subclass.

```powershell
python scripts/test_live_shutdown.py --bds C:/fixtures/bds-1.26.51.1 `
  --server scratch/new-server --output scratch/new-results `
  --wheel dist/endstone_inventory_share_plugin-2.7.6-py3-none-any.whl `
  --client C:/fixtures/bedrock-client.exe --db-port 33420 `
  --database invshare_live_276 --join-cases
```

See [v2.7.5 validation](validation-2.7.5.md) for fixture setup and the pinned client source. All eight phases passed on the final GitHub-built wheel. The exact wheel digest, phase results, and CI build provenance are recorded in [Windows results](validation/2.7.6-windows.json).

This does not establish the exact cause of an individual production kick without its console error. It covers reproduced failure paths. The live fixture uses an offline scripted client, not a retail client, and does not cover production loads, Linux BDS, custom behavior packs, or arbitrary third-party inventory mutations. A genuinely active remote session or unavailable/corrupt inventory is still refused rather than overwritten.
