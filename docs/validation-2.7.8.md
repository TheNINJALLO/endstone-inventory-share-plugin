# Inventory Share 2.7.8 validation

## Reproduced regression

The released v2.7.7 wheel (SHA-256 `1ebe93fbff8ecd846e97077475a726150417b16dda73d9197892223bde65ca1b`) passes baseline equipment moves on Linux BDS 1.26.51.1, then rejects an offhand request with native status 49 after an identical inventory restore. InventoryUI and Backpacks are absent. The client's previous stack IDs no longer match the recreated server items.

## Qualification

- 70 automated tests, including 23 tests against disposable MariaDB 11.4. CI repeats the suite on Python 3.11 and 3.14.
- Native equipment fixture on Linux / Endstone 0.11.12 / Python 3.14.7 and Windows / Endstone 0.11.11 / Python 3.11.9.
- Full 36-slot inventory; totem and shield offhand moves; all four armor slots; identical and different-inventory restores; occupied equipment; empty snapshots; names and lore; server/client item agreement.
- Windows SQL lifecycle fixture: stop/restart, forced kill and journal recovery, transient database failure, busy handoff, pending local saves, NULL/empty legacy flags, and preservation of invalid optional metadata (ten phases).

**Both final GitHub-built platform wheels passed live qualification.** The exact SHA-256 values match the uploaded release assets. The [tag build](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/actions/runs/36372879818) passed both Python/MariaDB test jobs and both native build jobs.

- [Linux equipment results](validation/2.7.8-equipment-linux.json)
- [Windows equipment results](validation/2.7.8-equipment-windows.json)
- [Windows shutdown/recovery: all ten phases](validation/2.7.8-windows-shutdown.json)
- [Original v2.7.7 failure reproduction](validation/2.7.8-regression-v2.7.7-linux.json)
- [Release checksums](validation/2.7.8-SHA256SUMS.txt)

The release stayed in draft until these artifact checks passed. The reports and checksums are also attached to the GitHub release.

## Runtime profiles

| Platform | BDS executable SHA-256 |
|---|---|
| Linux x86-64 BDS 1.26.51.1 | `e93e739f373a84edfff7c9cd76fcb090c2176744b412e1143f1b38e91a49bed4` |
| Windows x86-64 BDS 1.26.51.1 | `76d547f82e02c18d0986c30b47132c9cc4171d0f2df1c00649e50ff35788b321` |

Endstone 0.11.11 and 0.11.12 are accepted; the live platform pairings above were tested. Linux wheels require glibc 2.35+. The CPython stable ABI supports 3.10+; live tests cover 3.11 and 3.14.

## Scope

These checks use native protocol requests against real disposable servers. They do not cover retail device rendering, controller/touch gestures, production load, every combination of inventory plugins, arbitrary BDS builds, or behavior-pack custom bundle contents. Inventory Share is a demonstrated source of this failure; separate interference by other plugins has not been ruled out.

Reproduction instructions: [live fixtures](../tests/live/README.md). Build details: [native bridge](../native/README.md). Operational guidance: [recovery](recovery.md).
