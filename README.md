# RuxtBot

Discord bot for Rust: raid planning with pictures, crafting, live servers, player lookups and BattleMetrics presence alerts.

Replies follow each user's Discord language: **English** by default, **Spanish** for Spanish clients (es-ES / es-419). Slash command descriptions are localized too. Background alerts use the language chosen with `/settings`.

## Commands

| Area | Commands |
| --- | --- |
| 💥 Raid | `/raid`, `/raidcalc`, `/raidbudget`, `/raidcompare`, `/raidtools` |
| 🛠️ Crafting | `/craft`, `/item`, `/sources` |
| 🖥️ Servers | `/server`, `/online`, `/serversearch`, `/servers`, `/wipe`, `/forcewipe` |
| 🕵️ Players | `/who`, `/findplayer`, `/player`, `/presence`, `/sessions`, `/playercompare`, `/steamid`, `/track` |
| ℹ️ Info | `/help`, `/examples`, `/author` |
| ⚙️ Admin | `/settings`, `/pausealerts`, `/resumealerts`, `/status`, `/syncservers`, `/ping` |

`/help` opens an interactive menu with buttons that launch the raid planner and the base calculator.

### Raid

- **57 targets** in six categories: doors, walls & high externals, floors & hatches, windows/bars/barricades, deployables (TC, turrets, SAM site, traps…) and vehicles. Walls and floors include the **soft side**.
- `/raid`: picture-based planner built with Discord **Components V2**. Every category shows a gallery of its targets; the simulator shows the target and explosive pictures, HP bar, sulfur/charcoal/frag cost, the 🏆 cheapest option, and buttons to apply, undo, complete, reset, switch side and compare.
- `/raidcalc`: base calculator. Add several targets (2 armored doors + 3 stone walls…), pick one method or "cheapest per target", and get explosives, totals and a picture per explosive. 📤 shares a read-only copy in the channel.
- `/raidbudget sulfur:20000`: how many of each explosive you can craft and how many targets of each kind you can destroy.
- "Cheapest" only considers common explosives; siege (catapult, mortar, ballista, ram, MLRS, 40mm HE, cannon) and fire are tagged in comparisons but never recommended by default. Unverified craft costs are shown as such, never as free.

### Players: no links, just IDs or names

Every player option takes a **SteamID64** (`7656119…`), `STEAM_0:X:Y`, `[U:1:N]` or a **BattleMetrics player ID** (numbers only). You never have to paste a link (pasted links still work).

After the first lookup the player goes into the guild's **player book** and every player option **autocompletes by name** (`KingGallardo · 7656119…`). The book is per Discord server (per user in DMs), keeps the 500 most recent players and never shares names between servers.

- **A SteamID is enough**: the bot finds the BattleMetrics ID by itself and loads Steam, RustWho and BattleMetrics together. Order: verified cache (30 days, no API call) → `quick-match` → if that is denied, BattleMetrics profiles with the same Steam name, accepted **only** when the profile lists that exact SteamID. Nothing is ever assumed from a name alone.
- **Type the name and press Enter**: a name typed without picking a suggestion is looked up in the book (exact name first, otherwise a single partial match).
- **Errors always offer a way out**: an unknown name shows a **🔎 Search «name»** button that runs the BattleMetrics name search in one click.
- `/who` with no options opens a panel: recent players, search by name, or enter a SteamID / BattleMetrics ID. `/help` has a **Find player** button that opens it.
- `/player player:` without a server shows where the player is (same as `/presence`).
- `/track` lists recent players in a **⚡ Watch for 7 days** picker: one click, nothing to type. The form accepts names too.
- `/findplayer name:` searches BattleMetrics by in-game name and shows each **BattleMetrics ID**; pick one to open the full profile.
- `/online server:` lists who is playing right now (20 per page, time in the current session). 👀 marks watched players, ⭐ players you looked up before; the picker opens a profile.
- `/playercompare first: second:` lists the servers two players have in common, hours of each and 🟢🟢 when both are online (possible teammates; not proof).
- `/steamid player:` converts between every SteamID format.

### Players: `/who`

`/who player:<SteamID64, BattleMetrics ID or name> bm_id:<optional BattleMetrics ID>`. With only a BattleMetrics ID, the bot reads the SteamID from the BattleMetrics profile when the token can see it, so Steam and RustWho data still appear. Buttons under the profile open **Watch 7 days** and **Sessions** directly. It shows:

- 📝 **Name history first**: merged from Steam, RustWho and BattleMetrics with date and source, plus how many older names are locked on RustWho.
- 👤 Steam status, every SteamID format (like steamid.io), creation date, level, games, badges, limited account.
- 🛡️ VAC, game, community, trade and server bans.
- 🦀 Rust stats from RustWho; 📊 BattleMetrics hours, servers and most played servers.
- SteamIDs are resolved automatically through the official authenticated `POST /players/quick-match` endpoint. Only an exact, unique identifier match is used. Account permissions may limit available matches; same-name candidates remain unverified and never activate tracking.
- Buttons to Steam, SteamID I/O, SteamDB (MXN calculator), RustWho and BattleMetrics. `STEAM_API_KEY` (optional) adds Rust hours.

