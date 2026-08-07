/**
 * InvShare Bundle Companion
 * 
 * Bridges the gap between Bedrock's Item Components system and the Endstone
 * Inventory Share plugin. Bundles store their contents in the component layer
 * (minecraft:storage_item) which Endstone's Python API cannot access.
 * 
 * This addon periodically snapshots bundle contents for each player and relays
 * the data to Endstone via /scriptevent when the player leaves.
 * 
 * Communication Protocol:
 *   Addon -> Endstone:  /scriptevent invshare:bundle_save <json>
 *   Endstone -> Addon:  /scriptevent invshare:bundle_load <json>
 */

import { world, system, ItemStack } from "@minecraft/server";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** How often (in ticks) to snapshot bundle contents. 20 ticks = 1 second. */
const SNAPSHOT_INTERVAL_TICKS = 100; // Every 5 seconds

/** Max chars per /scriptevent message payload. */
const SCRIPTEVENT_MAX_LENGTH = 2048;

/** Namespace prefix for our script events. */
const NS = "invshare";

// ---------------------------------------------------------------------------
// In-memory cache: playerId -> serialized bundle data
// ---------------------------------------------------------------------------

/** @type {Map<string, object[]>} */
const bundleCache = new Map();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Check if an item type ID represents a bundle (vanilla or dyed).
 * @param {string} typeId 
 * @returns {boolean}
 */
function isBundle(typeId) {
    return typeId.includes("bundle");
}

/**
 * Serialize a single ItemStack to a portable JSON-friendly object.
 * Captures type, amount, and any accessible component data.
 * @param {ItemStack} item 
 * @returns {object}
 */
function serializeItem(item) {
    const result = {
        type: item.typeId,
        amount: item.amount,
    };

    // Capture enchantments if available
    try {
        const enchComp = item.getComponent("minecraft:enchantable");
        if (enchComp) {
            const enchants = enchComp.getEnchantments();
            if (enchants && enchants.length > 0) {
                result.enchantments = enchants.map(e => ({
                    type: e.type.id,
                    level: e.level,
                }));
            }
        }
    } catch (e) { /* Component not available */ }

    // Capture durability
    try {
        const durComp = item.getComponent("minecraft:durability");
        if (durComp) {
            result.durability = {
                damage: durComp.damage,
                maxDurability: durComp.maxDurability,
            };
        }
    } catch (e) { /* Component not available */ }

    // Capture display name / lore
    try {
        if (item.nameTag) result.nameTag = item.nameTag;
        const lore = item.getLore();
        if (lore && lore.length > 0) result.lore = lore;
    } catch (e) { /* Not available */ }

    // Capture dynamic properties (custom data)
    try {
        const dynProps = item.getDynamicPropertyIds();
        if (dynProps && dynProps.length > 0) {
            result.dynamicProperties = {};
            for (const propId of dynProps) {
                result.dynamicProperties[propId] = item.getDynamicProperty(propId);
            }
        }
    } catch (e) { /* Not available */ }

    return result;
}

/**
 * Attempt to read the contents of a bundle item.
 * Tries multiple API approaches since the component interface varies by version.
 * 
 * @param {ItemStack} bundleItem 
 * @returns {object[]|null} Array of serialized items, or null if inaccessible
 */
function readBundleContents(bundleItem) {
    const contents = [];

    // Approach 1: Try minecraft:inventory component (provides Container)
    try {
        const invComp = bundleItem.getComponent("minecraft:inventory");
        if (invComp && invComp.container) {
            const container = invComp.container;
            for (let i = 0; i < container.size; i++) {
                const inner = container.getItem(i);
                if (inner) {
                    contents.push({ slot: i, ...serializeItem(inner) });
                }
            }
            if (contents.length > 0) return contents;
        }
    } catch (e) {
        // Approach 1 failed, try next
    }

    // Approach 2: Try minecraft:storage_item component
    try {
        const storageComp = bundleItem.getComponent("minecraft:storage_item");
        if (storageComp) {
            // Some versions expose .container or .getItems()
            if (storageComp.container) {
                const container = storageComp.container;
                for (let i = 0; i < container.size; i++) {
                    const inner = container.getItem(i);
                    if (inner) {
                        contents.push({ slot: i, ...serializeItem(inner) });
                    }
                }
                if (contents.length > 0) return contents;
            }

            // Try .getItems() if available
            if (typeof storageComp.getItems === "function") {
                const items = storageComp.getItems();
                items.forEach((item, idx) => {
                    if (item) {
                        contents.push({ slot: idx, ...serializeItem(item) });
                    }
                });
                if (contents.length > 0) return contents;
            }
        }
    } catch (e) {
        // Approach 2 failed, try next
    }

    // Approach 3: Try minecraft:bundle_contents component directly
    try {
        const bundleComp = bundleItem.getComponent("minecraft:bundle_contents");
        if (bundleComp) {
            if (bundleComp.container) {
                const container = bundleComp.container;
                for (let i = 0; i < container.size; i++) {
                    const inner = container.getItem(i);
                    if (inner) {
                        contents.push({ slot: i, ...serializeItem(inner) });
                    }
                }
                if (contents.length > 0) return contents;
            }
        }
    } catch (e) {
        // All approaches exhausted
    }

    return contents.length > 0 ? contents : null;
}

