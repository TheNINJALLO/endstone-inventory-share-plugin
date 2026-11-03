/**
 * Optional bundle diagnostics for Inventory Share 2.7.13.
 * Native typed NBT carries the complete bundle tree, including custom lore.
 * Historical companion snapshots remain in SQL for manual recovery.
 * This addon never creates, clears, replaces or adds inventory items.
 */
import { world, system } from '@minecraft/server';

system.afterEvents.scriptEventReceive.subscribe(event => {
    if (event.id === 'invshare:bundle_load') {
        console.warn('[InvShare Companion] Ignored legacy additive restore. Native item NBT is authoritative; retain old SQL records for recovery.');
    }
});

world.afterEvents.playerSpawn.subscribe(event => {
    if (!event.initialSpawn) return;
    system.runTimeout(() => {
        try {
            const player = event.player;
            const inventory = player.getComponent('minecraft:inventory').container;
            let bundles = 0;
            for (let slot = 0; slot < inventory.size; slot++) {
                const item = inventory.getItem(slot);
                if (!item || !item.typeId.endsWith('bundle')) continue;
                const storage = item.getComponent('minecraft:inventory');
                if (storage) bundles++;
            }
            console.log(`[InvShare Companion] Read-only bundle diagnostics for ${player.name}: ${bundles} accessible bundle(s).`);
        } catch (error) {
            console.warn(`[InvShare Companion] Bundle diagnostics unavailable: ${error}`);
        }
    }, 40);
});