### Servers

- Every `server` option takes a name from the suggestions **or any BattleMetrics server ID**. When the local directory has few matches, suggestions are filled live from BattleMetrics (cached, at most one search per second so the tracker keeps its rate limit).
- `/server`: live players, queue, map, rank, country, wipes, header image and `client.connect`.
- `/serversearch query:`: search any Rust server on BattleMetrics, most players first, with each server ID.
- `/forcewipe`: next Facepunch forced wipe (first Thursday of the month, 2 PM US Eastern) with countdowns in each user's time zone.

### Alerts

`/track action:Add player:<name, SteamID64 or BattleMetrics ID> server:<name>` pings the single `wipe` role on connect/disconnect. The first reading is silent, unknown data never counts as a disconnect, and player names are escaped so they cannot mention anyone. Available to server members; owners manage their watches and administrators can manage all watches.

## UX rules

- Interactive panels can only be used by whoever opened them; they disable themselves when they expire.
- Errors are red embeds with a hint on how to continue; a global handler catches anything unexpected.

## Data

- `data/raid.json` is generated by `python scripts/build_raid_data.py` from the snapshots in `data/sources/` ([Rustly](https://rustly.com/raid/) API v1 and [RustClash](https://wiki.rustclash.com/) durability tables). Both sites block non-browser clients, so the snapshots were captured with a browser; refresh them and re-run the script after a wipe/patch. See [SOURCES.md](SOURCES.md).
- `data/rust_catalog.yml` holds crafting recipes for `/craft` and `/item`.
- Item pictures come from `https://wiki.rustclash.com/img/items180/<shortName>.png`.

## Setup

1. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`. Add `BATTLEMETRICS_TOKEN` for `/server`, `/serversearch`, `/player`, `/track` and BattleMetrics data in `/who`; `STEAM_API_KEY` is optional.
2. Docker: `docker compose up -d --build` (the `rustbot-data` volume keeps watches and settings). Cybrancee: see [CYBRANCEE.md](CYBRANCEE.md).
3. Invite the bot with the `bot` and `applications.commands` scopes and permission to send messages and embed links. Global commands can take a few minutes to appear.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. pytest
```

The test suite checks the raid math, every panel against Discord's limits (40 components, 4000 characters) in both languages, that every translation key exists in English and Spanish with matching placeholders, that every command description has a Spanish version, presence/alert safety rules and the `/who` parsers.

### SteamID-first activity

- `/track action:Add player:<SteamID64>` watches the player's known servers in the synchronized directory, with no server IDs to copy. It displays current observations and retains the existing silent first-reading policy.
- `/syncservers profile:<SteamID64 or BattleMetrics ID>` imports accessible Rust servers; `/track` activates alerts separately.
- `/player player:<SteamID64> server:<name>` checks a selected server.
- `/presence player:<SteamID64> page:1` lists synchronized servers, fresh presence, recorded hours and last seen, ten per page.
- `/sessions player:<SteamID64> server:<optional name>` shows ten accessible sessions with start/end and duration. An unfinished session is not treated as proof of being online.
- Numeric BattleMetrics player IDs work everywhere; when SteamID matching is denied for the token, `/findplayer` gives the ID to use instead. Access denial, no exact match and ambiguity are reported separately.

API contract: [BattleMetrics developer documentation](https://www.battlemetrics.com/developers/documentation), Player Quick Match Identifiers and Player Session History, reviewed 2026-10-03. New commands require a bot restart to sync with Discord.

### Temporary, shareable tracking

`/track action:Add player:<SteamID64> days:7` works for regular server members. Duration defaults to seven days and accepts 1–15 days. Adding the same watch again renews it; only its owner or an administrator can modify it. One shared watch per player/server/channel avoids duplicate role notifications. Legacy watches expire seven days after migration and remain administrator-managed.

Expiry is stored in SQLite and survives restarts. Expired watches are removed before polling. The bot itself continues serving commands, but makes no tracking requests when no active watches remain. Connection and disconnection changes mention the configured server's `wipe` role; the existing role and channel permissions still apply.

Use `share:true` on `/track`, `/player`, `/who`, `/presence` or `/sessions` to publish the response in the channel where you invoked it. Friends can view and share the public Discord message. Replies remain private by default; this does not send DMs or post to unrelated chats.

Performance: duplicate player/server observations are reused within each polling cycle; expired watch timing entries are discarded; profile cache entries expire after eight seconds with a 256-profile cap; expired `/who` cooldown entries are removed. BattleMetrics rate-limit backoff remains enabled. These are bounded-state improvements, not a measured production memory benchmark.

### Guided tracking panel

Type `/track` with no arguments. Choose **Watch · 7 days** or **Watch · 15 days**, enter a SteamID and optionally a nickname. **Stop watching** removes your watches for that player in the configured alert channel; **My watches** refreshes the list. Each panel is controlled by its opener and expires after five minutes. The confirmation shows the destination channel, @wipe, and exact expiry. English and Spanish are supported.
