"""Raid math over data/raid.json (built by scripts/build_raid_data.py).

Everything here is pure and synchronous so it is easy to unit test; the Discord UI lives in raid.py.
"""
from __future__ import annotations
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BEST = 'best'  # special method value: "cheapest common explosive per target"
CATEGORY_EMOJI = {'doors': '🚪', 'walls': '🧱', 'floors': '🪜', 'windows': '🪟', 'deployables': '🛡️', 'vehicles': '🚁'}
METHOD_EMOJI = {
    'explosive556': '🔫', 'c4': '🧨', 'rocket': '🚀', 'satchel': '🎒', 'propane_bomb': '🛢️', 'hv_rocket': '🚀',
    'beancan': '🥫', 'f1': '💣', 'incendiary_rocket': '🔥', 'molotov': '🍾', 'fire_arrow': '🏹',
    'catapult_propane': '🛢️', 'mortar': '🎯', 'mlrs': '🎆', 'he_grenade': '💥', 'hammerhead': '🏹', 'ram': '🐏',
    'cannonball': '⚫',
}
COST_KEYS = ('sulfur', 'charcoal', 'metalFragments')


def normalized(text: str) -> str:
    """Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq")."""
    return re.sub(r'[^a-z0-9]', '', text.casefold())


@dataclass(frozen=True)
class MethodRow:
    method: str
    amount: int
    cost: dict | None  # totals for `amount` units; None = unknown recipe (never "free")
    group: str         # explosive | fire | siege

    @property
    def sulfur(self) -> int | None:
        return None if self.cost is None else self.cost['sulfur']


class RaidData:
    def __init__(self, raw: dict):
        self.raw = raw
        self.targets: dict[str, dict] = raw['targets']
        self.explosives: dict[str, dict] = raw['explosives']

    @classmethod
    def load(cls, path: str | Path) -> 'RaidData':
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    @property
    def version(self) -> str:
        return self.raw['meta']['version']

    # ── Lookup ──
    def categories(self) -> list[str]:
        return [c for c in CATEGORY_EMOJI if any(t['category'] == c for t in self.targets.values())]

    def in_category(self, category: str) -> list[str]:
        return [k for k, t in self.targets.items() if t['category'] == category]

    def find(self, query: str) -> str | None:
        """Target key by exact key, name or alias (English or Spanish)."""
        q = normalized(query or '')
        if not q:
            return None
        for key, t in self.targets.items():
            if q in {normalized(key), normalized(t['name'])} | {normalized(a) for a in t.get('aliases', [])}:
                return key
        return None

    def search(self, query: str, limit: int = 25) -> list[str]:
        """Keys whose name, key or alias contains the query, for autocomplete."""
        q = normalized(query or '')
        hits = [k for k, t in self.targets.items()
                if not q or any(q in normalized(s) for s in [k, t['name'], *t.get('aliases', [])])]
        return hits[:limit]

    def sides(self, key: str) -> list[str]:
        return [s for s in ('hard', 'soft') if self.targets[key].get(s)]

    def icon(self, key: str) -> str:
        """Target icon, or the cheapest explosive's icon for things without one (vehicles)."""
        t = self.targets[key]
        if t.get('icon'):
            return t['icon']
        best = self.best(key)
        return self.explosives[best[0]]['icon'] if best else next(iter(self.explosives.values()))['icon']

    # ── Costs ──
    def cost(self, method: str, amount: int) -> dict | None:
        """Raw materials to craft `amount` units, rounded up to whole items."""
        unit = self.explosives[method]['cost']
        if unit is None:
            return None
        return {k: math.ceil(unit[k] * amount - 1e-9) for k in COST_KEYS}

    def rows(self, key: str, side: str = 'hard') -> list[MethodRow]:
        """Every method for a target: paid explosives by sulfur, then sulfur-free, then unknown cost."""
        out = []
        for method, amount in self.targets[key].get(side, {}).items():
            out.append(MethodRow(method, amount, self.cost(method, amount), self.explosives[method]['group']))
        return sorted(out, key=lambda r: (r.cost is None, r.sulfur == 0, r.sulfur or 0, r.amount))

    def best(self, key: str, side: str = 'hard', practical: bool = True) -> tuple[str, int] | None:
        """Cheapest method by sulfur (> 0). `practical` skips siege and fire unless nothing else works."""
        rows = [r for r in self.rows(key, side) if r.sulfur and (not practical or r.group == 'explosive')]
        if not rows and practical:
            return self.best(key, side, practical=False)
        return (rows[0].method, rows[0].sulfur) if rows else None

    def amount(self, key: str, method: str, side: str = 'hard') -> int | None:
        return self.targets[key].get(side, {}).get(method)

    def plan(self, entries: dict[str, int], method: str = BEST) -> dict:
        """Totals for several targets (hard side). Unsupported method/target pairs are flagged, never guessed."""
        rows, units = [], Counter()
        for key, qty in entries.items():
            chosen = (self.best(key) or (None,))[0] if method == BEST else method
            amount = self.amount(key, chosen) if chosen else None
            if not amount:
                rows.append((key, qty, None, 0))
                continue
            units[chosen] += amount * qty
            rows.append((key, qty, chosen, amount * qty))
        totals, unknown = Counter(), []
        for m, n in units.items():
            cost = self.cost(m, n)
            if cost is None:
                unknown.append(m)
            else:
                totals.update(cost)
        return {'rows': rows, 'units': units, 'totals': totals, 'unknown': unknown}

    def budget(self, sulfur: int) -> dict:
        """What a sulfur budget crafts (per explosive) and destroys (per target, cheapest method)."""
        crafts = sorted(((m, int(sulfur // e['cost']['sulfur']), e['cost']['sulfur'])
                         for m, e in self.explosives.items() if e['cost'] and e['cost']['sulfur'] and e['group'] == 'explosive'),
                        key=lambda r: r[2])
        kills = [(k, sulfur // b[1], b[0], b[1]) for k in self.targets if (b := self.best(k))]
        return {'crafts': crafts, 'kills': kills}
