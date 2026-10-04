# RuxtBot

Discord bot for Rust: raid planning with pictures, crafting, live servers, player lookups and BattleMetrics presence alerts.

Replies follow each user's Discord language: **English** by default, **Spanish** for Spanish clients (es-ES / es-419). Slash command descriptions are localized too. Background alerts use the language chosen with `/settings`.

## Commands

| Area | Commands |
| --- | --- |
| ⚡ Start here | `/me`, `/sv`, `/ip`, `/help`, `/examples` |
| 💥 Raid | `/raid`, `/raidcalc`, `/raidbudget`, `/raidcompare`, `/raidtools` |
| 🛠️ Crafting & base | `/craft`, `/item`, `/upkeep`, `/decay`, `/binds`, `/cctv`, `/sources` |
| 🖥️ Servers | `/server`, `/online`, `/serverstats`, `/leaderboard`, `/serversearch`, `/servers`, `/wipe`, `/forcewipe`, `/rust` |
| 🕵️ Players | `/who`, `/findplayer`, `/player`, `/presence`, `/sessions`, `/playercompare`, `/steamid` |
| 🔔 Alerts (everyone) | `/track`, `/team`, `/wipealert`, `/serverwatch` |
| ⚙️ Server managers | `/setserver`, `/delserver`, `/settings`, `/pausealerts`, `/resumealerts`, `/status`, `/syncservers` |
| 🏷️ Bot | `/version` (everyone), `/update`, `/restart` (bot owner), `/author`, `/ping` |

Lookups are **public by default** so the whole channel sees them: `/who`, `/player`, `/presence`, `/sessions`, `/findplayer`, `/playercompare`, `/online`, `/server`, `/serverstats`, `/leaderboard`, `/team`, and the confirmations of `/track`, `/wipealert` and `/serverwatch`. Each has `share:false` to keep it private. Errors, notices, `/me`, `/settings`, `/status`, `/version` and personal panels are always private; when a public reply turns into an error, the public "thinking…" placeholder is deleted and the error is sent privately.

`/help` is a menu with buttons for the common next steps: 👤 My profile, 🎮 Our server, 🔎 Find player, 👀 Track and the raid tools. `/examples` is posted publicly so everyone in the channel can copy them.

Commands mentioned in `/help`, `/examples` and the welcome message are **clickable**: after the startup sync the bot knows each command's ID, so `` `/sv` `` becomes a Discord command mention that opens the command when tapped. Commands written with options stay as code so they can be copied. When the bot joins a server it posts a short setup guide (in the server's language) in the system channel, or the first channel it can write in, with a button that shows the examples.

### Your settings: `/me`

Settings are stored per Discord user and follow you to every server. `/me battlemetrics:<profile URL or ID>` saves your BattleMetrics profile; `/me server:` saves a default server; `/me forget:true` deletes everything. `/me` alone shows a card with buttons (set profile, who is on my server, find a player here, forget me).

Commands whose `server` is optional (`/server`, `/online`, `/serverstats`, `/leaderboard`) use, in order: the server you are playing on right now (from your BattleMetrics profile), your default server, then the Discord server's default `/sv` entry. `/findplayer` lists matches **on your current server first**: they are online right next to you, so that is the quickest way to get someone's BattleMetrics ID.

### Our server: `/sv`, `/ip`, `/setserver`

A server manager saves the community's servers once: `/setserver name:Main address:1.2.3.4:28015` (the whole `client.connect …` line also works), optionally with `battlemetrics:` for live data, and `default:true` for the one `/sv` shows first. If you only pick the BattleMetrics server, the address is read from it. `/sv` and `/ip` post **publicly**: name, live status and the `client.connect` line in a code block, with a **📋 Copy connect** button that replies with just the plain line for easy copying.

### Server tools (BattleMetrics)

