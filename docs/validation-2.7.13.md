# Inventory Share 2.7.13 safety validation

Target: Endstone 0.11.15 / BDS 1.26.60.6 / protocol 2225. The evidence below was recorded locally before publication; release packaging preserves the qualified runtime code.

All four safety candidates loaded together on Windows and Linux: InventoryUI 2.0.10, Backpacks 1.0.94, Inventory Manager 1.0.18 and the matching Inventory Share 2.7.13 wheel. Each OS passed twelve actual nested-bundle, custom-lore, GUI, SQL and failed-write checks. The live barrier test confirms shared ownership stays held while a backpack save awaits recovery. Installed source/native bytes match the tested wheels.

The additional ten-phase process lifecycle suite ran on Windows and includes the complete native NBT tree captured from a real Script API-filled nested bundle. It covers restart, forced crash, temporary database failures, handoff, recovery and legacy/optional-field handling. The initial phase had auxiliary plugin-import errors; later phases loaded them. Separate twelve-check runs establish current four-plugin coexistence on both platforms.

The four affected Python suites pass 140 tests; all 23 isolated MariaDB tests pass. Inventory Share contributes 65 offline tests. The native helpers are byte-identical to qualified 2.7.12, and exact runtime/fingerprint guards remain enabled. No new native compilation is claimed.

Follow-up: the user confirms all servers share Backpacks MySQL and losses appear after reconnect/server change. Seven shared-database integration checks with independent store/manager instances pass. The preserved 1.0.93 handler reproduces a late empty overwrite of newer shared contents; the staged 1.0.94 closed-session/menu guards prevent it. This follow-up changes tests/evidence, not runtime wheel bytes, and does not establish the production incident's cause.

| Platform wheel | SHA-256 |
| --- | --- |
| Windows | `75ced71ee22e48fc4389f8ecefb78ced7fbccaab4c3a86770280dbddf0eef249` |
| Linux | `6953625f7a2d313c5ccb384ee676a45fd25685312105546f4a1d2044785b10b1` |

See [the release safety report](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/releases/download/v2.7.13/ITEM_STORAGE_SAFETY_REVIEW.md) and [qualification JSON](validation-2.7.13.json) for exact scope and hashes. Cross-server backpack contents still require a shared Backpacks database. Older lost items/metadata require backups or retained recovery records. Virtual-storage following-tick reconciliation, retail clients, arbitrary custom behavior packs and distributed concurrent backpack editing are outside the guarantees of these checks.
