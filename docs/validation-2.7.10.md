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

Local Linux equipment checks passed on Python 3.13 and 3.14; the local Linux SQL lifecycle fixture passed all ten phases. Release wheels remain in draft until their live checks finish. The final artifact reports and checksums are attached to the published release.

## Scope and reproduction

These are scripted native protocol requests against disposable servers and an isolated database. Retail clients, production load, arbitrary server binaries, other inventory plugins, and custom behavior-pack bundle contents are outside this qualification.

Use [the live fixtures](../tests/live/README.md) and [native build instructions](../native/README.md). The shutdown runner now supports both Linux and Windows; `--db-host` selects a disposable database reachable from a container. All generated worlds and test artifacts must remain under new `scratch` directories.
