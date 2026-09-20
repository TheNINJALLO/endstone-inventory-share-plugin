# Changelog

## 2.7.5 — 2026-09-20

- Fix rollback on native `stop` by capturing inventories before BDS removes players, then flushing saves during plugin disable.
- Add configurable periodic snapshots and a durable local recovery journal.
- Order asynchronous saves and atomically commit inventory data with login-lock release.
- Fence sessions across servers; rejected/old connections cannot clear another server's lock.
- Keep incomplete restores and failed item serialization from overwriting good inventories.
- Persist legitimate zero Money scores and removed tags, and retain original NBT in the vault when reconstruction fails.
- Migrate legacy text login flags without deleting inventory data; require InnoDB.
- Add automated, MariaDB, and live Windows BDS stop/restart/crash-recovery tests.

## 2.7.4

Compatibility update for Endstone 0.11.9 / BDS 1.26.44.