/**
 * Scan a player's inventory for bundles and serialize their contents.
 * @param {import("@minecraft/server").Player} player 
 * @returns {object[]|null} Array of bundle descriptors with contents
 */
function scanPlayerBundles(player) {
    try {
        const invComp = player.getComponent("minecraft:inventory");
        if (!invComp || !invComp.container) return null;

        const container = invComp.container;
        const bundles = [];

        for (let i = 0; i < container.size; i++) {
            const item = container.getItem(i);
            if (!item) continue;
            if (!isBundle(item.typeId)) continue;

            const bundleData = {
                slot: i,
                type: item.typeId,
                amount: item.amount,
            };

            // Try to read what's inside
            const contents = readBundleContents(item);
            if (contents !== null) {
                bundleData.items = contents;
                bundleData.accessible = true;
            } else {
                // Contents couldn't be read via Script API
                bundleData.items = [];
                bundleData.accessible = false;
            }

            bundles.push(bundleData);
        }

        return bundles.length > 0 ? bundles : null;

    } catch (e) {
        // Player might be invalid
        return null;
    }
}

// ---------------------------------------------------------------------------
// Periodic Snapshot System
// ---------------------------------------------------------------------------

/**
 * Runs every SNAPSHOT_INTERVAL_TICKS to cache bundle data for all online
 * players. Since we can't access inventory during playerLeave, we maintain
 * a rolling snapshot.
 */
system.runInterval(() => {
    for (const player of world.getAllPlayers()) {
        try {
            const bundles = scanPlayerBundles(player);
            if (bundles) {
                bundleCache.set(player.id, {
                    playerName: player.name,
                    bundles: bundles,
                    timestamp: Date.now(),
                });
            } else {
                // Player has no bundles — clear cache entry
                bundleCache.delete(player.id);
            }
        } catch (e) {
            // Player might have disconnected mid-scan
        }
    }
}, SNAPSHOT_INTERVAL_TICKS);

// ---------------------------------------------------------------------------
// Player Leave: Dispatch cached bundle data to Endstone
// ---------------------------------------------------------------------------

world.afterEvents.playerLeave.subscribe((event) => {
    const playerId = event.playerId;
    const playerName = event.playerName;
    const cached = bundleCache.get(playerId);

    if (!cached || !cached.bundles || cached.bundles.length === 0) {
        // No bundle data to sync
        bundleCache.delete(playerId);
        return;
    }

    // Build the payload
    const payload = {
        playerName: playerName,
        bundles: cached.bundles,
        capturedAt: cached.timestamp,
    };

    const jsonStr = JSON.stringify(payload);

    // Dispatch via server command since player object is no longer valid
    try {
        if (jsonStr.length <= SCRIPTEVENT_MAX_LENGTH) {
            world.getDimension("overworld").runCommand(
                `scriptevent ${NS}:bundle_save ${jsonStr}`
            );
        } else {
            // Chunk the payload for large bundle inventories
            const chunkCount = Math.ceil(jsonStr.length / SCRIPTEVENT_MAX_LENGTH);
            for (let i = 0; i < chunkCount; i++) {
                const chunk = jsonStr.substring(
                    i * SCRIPTEVENT_MAX_LENGTH,
                    (i + 1) * SCRIPTEVENT_MAX_LENGTH
                );
                const chunkPayload = JSON.stringify({
                    _chunked: true,
                    _chunkIndex: i,
                    _chunkTotal: chunkCount,
                    _playerName: playerName,
                    _data: chunk,
                });
                world.getDimension("overworld").runCommand(
                    `scriptevent ${NS}:bundle_chunk ${chunkPayload}`
                );
            }
        }
    } catch (e) {
        console.warn(`[InvShare Companion] Failed to dispatch bundle data for ${playerName}: ${e}`);
    }

    // Clean up cache
    bundleCache.delete(playerId);
});

// ---------------------------------------------------------------------------
// Player Join: Listen for Endstone sending bundle restore data
// ---------------------------------------------------------------------------

