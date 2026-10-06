# Inventory Share 2.7.10 validation

This release targets Endstone **0.11.13** and BDS **1.26.52.3**. The native helper is built against Endstone commit `3491c609ddfde392cee2b062e3063e39aae87274`.

## Runtime profiles

| Platform | BDS executable SHA-256 |
|---|---|
| Linux x86-64 BDS 1.26.52.3 | `0a490c711d4a2ce075debcd979e8862b7eaba008373f9970f0edbb67f98f9207` |
| Windows x86-64 BDS 1.26.52.3 | `19c88569af2e4b7d984e999055a31cbcb0799dacf8bbbf7371eda42f5772a443` |

Both server downloads are verified against the archive hashes in Endstone's server metadata before computing the executable profiles. Old Endstone/BDS combinations and unknown executable hashes remain blocked before native code is loaded.

## Checks

- 77 automated tests, including 23 tests against disposable MariaDB 11.4. CI tests Endstone 0.11.13 on Python 3.11, 3.13, and 3.14.
- Full plugin entry-point import with either or both `endstone.level` and `endstone.inventory` Python facades unavailable.
- Native equipment fixture: a full inventory; totem and shield offhand moves; all four armor slots; identical and different-inventory restores; occupied equipment; empty snapshots; item names and lore; agreement between the server and client.
- SQL lifecycle fixture: stop/restart, forced kill and journal recovery, transient database failure, busy handoff, local recovery, NULL/empty legacy flags, and invalid optional metadata (ten phases).

Both GitHub-built platform wheels passed the equipment fixture and all ten shutdown/recovery phases. Linux was qualified with Python 3.13.16 and NetherNet LAN discovery; Windows with Python 3.11.9 and direct RakNet requests. NetherNet loopback discovery was unavailable in the Windows fixture. Local Linux equipment checks also passed on Python 3.14.7.

The [GitHub build](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/actions/runs/37517336344) passed all three Python/MariaDB jobs and both native build jobs. The published wheels are these exact live-tested artifacts; production Python/native source matches the release tag. Checksums are verified again after upload.

- [Linux equipment](validation/2.7.10-equipment-linux.json)
- [Windows equipment](validation/2.7.10-equipment-windows.json)
- [Linux shutdown/recovery](validation/2.7.10-shutdown-linux.json)
- [Windows shutdown/recovery](validation/2.7.10-shutdown-windows.json)
- [Release checksums](validation/2.7.10-SHA256SUMS.txt)

## Scope and reproduction

These are scripted native protocol requests against disposable servers and an isolated database. Retail clients, production load, arbitrary server binaries, other inventory plugins, and custom behavior-pack bundle contents are outside this qualification.

Use [the live fixtures](../tests/live/README.md) and [native build instructions](../native/README.md). The shutdown runner now supports both Linux and Windows; `--db-host` selects a disposable database reachable from a container. All generated worlds and test artifacts must remain under new `scratch` directories.
