# Graph Report - ruxtbot  (2026-10-02)

## Corpus Check
- 20 files · ~376,134 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 203 nodes · 378 edges · 11 communities (9 shown, 2 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 30 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- test_utilities.py
- .__init__
- RustBot
- BattleMetrics
- Store
- __main__.py
- Catalog
- RuxtBot
- HelpView
- __init__.py
- register_utilities

## God Nodes (most connected - your core abstractions)
1. `main()` - 22 edges
2. `register_utilities()` - 19 edges
3. `Store` - 18 edges
4. `BattleMetrics` - 17 edges
5. `RustBot` - 13 edges
6. `raid_embed()` - 13 edges
7. `embed()` - 12 edges
8. `Catalog` - 12 edges
9. `RaidProgressView` - 11 edges
10. `ServerDirectory` - 11 edges

## Surprising Connections (you probably didn't know these)
- `test_poll_transition_and_delivery()` --uses--> `RustBot`  [INFERRED]
  tests/test_poll.py → rustbot/__main__.py
- `request()` --indirect_call--> `status()`  [INFERRED]
  tests/test_presence.py → rustbot/utility_commands.py
- `test_health_and_bar_describe_remaining_health()` --calls--> `raid_embed()`  [EXTRACTED]
  tests/test_raid_ui.py → rustbot/__main__.py
- `test_unknown_cost_never_claims_free()` --calls--> `raid_embed()`  [EXTRACTED]
  tests/test_raid_ui.py → rustbot/__main__.py
- `test_only_explicit_fresh_presence()` --uses--> `BattleMetrics`  [INFERRED]
  tests/test_presence.py → rustbot/battlemetrics.py

## Import Cycles
- None detected.

## Communities (11 total, 2 thin omitted)

### Community 0 - "test_utilities.py"
Cohesion: 0.18
Nodes (14): Settings, comparison(), execute(), run(), test_admin_commands_reject_dms(), test_alert_toggle_preserves_channel_interval_and_watches(), test_all_commands_register_and_serialize(), case() (+6 more)

### Community 1 - ".__init__"
Cohesion: 0.09
Nodes (17): CompareMethodsButton, CompleteRaidButton, DetonateButton, raid_embed(), RaidBackButton, RaidBackButtonView, RaidCategorySelect, RaidMethodSelect (+9 more)

### Community 2 - "RustBot"
Cohesion: 0.14
Nodes (6): before_loop, loop, Path, RustBot, ServerDirectory, test_named_servers_and_profile_input()

### Community 3 - "BattleMetrics"
Cohesion: 0.14
Nodes (8): BattleMetrics, parametrize, test_only_explicit_fresh_presence(), run(), request(), test_rate_limit_stops_following_requests(), run(), test_rustwho_uses_only_the_requested_public_profile()

### Community 4 - "Store"
Cohesion: 0.13
Nodes (11): Store, transition(), valid_steamid64(), Watch, parametrize, test_poll_transition_and_delivery(), test_readding_does_not_erase_baseline(), test_unknown_is_never_a_disconnect() (+3 more)

### Community 5 - "__main__.py"
Cohesion: 0.15
Nodes (18): Cybrancee/Pterodactyl entry point for RuxtBot., embed(), main(), craft(), help(), item(), player(), raid() (+10 more)

### Community 6 - "Catalog"
Cohesion: 0.20
Nodes (4): Counter, Catalog, normalized(), All craftable recipe inputs, accumulated across recursive recipes.

### Community 7 - "RuxtBot"
Cohesion: 0.12
Nodes (13): Despliegue en Cybrancee, Secretos correctos, Comandos, Comandos adicionales, Conectar Discord, Datos y límites, Desarrollo, Instalación en Fedora (+5 more)

### Community 10 - "register_utilities"
Cohesion: 0.16
Nodes (7): register_utilities(), guild_watches(), pause_alerts(), raid_compare(), resume_alerts(), status(), toggle()

## Knowledge Gaps
- **9 isolated node(s):** `Secretos correctos`, `Instalación en Fedora`, `Conectar Discord`, `Comandos`, `Datos y límites` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 59 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BattleMetrics` connect `BattleMetrics` to `RustBot`, `Store`, `__main__.py`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Why does `register_utilities()` connect `register_utilities` to `__main__.py`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `Store` connect `Store` to `RustBot`, `__main__.py`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `main()` (e.g. with `Catalog` and `Settings`) actually correct?**
  _`main()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `register_utilities()` (e.g. with `methods()` and `servers()`) actually correct?**
  _`register_utilities()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Store` (e.g. with `RustBot` and `test_poll_transition_and_delivery()`) actually correct?**
  _`Store` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `BattleMetrics` (e.g. with `RustBot` and `test_only_explicit_fresh_presence()`) actually correct?**
  _`BattleMetrics` has 2 INFERRED edges - model-reasoned connections that need verification._