# Graph Report - ruxtbot  (2026-10-03)

## Corpus Check
- 35 files · ~415,703 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 536 nodes · 1264 edges · 13 communities (12 shown, 1 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 94 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f9fb81f6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_utilities.py
- RaidData
- test_integration.py
- BattleMetrics
- Store
- t
- Catalog
- RuxtBot
- who.py
- __init__.py
- .best
- ServerPagesView
- build_raid_data.py

## God Nodes (most connected - your core abstractions)
1. `t()` - 65 edges
2. `lang_for()` - 64 edges
3. `RaidData` - 37 edges
4. `main()` - 36 edges
5. `target_layout()` - 32 edges
6. `error_embed()` - 31 edges
7. `builder_layout()` - 28 edges
8. `BattleMetrics` - 25 edges
9. `FakeInteraction` - 23 edges
10. `bot()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `handler()` --indirect_call--> `status()`  [INFERRED]
  tests/test_identity.py → rustbot/utility_commands.py
- `track()` --indirect_call--> `bot()`  [INFERRED]
  rustbot/__main__.py → tests/test_integration.py
- `presence()` --indirect_call--> `bot()`  [INFERRED]
  rustbot/activity.py → tests/test_integration.py
- `bot()` --uses--> `Settings`  [INFERRED]
  tests/test_integration.py → rustbot/config.py
- `request()` --indirect_call--> `status()`  [INFERRED]
  tests/test_presence.py → rustbot/utility_commands.py

## Import Cycles
- None detected.

## Communities (13 total, 1 thin omitted)

### Community 0 - "test_utilities.py"
Cohesion: 0.11
Nodes (22): date, datetime, Settings read from environment variables (or a .env file during development)., Process settings. Only DISCORD_TOKEN is required; everything else has a default., Settings, forced_wipes(), _nth_weekday(), n-th given weekday (Mon=0) of a month. (+14 more)

### Community 1 - "RaidData"
Cohesion: 0.05
Nodes (77): Item, best_line(), budget_layout(), builder_layout(), add_target(), clear(), pick_category(), pick_method() (+69 more)

### Community 2 - "test_integration.py"
Cohesion: 0.07
Nodes (55): fixture, Request, Response, bm_player(), bot(), click(), cmd(), fake_http() (+47 more)

### Community 3 - "BattleMetrics"
Cohesion: 0.05
Nodes (36): BattleMetrics, Minimal BattleMetrics API client with retries and a brake for rate limits., Authenticated GET. Retries 5xx with exponential backoff; a 429 blocks the…, True/False only with an explicit, fresh (< 5 min) observation; None in every…, Live Rust servers matching a name, most players first., Players by name (the public API cannot search by SteamID)., Resolve an exact Steam identifier; never infer identity from a name., Path (+28 more)

### Community 4 - "Store"
Cohesion: 0.07
Nodes (26): before_loop, Locale, locale_str, loop, CommandTranslator, Shows command and option descriptions in Spanish to Spanish Discord clients., Bot with shared state: database, HTTP clients, raid data and server directory., Check every watch and ping the @wipe role only when the state changes. Safety… (+18 more)

### Community 5 - "t"
Cohesion: 0.06
Nodes (74): Cybrancee/Pterodactyl entry point for RuxtBot., Exception, Interaction, presence_lines(), Read-only activity tools using exact player identifiers., register_activity(), presence(), sessions() (+66 more)

### Community 6 - "Catalog"
Cohesion: 0.11
Nodes (11): Counter, Catalog, normalized(), Rust crafting catalog (items and recipes) loaded from data/rust_catalog.yml.…, Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq")., Item by exact ID or alias; None when unknown or ambiguous., Items whose ID or alias contains the query (for suggestions)., Raw resources to craft `quantity`, walking recipes recursively. Batch recipes… (+3 more)

### Community 7 - "RuxtBot"
Cohesion: 0.09
Nodes (20): Deploying on Cybrancee, The right secret, Alerts, Commands, Data, Development, Players — `/who`, Raid (+12 more)

### Community 8 - "who.py"
Cohesion: 0.07
Nodes (45): AsyncClient, bm_embed(), build_embeds(), check(), clip(), esc(), iso_ts(), links() (+37 more)

### Community 10 - ".best"
Cohesion: 0.09
Nodes (13): MethodRow, normalized(), Raid math over data/raid.json (built by scripts/build_raid_data.py). Everything…, rows() with the recommended method moved to the top (for pickers and…, Cheapest method by sulfur (> 0). `practical` skips siege and fire unless…, Totals for several targets (hard side). Unsupported method/target pairs are…, What a sulfur budget crafts (per explosive) and destroys (per target, cheapest…, Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq"). (+5 more)

### Community 11 - "ServerPagesView"
Cohesion: 0.29
Nodes (6): button(), Embed, Page `page` (1-based) of the filtered directory., ◀️ ▶️ buttons to browse the directory without retyping the command., ServerPagesView, servers_page_embed()

### Community 14 - "build_raid_data.py"
Cohesion: 0.47
Nodes (5): main(), Build data/raid.json from the raw source snapshots in data/sources/. Sources…, First (hard side) table only; the first matching label per explosive wins., rustclash_methods(), to_int()

## Knowledge Gaps
- **15 isolated node(s):** `The right secret`, `Raid`, `Players — `/who``, `Servers`, `Alerts` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 180 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `t()` connect `t` to `who.py`, `RaidData`, `ServerPagesView`, `Store`?**
  _High betweenness centrality (0.132) - this node is a cross-community bridge._
- **Why does `RaidData` connect `RaidData` to `.best`, `BattleMetrics`, `Store`, `t`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `BattleMetrics` connect `BattleMetrics` to `Store`, `t`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `RaidData` (e.g. with `help_layout()` and `RustBot`) actually correct?**
  _`RaidData` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `main()` (e.g. with `Catalog` and `Settings`) actually correct?**
  _`main()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `target_layout()` (e.g. with `back()` and `RaidData`) actually correct?**
  _`target_layout()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `The right secret`, `Raid`, `Players — `/who`` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._