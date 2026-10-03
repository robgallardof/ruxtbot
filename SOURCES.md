# Data sources and scope

Snapshot: 2026-10-02, vanilla PC servers (modded multipliers are not included).

## Raid targets — `data/raid.json`

Built by `scripts/build_raid_data.py` from:

- **Rustly API v1** (`data/sources/rustly_raid.json`) — 27 targets: walls and floors (hard and soft side), doors, double doors, tool cupboard, auto turret and vehicles. Datamined from game build 2633.288.1; C4, rocket, satchel, beancan, F1 and HV amounts are measured in game by Rustly. Free to use with a link to [rustly.com](https://rustly.com/raid/), shown in `/sources` and in every raid footer.
- **RustClash durability tables** (`data/sources/rustclash_durability.json`, trimmed to the explosive rows) — 30 more targets: high external walls and gates, hatches, floor grill, windows, embrasures, bars, shop front, prison cell, fences, barricades, shotgun trap, flame turret, SAM site, tesla coil, large box, vending machine, large furnace, workbench 3. Hard side only.
- Siege amounts (catapult, mortar, MLRS, 40mm HE, ballista, ram, cannon) for the original eight doors and walls come from the previous RustClash-based catalog.

Rules:
- Amount = units needed with direct hits; no splash stacking between targets.
- Costs are raw materials to craft the full amount (sulfur, charcoal, metal fragments). Recipes without a verified cost (MLRS, ram, 40mm HE) are shown as "cost not verified", never as free.
- "Cheapest" only picks common explosives; siege and fire are shown and tagged but not recommended.
- Rustly and RustClash are behind bot checks, so the raw snapshots are captured with a real browser and committed. Refresh them after a patch and re-run the build script.

## Crafting — `data/rust_catalog.yml`

Official Facepunch Wiki recipes (explosives, satchel, beancan, F1, explosive ammo, molotov) plus RustClash recipes (rocket, HV, incendiary, propane, mortar, cannonball, hammerhead). Batches round up; launchers and weapons are not included.

## Pictures

Item icons: `https://wiki.rustclash.com/img/items180/<shortName>.png` (shortNames from the Rustly item API). Vehicles have no item icon, so the UI shows the icon of their cheapest explosive.

## Servers

`data/servers.json` holds 75 server names/IDs from the authenticated BattleMetrics profile, plus anything imported with `/syncservers`. `/serversearch` queries BattleMetrics live. `/forcewipe` computes the first Thursday of each month at 2 PM US Eastern (DST-aware, no external data).

The tracker uses `GET /players/{id}?include=server` and only trusts a boolean `meta.online` from an online server with a valid query updated less than five minutes ago. Missing, private or stale data keeps the last reading and never counts as a disconnect. The first reading is silent. Delivery is retried if Discord fails before the state is saved; exactly-once delivery is not promised.

## /who

Sources queried in parallel; a failing one is listed in the footer:

- Steam Community: `/profiles/{id}?xml=1`, the profile page (level, games, badges), `/ajaxaliases` (Steam name history) and `/id/{vanity}?xml=1`.
- SteamID formats computed locally with the steamid.io formula.
- RustWho: `fetch-v1.rustwho.com/stats/public/{id}` (bans, server bans, name history, Rust stats — informational, not proof of cheating).
- BattleMetrics: `GET /players/{id}?include=server,identifier` with a profile link. Without one, an exact-name search lists up to three unverified candidates with the other names they used.
- Steam Web API (`IPlayerService/GetOwnedGames`) only with `STEAM_API_KEY`.
- SteamDB returns 403 to bots, so its calculator (`?cc=mx`) is linked instead of scraped.