- `/server`: live card with population and queue, official/community/modded, **rates** (gather, craft, scrap), group or team limit, upkeep and decay multipliers, blueprint wipes, kits, PvE, map size with its **RustMaps** page and thumbnail, last and next wipes (plus the following ones), FPS and uptime, and the connect line. Buttons: Copy connect, Online, Stats, Top, BattleMetrics, RustMaps, website.
- `/serverstats period:24 h|7 days|30 days`: player-count graph (sparkline) with peak, average and low; current and best rank; unique and new players; outages and total downtime.
- `/leaderboard period:all time|30 days|7 days|24 h`: players with the most hours on a server, paged, with a picker that opens their profile.
- `/serversearch`: name, country, minimum players, gather (1x, 2x, 3x+), maximum group (solo, duo, trio, quad), type, wiped in the last N days and PvE. BattleMetrics ignores or rejects most Rust feature filters (checked 2026-10-03), so the bot fetches up to 100 servers and filters them itself. A picker opens the full card.
- `/player player: server:` adds hours on that server, first and last seen, and a 30-day hours-per-day graph.
- In `/player`, `/sessions` and `/track`, the `server` suggestions follow the player already typed: their servers first (🟢 online there now, then most recent) with their hours on each. This works for BattleMetrics IDs and for SteamIDs already linked in the Discord.
- `/rust`: players and servers worldwide, with the 24-hour range and 7-day peak.
- `/upkeep server:` and `/decay server:` apply that server's upkeep and decay multipliers.

### Binds: `/binds`

Posts the binds and console (F1) commands guide publicly, one message per part (movement, combat & FOV · audio, aim & performance · items, chat & utilities), every bind in its own code block so it can be copied. The text lives in `data/binds.md`: edit it there. Use real Unicode emoji in that file, because Discord does not convert `:shortcodes:` sent by bots. Messages are split only at headings and stay under Discord's 2000-character limit.

### CCTV codes: `/cctv`

Posts the CCTV camera codes publicly, grouped by monument (small and large Oil Rig, Outpost, Bandit Camp, Dome, Airfield), every code in its own code block so it can be copied on its own and pasted into a Computer Station. The text lives in `data/cctv.md`: edit it there.

### Version and updates

`/version` shows the bot version, the commit it is running, uptime, ping and how many Discords and commands it has. The bot owner (the Discord application owner, or IDs in `BOT_OWNER_IDS`) also gets **Update & restart** and **Restart** buttons, and can use `/update` and `/restart`. `/update` runs `git pull --ff-only`, reinstalls requirements only if `requirements.txt` changed, and restarts the process in place. A copy uploaded without git says so and is updated from the host panel. Only fixed commands run: nothing typed by a user reaches a shell.

### Raid

- **57 targets** in six categories: doors, walls & high externals, floors & hatches, windows/bars/barricades, deployables (TC, turrets, SAM site, traps…) and vehicles. Walls and floors include the **soft side**.
- `/raid`: picture-based planner built with Discord **Components V2**. Every category shows a gallery of its targets; the simulator shows the target and explosive pictures, HP bar, sulfur/charcoal/frag cost, the 🏆 cheapest option, and buttons to apply, undo, complete, reset, switch side and compare.
- `/raidcalc`: base calculator. Add several targets (2 armored doors + 3 stone walls…), pick one method or "cheapest per target", and get explosives, totals and a picture per explosive. 📤 shares a read-only copy in the channel.
- `/raidbudget sulfur:20000`: how many of each explosive you can craft and how many targets of each kind you can destroy.
- "Cheapest" only considers common explosives; siege (catapult, mortar, ballista, ram, MLRS, 40mm HE, cannon) and fire are tagged in comparisons but never recommended by default. Unverified craft costs are shown as such, never as free.

### Players: no links, just IDs or names

Every player option takes a **SteamID64** (`7656119…`), `STEAM_0:X:Y`, `[U:1:N]` or a **BattleMetrics player ID** (numbers only). You never have to paste a link (pasted links still work).

After the first lookup the player goes into the guild's **player book** and every player option **autocompletes by name** (`KingGallardo · 7656119…`). The book is per Discord server (per user in DMs), keeps the 500 most recent players and never shares names between servers.