system.afterEvents.scriptEventReceive.subscribe((event) => {
    if (event.id === `${NS}:bundle_load`) {
        try {
            const data = JSON.parse(event.message);
            const playerName = data.playerName;

            // Find the player
            const players = world.getAllPlayers().filter(p => p.name === playerName);
            if (players.length === 0) {
                console.warn(`[InvShare Companion] Player ${playerName} not found for bundle restore`);
                return;
            }

            const player = players[0];
            const invComp = player.getComponent("minecraft:inventory");
            if (!invComp || !invComp.container) return;

            const container = invComp.container;

            for (const bundleData of data.bundles) {
                // Only restore if we were able to read contents originally
                if (!bundleData.accessible || !bundleData.items || bundleData.items.length === 0) {
                    continue;
                }

                // Create the bundle item
                try {
                    const bundle = new ItemStack(bundleData.type, bundleData.amount || 1);

                    // Try to populate the bundle's internal storage
                    const storageComp = bundle.getComponent("minecraft:inventory")
                        || bundle.getComponent("minecraft:storage_item")
                        || bundle.getComponent("minecraft:bundle_contents");

                    if (storageComp && storageComp.container) {
                        for (const itemData of bundleData.items) {
                            try {
                                const innerItem = new ItemStack(itemData.type, itemData.amount || 1);

                                // Restore enchantments
                                if (itemData.enchantments) {
                                    const enchComp = innerItem.getComponent("minecraft:enchantable");
                                    if (enchComp) {
                                        for (const ench of itemData.enchantments) {
                                            try {
                                                enchComp.addEnchantment({
                                                    type: ench.type,
                                                    level: ench.level,
                                                });
                                            } catch (ee) { /* Enchant not available */ }
                                        }
                                    }
                                }

                                // Restore name tag & lore
                                if (itemData.nameTag) innerItem.nameTag = itemData.nameTag;
                                if (itemData.lore) innerItem.setLore(itemData.lore);

                                // Restore durability damage
                                if (itemData.durability) {
                                    const durComp = innerItem.getComponent("minecraft:durability");
                                    if (durComp) {
                                        durComp.damage = itemData.durability.damage;
                                    }
                                }

                                storageComp.container.setItem(itemData.slot, innerItem);
                            } catch (itemErr) {
                                console.warn(
                                    `[InvShare Companion] Failed to restore inner item ${itemData.type}: ${itemErr}`
                                );
                            }
                        }
                    }

                    // Place the populated bundle in the player's inventory
                    const targetSlot = bundleData.slot;
                    const existing = container.getItem(targetSlot);
                    if (!existing) {
                        container.setItem(targetSlot, bundle);
                    } else {
                        // Target slot is occupied — find first empty slot
                        container.addItem(bundle);
                    }

                } catch (bundleErr) {
                    console.warn(
                        `[InvShare Companion] Failed to restore bundle ${bundleData.type}: ${bundleErr}`
                    );
                }
            }

            console.log(
                `[InvShare Companion] Restored ${data.bundles.length} bundle(s) for ${playerName}`
            );

        } catch (e) {
            console.warn(`[InvShare Companion] Failed to process bundle_load: ${e}`);
        }
    }
});

// ---------------------------------------------------------------------------
// Startup Diagnostics
// ---------------------------------------------------------------------------

world.afterEvents.playerSpawn.subscribe((event) => {
    if (!event.initialSpawn) return;

    const player = event.player;

    // Run a diagnostic check on the first player to join
    system.runTimeout(() => {
        try {
            const invComp = player.getComponent("minecraft:inventory");
            if (!invComp || !invComp.container) return;

            const container = invComp.container;
            let bundleFound = false;

            for (let i = 0; i < container.size; i++) {
                const item = container.getItem(i);
                if (!item || !isBundle(item.typeId)) continue;

                bundleFound = true;
                const contents = readBundleContents(item);
                const accessible = contents !== null;

                // Log diagnostic info
                console.log(
                    `[InvShare Companion] Diagnostic: Found ${item.typeId} in slot ${i}. ` +
                    `Contents accessible: ${accessible}. ` +
                    (accessible ? `Items inside: ${contents.length}` : "API cannot read bundle contents on this version.")
                );

                // Send diagnostic result to Endstone
                const diagPayload = JSON.stringify({
                    playerName: player.name,
                    bundleType: item.typeId,
                    slot: i,
                    accessible: accessible,
                    itemCount: accessible ? contents.length : -1,
                    apiVersion: "beta",
                });

                player.runCommand(
                    `scriptevent ${NS}:diagnostic ${diagPayload}`
                );

                break; // Only need one diagnostic
            }

            if (!bundleFound) {
                console.log(
                    `[InvShare Companion] Diagnostic: No bundles found in ${player.name}'s inventory. ` +
                    `Give them a bundle with items to test accessibility.`
                );
            }
        } catch (e) {
            console.warn(`[InvShare Companion] Diagnostic failed: ${e}`);
        }
    }, 60); // Wait 3 seconds after spawn
});

console.log("[InvShare Companion] Bundle sync companion addon loaded successfully.");
