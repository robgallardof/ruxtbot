# Graph Report - ruxtbot  (2026-10-03)

## Corpus Check
- 36 files · ~416,323 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 549 nodes · 1301 edges · 15 communities (13 shown, 1 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 101 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a9534943`
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
- .__init__
- build_raid_data.py

## God Nodes (most connected - your core abstractions)
1. `t()` - 68 edges
2. `lang_for()` - 64 edges
3. `main()` - 37 edges
4. `RaidData` - 37 edges
5. `target_layout()` - 32 edges
6. `error_embed()` - 31 edges
7. `builder_layout()` - 28 edges
8. `BattleMetrics` - 25 edges
9. `FakeInteraction` - 24 edges
10. `bot()` - 23 edges

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

## Communities (15 total, 1 thin omitted)

### Community 0 - "test_utilities.py"
Cohesion: 0.11
Nodes (22): date, datetime, Settings read from environment variables (or a .env file during development)., Process settings. Only DISCORD_TOKEN is required; everything else has a default., Settings, forced_wipes(), _nth_weekday(), n-th given weekday (Mon=0) of a month. (+14 more)

### Community 1 - "RaidData"
Cohesion: 0.05
Nodes (77): Item, help_layout(), open_calc(), open_planner(), /help: a Components V2 menu in the user's language, with buttons that open the…, best_line(), budget_layout(), builder_layout() (+69 more)

### Community 2 - "test_integration.py"
Cohesion: 0.07
Nodes (57): fixture, Request, Response, bm_player(), bot(), click(), cmd(), fake_http() (+49 more)

### Community 3 - "BattleMetrics"
Cohesion: 0.05
Nodes (36): BattleMetrics, Minimal BattleMetrics API client with retries and a brake for rate limits., Authenticated GET. Retries 5xx with exponential backoff; a 429 blocks the…, True/False only with an explicit, fresh (< 5 min) observation; None in every…, Live Rust servers matching a name, most players first., Players by name (the public API cannot search by SteamID)., Resolve an exact Steam identifier; never infer identity from a name., Path (+28 more)

### Community 4 - "Store"
Cohesion: 0.07
Nodes (26): before_loop, Locale, locale_str, loop, CommandTranslator, Shows command and option descriptions in Spanish to Spanish Discord clients., Bot with shared state: database, HTTP clients, raid data and server directory., Check every watch and ping the @wipe role only when the state changes. Safety… (+18 more)

### Community 5 - "t"
Cohesion: 0.06
Nodes (82): Cybrancee/Pterodactyl entry point for RuxtBot., Exception, Interaction, presence_lines(), Read-only activity tools using exact player identifiers., register_activity(), presence(), sessions() (+74 more)

### Community 6 - "Catalog"
Cohesion: 0.11
Nodes (11): Counter, Catalog, normalized(), Rust crafting catalog (items and recipes) loaded from data/rust_catalog.yml.…, Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq")., Item by exact ID or alias; None when unknown or ambiguous., Items whose ID or alias contains the query (for suggestions)., Raw resources to craft `quantity`, walking recipes recursively. Batch recipes… (+3 more)

### Community 7 - "RuxtBot"
Cohesion: 0.08
Nodes (21): Deploying on Cybrancee, The right secret, Alerts, Commands, Data, Development, Guided tracking panel, Players — `/who` (+13 more)

### Community 8 - "who.py"
Cohesion: 0.07
Nodes (44): AsyncClient, bm_embed(), build_embeds(), check(), clip(), esc(), iso_ts(), links() (+36 more)

### Community 10 - ".best"
Cohesion: 0.15
Nodes (8): MethodRow, rows() with the recommended method moved to the top (for pickers and…, Cheapest method by sulfur (> 0). `practical` skips siege and fire unless…, Totals for several targets (hard side). Unsupported method/target pairs are…, What a sulfur budget crafts (per explosive) and destroys (per target, cheapest…, Target icon, or the cheapest explosive's icon for things without one (vehicles)., Raw materials to craft `amount` units, rounded up to whole items., Every method for a target: paid explosives by sulfur, then sulfur-free, then…

### Community 11 - "ServerPagesView"
Cohesion: 0.29
Nodes (5): Embed, Page `page` (1-based) of the filtered directory., ◀️ ▶️ buttons to browse the directory without retyping the command., ServerPagesView, servers_page_embed()

### Community 12 - ".__init__"
Cohesion: 0.43
Nodes (5): callback(), add(), refresh_list(), remove(), TrackModal

### Community 14 - "build_raid_data.py"
Cohesion: 0.47
Nodes (5): main(), Build data/raid.json from the raw source snapshots in data/sources/. Sources…, First (hard side) table only; the first matching label per explosive wins., rustclash_methods(), to_int()

## Knowledge Gaps
- **16 isolated node(s):** `The right secret`, `Raid`, `Players — `/who``, `Servers`, `Alerts` (+11 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 183 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `t()` connect `t` to `RaidData`, `Store`, `who.py`, `ServerPagesView`, `.__init__`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Why does `RaidData` connect `RaidData` to `.best`, `BattleMetrics`, `Store`, `t`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `BattleMetrics` connect `BattleMetrics` to `Store`, `t`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `main()` (e.g. with `Catalog` and `Settings`) actually correct?**
  _`main()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `RaidData` (e.g. with `help_layout()` and `RustBot`) actually correct?**
  _`RaidData` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `target_layout()` (e.g. with `back()` and `RaidData`) actually correct?**
  _`target_layout()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `The right secret`, `Raid`, `Players — `/who`` to the rest of the system?**
  _16 weakly-connected nodes found - possible documentation gaps or missing edges._