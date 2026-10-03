# Graph Report - ruxtbot  (2026-10-03)

## Corpus Check
- 35 files · ~414,891 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 529 nodes · 1249 edges · 14 communities (13 shown, 1 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 91 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `973a1679`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_utilities.py
- raid.py
- test_integration.py
- BattleMetrics
- Store
- t
- Catalog
- RuxtBot
- who.py
- __init__.py
- RaidData
- ServerPagesView
- CommandTranslator
- build_raid_data.py

## God Nodes (most connected - your core abstractions)
1. `t()` - 65 edges
2. `lang_for()` - 64 edges
3. `RaidData` - 37 edges
4. `main()` - 36 edges
5. `target_layout()` - 32 edges
6. `error_embed()` - 31 edges
7. `builder_layout()` - 28 edges
8. `BattleMetrics` - 23 edges
9. `FakeInteraction` - 22 edges
10. `brand_embed()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `handler()` --indirect_call--> `status()`  [INFERRED]
  tests/test_identity.py → rustbot/utility_commands.py
- `request()` --indirect_call--> `status()`  [INFERRED]
  tests/test_presence.py → rustbot/utility_commands.py
- `track()` --indirect_call--> `bot()`  [INFERRED]
  rustbot/__main__.py → tests/test_integration.py
- `presence()` --indirect_call--> `bot()`  [INFERRED]
  rustbot/activity.py → tests/test_integration.py
- `bot()` --uses--> `Settings`  [INFERRED]
  tests/test_integration.py → rustbot/config.py

## Import Cycles
- None detected.

## Communities (14 total, 1 thin omitted)

### Community 0 - "test_utilities.py"
Cohesion: 0.11
Nodes (22): date, datetime, Settings read from environment variables (or a .env file during development)., Process settings. Only DISCORD_TOKEN is required; everything else has a default., Settings, forced_wipes(), _nth_weekday(), n-th given weekday (Mon=0) of a month. (+14 more)

### Community 1 - "raid.py"
Cohesion: 0.06
Nodes (69): Item, /help: a Components V2 menu in the user's language, with buttons that open the…, Tiny translation layer. English is the default language. Users whose Discord…, Informational commands: /author and /examples., best_line(), budget_layout(), builder_layout(), add_target() (+61 more)

### Community 2 - "test_integration.py"
Cohesion: 0.07
Nodes (53): fixture, Request, Response, bm_player(), bot(), click(), cmd(), fake_http() (+45 more)

### Community 3 - "BattleMetrics"
Cohesion: 0.09
Nodes (23): BattleMetrics, Minimal BattleMetrics API client with retries and a brake for rate limits., Authenticated GET. Retries 5xx with exponential backoff; a 429 blocks the…, True/False only with an explicit, fresh (< 5 min) observation; None in every…, Live Rust servers matching a name, most players first., Players by name (the public API cannot search by SteamID)., Resolve an exact Steam identifier; never infer identity from a name., match() (+15 more)

### Community 4 - "Store"
Cohesion: 0.06
Nodes (28): before_loop, loop, Bot with shared state: database, HTTP clients, raid data and server directory., Check every watch and ping the @wipe role only when the state changes. Safety…, RustBot, Path, profile_id(), Path (+20 more)

### Community 5 - "t"
Cohesion: 0.07
Nodes (74): Cybrancee/Pterodactyl entry point for RuxtBot., Exception, Interaction, presence_lines(), Read-only activity tools using exact player identifiers., register_activity(), presence(), sessions() (+66 more)

### Community 6 - "Catalog"
Cohesion: 0.11
Nodes (11): Counter, Catalog, normalized(), Rust crafting catalog (items and recipes) loaded from data/rust_catalog.yml.…, Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq")., Item by exact ID or alias; None when unknown or ambiguous., Items whose ID or alias contains the query (for suggestions)., Raw resources to craft `quantity`, walking recipes recursively. Batch recipes… (+3 more)

### Community 7 - "RuxtBot"
Cohesion: 0.09
Nodes (19): Deploying on Cybrancee, The right secret, Alerts, Commands, Data, Development, Players — `/who`, Raid (+11 more)

### Community 8 - "who.py"
Cohesion: 0.06
Nodes (46): AsyncClient, Accepts an ID, link or exact name; requires a single match so the wrong server…, bm_embed(), build_embeds(), check(), clip(), esc(), iso_ts() (+38 more)

### Community 10 - "RaidData"
Cohesion: 0.10
Nodes (13): MethodRow, normalized(), RaidData, rows() with the recommended method moved to the top (for pickers and…, Cheapest method by sulfur (> 0). `practical` skips siege and fire unless…, Totals for several targets (hard side). Unsupported method/target pairs are…, What a sulfur budget crafts (per explosive) and destroys (per target, cheapest…, Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq"). (+5 more)

### Community 11 - "ServerPagesView"
Cohesion: 0.16
Nodes (10): button(), OwnedView, OwnerLock, Mixin: only the user who opened a panel may use it; components disable…, Classic (embed + buttons) view with the owner lock., Embed, Page `page` (1-based) of the filtered directory., ◀️ ▶️ buttons to browse the directory without retyping the command. (+2 more)

### Community 13 - "CommandTranslator"
Cohesion: 0.14
Nodes (11): Locale, locale_str, CommandTranslator, normalize_lang(), es-ES', 'es-419', Locale.spain_spanish… -> 'es'; anything else -> 'en'., Shows command and option descriptions in Spanish to Spanish Discord clients., test_dynamic_keys_resolve(), test_fallbacks() (+3 more)

### Community 14 - "build_raid_data.py"
Cohesion: 0.47
Nodes (5): main(), Build data/raid.json from the raw source snapshots in data/sources/. Sources…, First (hard side) table only; the first matching label per explosive wins., rustclash_methods(), to_int()

## Knowledge Gaps
- **14 isolated node(s):** `The right secret`, `Raid`, `Players — `/who``, `Servers`, `Alerts` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 179 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `t()` connect `t` to `raid.py`, `Store`, `who.py`, `ServerPagesView`, `CommandTranslator`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Why does `RaidData` connect `RaidData` to `raid.py`, `Store`, `t`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `BattleMetrics` connect `BattleMetrics` to `Store`, `t`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `RaidData` (e.g. with `help_layout()` and `RustBot`) actually correct?**
  _`RaidData` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `main()` (e.g. with `Catalog` and `Settings`) actually correct?**
  _`main()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `target_layout()` (e.g. with `back()` and `RaidData`) actually correct?**
  _`target_layout()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `The right secret`, `Raid`, `Players — `/who`` to the rest of the system?**
  _14 weakly-connected nodes found - possible documentation gaps or missing edges._