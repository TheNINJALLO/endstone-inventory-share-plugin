# Inventory Share 2.7.11 validation — 2026-10-12

Target: Endstone 0.11.14, SDK `03f4189b1535af0870861748fc569f6deac0ad65`, unchanged BDS 1.26.52.3 / protocol 2193. The native helper and platform wheels were rebuilt. Exact Endstone and BDS guards remain enabled; unsupported versions fail closed. Package installation requires Python >=3.11. The helper retains its existing cp310 stable ABI.

| Check | Linux x86-64 | Windows x86-64 |
| --- | --- | --- |
| Native helper and wheel build | Passed | Passed |
| Live equipment checks | 5 passed | 5 passed |
| Shutdown, crash and recovery phases | 10 passed | 10 passed |

Equipment checks cover totem/shield offhand movement, all four armor slots, identical and occupied-equipment restores, replacing a different local inventory, names/lore, and empty snapshots. Recovery phases cover save/restart, forced crash, transient DB failure, handoff, local recovery, legacy null/empty locks, metadata preservation, and post-shutdown database state. Every clean-stop phase exited successfully. Linux used CPython 3.14.7 and Windows used CPython 3.11.9 with their matching official Endstone 0.11.14 wheels.

55 unit tests passed; 23 MySQL-specific unit tests were excluded from that unit run. The separate live recovery runs used a disposable MariaDB fixture. All live servers and databases were disposable. Windows fixtures were retried after freeing temporary disk space; the completed results above are from the successful retries. The test runner also waits for a complete spawn snapshot and copies Windows fixture directories without invoking PowerShell.

Machine-readable results and wheel hashes: [validation-2.7.11.json](validation-2.7.11.json). Release assets contain these validated builds.
