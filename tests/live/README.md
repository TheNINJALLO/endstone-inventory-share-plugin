# Real-server inventory qualification

Use disposable BDS copies and a disposable database only. Equipment tests register a probe that imports the restore function from the supplied wheel; InventoryUI and Backpacks are absent. Shutdown tests load the actual Inventory Share plugin and exercise its SQL/journal lifecycle.

Build `tests/live/client` with Go 1.26 (`go build -o bedrock-inventory-client .`). The pinned Gophertunnel client sends native ItemStackRequests using IDs from BDS packets and response updates. It opens the real inventory container, uses the native offhand and armor slots, and fails on rejected requests or packet violations.

```sh
python scripts/test_live_equipment.py --bds /path/to/fixture --output scratch/equipment-run --wheel /path/to/platform.whl --client /path/to/bedrock-inventory-client
```

Run under an Endstone-enabled Python environment matching the fixture. Output must be a NEW directory under `scratch`. The runner owns and stops its new server. Add `--expect-rejection` with v2.7.7 to verify the known stale-ID failure after successful baseline equipment moves. The new release must pass without that flag.

Use `scripts/test_live_shutdown.py --help` for the ten-phase SQL lifecycle fixture (`--join-cases`). These are automated protocol-client tests against BDS, not retail device/touch/controller or production multi-plugin tests. Preserve results and wheel hashes in the release validation record.
