# Changelog

## 2.7.12 - 2026-10-28

- Support Endstone 0.11.15 with BDS 1.26.60.6 / protocol 2225. Rebuild the native inventory synchronization helper against SDK commit `b4aaa87d2c5305e7d340168f824ac2e2ea722e44` and retain exact runtime/fingerprint checks.
- Fix the startup rejection that leaves all logins blocked after upgrading to the runtime required by BlockData 0.6.9. Preserve the shared schema, inventory format, session fencing, recovery journal, and failed-restore protections.
- Keep standalone SDK formatting substitutions in a generated header rather than modifying the pinned checkout; refresh the bundled native provenance notice.
- Update the scripted equipment/recovery client for protocol 2225 and test that previous and unknown Endstone versions remain blocked before native code loads.
- Validate the final Linux/Windows wheels with five live equipment checks and ten shutdown/crash/recovery phases per platform. CI passes 79 lifecycle/MariaDB tests on Python 3.11, 3.13, and 3.14; make equipment reports atomic after a reproduced Windows fixture read race.

## 2.7.10 - 2026-10-06

- Support Endstone 0.11.13 with BDS 1.26.52.3 on Linux and Windows x86-64.
- Rebuild the native inventory synchronization helper against the pinned 0.11.13 SDK.
- Update Endstone dependencies and executable hash checks; reject old or unknown native runtime profiles.
- Preserve missing-facade import fixes, automatic recovery, inventory serialization, and shutdown/crash protections.

## 2.7.9 - 2026-10-06

- Resolve Location and ItemStack from Endstone native exports when Python facade packages are missing.
- Add full entry-point import regression tests with each missing facade and both missing together.
- Preserve native inventory synchronization, database recovery, and the existing qualified runtime checks.

## 2.7.8 - 2026-09-27

- Fix native stack-ID desynchronization after restore that rejects offhand and armor equipment requests.
- Assign final slots directly and publish Bedrock inventory contents through a bundled C++ bridge.
- Gate the bridge on qualified BDS 1.26.51.1 executable hashes and Endstone 0.11.11/0.11.12.
- Preserve unsupported saved slots in the unresolved vault; propagate native slot-write failures instead of marking partial restores ready.
- Add native Linux/Windows packaging, full-inventory equipment regression fixtures, and runtime compatibility tests.
- Retain and recheck automatic legacy recovery, shutdown capture, crash journals, and multi-server handoff protection.

## 2.7.7 — 2026-09-21

- Automatically recover tokenless legacy login flags on join, replacing `INV-LEGACY` kicks and per-player console intervention.
- Adopt the row and load saved fields in one transaction; preserve inventory, ender chest, XP, Money, tags, locations, bundles, and unresolved items.
- Protect existing token owners even if their login flag is inconsistent. Require all sharing servers to be upgraded together.
- Avoid the reproduced concurrent-claim deadlock by acquiring an exclusive duplicate-row lock before reading ownership.
- Test NULL/empty legacy tokens, competing claims, transaction rollback, and real-player legacy recovery; retain shutdown, journal, and handoff regression coverage.

## 2.7.6 — 2026-09-21

- Retry temporary database errors and busy inventory handoffs before kicking a joining player; configurable default wait is 15 seconds.
- Recover failed local disconnect saves before reconnect and during periodic saves, while protecting active sessions and newer login markers.
- Block gameplay inventory input, pickups, and damage until restore completes.
- Preserve optional XP/Money/tag fields on restore failures instead of kicking players or overwriting those fields.
- Add explicit load-failure codes, full underlying error diagnostics, and console-only legacy-lock recovery with offline confirmation.
- Reject malformed inventory record shapes before clearing local items.
- Retain the v2.7.5 shutdown capture, ordered writes, atomic release, and crash recovery protections.

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
