# v2.7.7 validation

The automated suite passes **59 tests, including 23 real MariaDB 11.4 integration cases**, with no skips. Ruff also passes. The shutdown, journal, retry, and optional-field tests from v2.7.6 remain included.

New coverage verifies automatic adoption of both NULL and empty legacy tokens, preservation of every saved field, single ownership under concurrent joins, rollback after an interrupted adoption, nonempty-token protection even with an inconsistent login flag, rejection of empty new session tokens, and successful join/logging without a legacy kick.

The simultaneous-join test reproduced a deadlock when two transactions first acquired shared duplicate-key locks through `INSERT IGNORE` and then requested exclusive row locks. Claims now acquire the exclusive duplicate-row lock immediately. This follows the documented [InnoDB duplicate-key locking behavior](https://dev.mysql.com/doc/refman/8.0/en/innodb-locks-set.html). Existing transient-error retries remain in place for other contention or connection errors.

```powershell
$env:INVSHARE_TEST_PORT = '33421'
python -m pytest -q
python -m ruff check src tests scripts
```

Use a disposable database: the integration tests reset `invshare_test.player_data`.

## Real-server acceptance

The runner uses Windows BDS 1.26.51.1, Endstone 0.11.11, MariaDB 11.4, and an offline scripted client. The eight [v2.7.6 acceptance phases](validation-2.7.6.md#real-server-acceptance) remain included. Two additional phases set the existing player's login flag with a NULL token and an empty token. Each must restore the complete saved inventory without a command or disconnect, establish ownership with the joining session's token, log recovery, and save/release correctly at shutdown. Local inventory is deliberately wrong before restore.

```powershell
python scripts/test_live_shutdown.py --bds C:/fixtures/bds-1.26.51.1 `
  --server scratch/new-server --output scratch/new-results `
  --wheel dist/endstone_inventory_share_plugin-2.7.7-py3-none-any.whl `
  --client C:/fixtures/bedrock-client.exe --db-port 33421 `
  --database invshare_live_277 --join-cases
```

Final GitHub-built wheel acceptance is pending; release publication waits for all ten phases and a recorded matching wheel digest.

See [fixture setup](validation-2.7.5.md) for the pinned client source. These checks do not cover Linux BDS, retail clients, production load, custom behavior packs, or simultaneous operation with pre-token writers. Stop and upgrade all sharing servers together: legacy flags cannot identify a live old server. Existing token-owned sessions and their pending saves remain protected.