- **A SteamID is enough**: the bot finds the BattleMetrics ID and loads Steam, RustWho and BattleMetrics together. Order: link saved in this Discord → verified cache (30 days) → `quick-match` → same-name profiles that list the exact SteamID.
- **Why**: SteamIDs are *private identifiers*; BattleMetrics requires the `rcon:read` token scope to view and match them (developer documentation, Player object). Without it `quick-match` and `/players/match` answer 200 with no data.
- **Regular BattleMetrics tokens do not see SteamIDs** (checked 2026-10-03: `quick-match` answers 200 with no data and profiles only list names). Then `/who <SteamID>` lists the BattleMetrics profiles named like the player, most likely first (names shared with Steam/RustWho, online now, hours, servers; ⭐ when one clearly stands out). **Pick the right one once** and the link is saved for that Discord server: from then on the SteamID alone works in `/track`, `/presence`, `/player`, `/sessions`… Commands that hit an unlinked SteamID show an **🔗 Open profile and link** button. Nothing is linked without that confirmation.
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

`/who` posts the profile **publicly** by default so everyone in the channel sees it (`share:false` keeps it private). Errors, the cooldown notice and the lookup panel (`/who` with no options) only go to whoever typed it. On a public profile anyone can press Watch or Sessions (their replies are private); choosing which BattleMetrics profile to link stays with the person who asked.

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

### Alerts: open to every member

- **Anyone in the server** can use `/track`: watch a player for 1–15 days (7 by default), renew any watch, and see the server's shared list. Stopping someone else's watch needs its creator or a server manager.
- Alerts are posted in **the channel where they were requested** (`/track`, `/team`, `/wipealert`, `/serverwatch`), so everyone there sees them. `/settings` no longer picks a channel. Stopping a watch works from any channel of the same Discord.
- Alerts ping **whoever started the watch**, plus the alert role chosen with `/settings role:` (or a role named `wipe`, if there is exactly one). No role is required. Player names are escaped so they can never mention anyone, and `@everyone` is never allowed.
- If none of the player's servers is in the directory, the servers where they played in the last 14 days are watched (at least the latest one) and added to the directory.
- The first reading is silent and unknown data never counts as a disconnect.
- **Server managers** (Administrator or Manage Server) **and the bot owner** can use `/settings`, `/pausealerts`, `/resumealerts`, `/status` and `/syncservers`.

### More alerts: `/team`, `/wipealert`, `/serverwatch`

One background loop checks these every 2 minutes, fetching each server and player once per round. Every first reading is silent; alerts go to the channel where they were created and ping whoever created them. Anyone can create them; removing someone else's needs its creator or a server manager.

- `/team`: group up to 20 players (a rival clan), up to 25 teams per server. `action:Show` lists who is online and on which server; `action:Alerts on` posts whenever members connect or disconnect (unknown readings keep the previous state).
- `/wipealert server:` pings when the server's last-wipe date changes; `forced:true` reminds one hour before the monthly forced wipe and when it goes live.
- `/serverwatch server: above: below:` pings when the population crosses a threshold (for example, when it fills up on wipe day). 1–15 days.
- `/track server:🌍` watches a player on any server; the alert names the server they joined or left.
- **Stale online flags**: BattleMetrics keeps `online: true` while it cannot query a server (`queryStatus` other than `valid`). The bot treats that as unknown for alerts and shows it as 🟡 *unconfirmed* in `/who`, never as online.

### Base: `/upkeep`, `/decay`

- `/upkeep stone: stone_half: metal: hqm: wood: players:` gives resources per day and per week. Vanilla brackets: first 15 pieces 10 % of build cost per day, next 50 15 %, next 125 20 %, then 33.3 % (a 100-piece base pays 16 %). Full pieces: stone 300, wood 200, metal 200 fragments, armored 25 HQM; floors, triangles and half walls cost half.
- Group tax since [Breach and Clear](https://rust.facepunch.com/news/breach-and-clear) (3 September 2026): first 4 players free, next 6 add 2 % each, every player after adds 4 %, capped at 300 %. Players authed on the TC or any code lock (guests included, and anyone deauthed in the last 24 h) count.
- `/decay grade: health:` gives the time to full decay: twig 1 h, wood 3 h, stone 5 h, sheet metal 8 h, armored 12 h from full health ([Facepunch wiki](https://wiki.facepunch.com/rust/the_tool_cupboard)). Servers can change all of these with the decay convars.

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
