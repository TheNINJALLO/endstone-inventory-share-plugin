# Inventory Share 2.7.12 validation — 2026-10-28

Target: Endstone **0.11.15**, SDK `b4aaa87d2c5305e7d340168f824ac2e2ea722e44`, BDS **1.26.60.6**, protocol **2225**. Exact SDK/runtime and executable checks remain enabled. This fixes the 2.7.11 guard rejecting the server version required by BlockData 0.6.9.

| Check | Linux x86-64 | Windows x86-64 |
| --- | --- | --- |
| CI native helper build | Ubuntu 22.04, Clang 20 | Windows 2022, Clang 20 |
| Final release wheel equipment checks | 5 passed | 5 passed |
| Final release wheel shutdown/recovery phases | 10 passed | 10 passed |
| Live test Python | 3.14.10 | 3.11.9 |

[CI run 40750141556](https://github.com/TheNINJALLO/endstone-inventory-share-plugin/actions/runs/40750141556) passed all **79 tests** with disposable MariaDB 11.4 on each of Python 3.11, 3.13, and 3.14, plus lint and both native builds. Compiled native libraries from that run were repackaged with the updated SDK notice; those exact final wheel files were then used by the live fixtures. Their hashes are recorded in [validation-2.7.12.json](validation-2.7.12.json) and the release evidence.

Equipment checks exercised actual protocol-2225 requests: totem/shield offhand moves, all four armor slots, identical restores, occupied equipment, replacing a different inventory, names/lore, and empty snapshots. The scripted client pins gophertunnel commit `25acc41eb24af21cfebf27ffa5ace37069838eb3`.

Lifecycle phases covered save/restart, an intentional forced crash and recovery, transient database failure, session handoff, pending local recovery, legacy null/empty locks, and preserved optional metadata. All clean-stop phases exited with status zero and verified the database afterward. Crash phases intentionally exited nonzero before successful recovery.

One final Windows equipment attempt encountered a partial JSON report read after four checks. The fixture now publishes reports atomically and tolerates a briefly open Windows reader; rerunning the same release wheel completed all five checks. Production restore code did not change for that fixture correction.

All servers, worlds, clients, and databases used for qualification were disposable. Existing production inventory data was not accessed. Clients used offline-mode test servers; production authentication and the optional custom bundle companion were outside this validation. No BDS executable is redistributed.
