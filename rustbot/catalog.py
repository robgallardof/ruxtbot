"""Rust crafting catalog (items and recipes) loaded from data/rust_catalog.yml.

Raid targets now live in data/raid.json (see raid_data.py); the legacy `targets`
section is only read by scripts/build_raid_data.py for siege methods.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import math
import yaml

ICON_URL = 'https://wiki.rustclash.com/img/items180/{}.png'
# Catalog item id -> in-game shortName, used to show the item picture.
ITEM_ICONS = {
    'sulfur': 'sulfur', 'charcoal': 'charcoal', 'low-grade-fuel': 'lowgradefuel', 'metal-fragments': 'metal.fragments',
    'metal-pipe': 'metalpipe', 'cloth': 'cloth', 'tech-trash': 'techparts', 'gunpowder': 'gunpowder', 'explosives': 'explosives',
    'rocket': 'ammo.rocket.basic', 'c4': 'explosive.timed', 'satchel': 'explosive.satchel', 'explosive-ammo': 'ammo.rifle.explosive',
    'rope': 'rope', 'small-stash': 'stash.small', 'beancan': 'grenade.beancan', 'f1': 'grenade.f1', 'hv-rocket': 'ammo.rocket.hv',
    'molotov': 'grenade.molotov', 'mlrs': 'ammo.rocket.mlrs', 'hammerhead': 'ballista.bolt.hammerhead', 'ram': 'batteringram',
    'propane': 'catapult.ammo.explosive', 'catapult-propane': 'catapult.ammo.explosive', 'he-grenade': 'ammo.grenadelauncher.he',
    'cannonball': 'cannonball', 'mortar': 'ammo.mortar.basic', 'incendiary-rocket': 'ammo.rocket.fire',
    'handmade-shell': 'ammo.handmade.shell', 'empty-propane-tank': 'propanetank', 'high-quality-metal': 'metal.refined',
}

def normalized(value: str) -> str:
    """Search key: lowercase letters and digits only ("Puerta HQ" -> "puertahq")."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())

@dataclass
class Catalog:
    raw: dict
    @classmethod
    def load(cls, path: str) -> "Catalog":
        with Path(path).open(encoding="utf-8") as f: return cls(yaml.safe_load(f))
    @property
    def version(self) -> str: return self.raw["meta"]["version"]
    def item(self, query: str) -> dict | None:
        """Item by exact ID or alias; None when unknown or ambiguous."""
        q = normalized(query)
        matches = [i for i in self.raw["items"].values() if q == normalized(i["id"]) or q in [normalized(x) for x in i.get("aliases", [])]]
        return matches[0] if len(matches) == 1 else None
    def matches(self, query: str) -> list[dict]:
        """Items whose ID or alias contains the query (for suggestions)."""
        q = normalized(query)
        return [i for i in self.raw["items"].values() if q in normalized(i["id"]) or any(q in normalized(a) for a in i.get("aliases", []))]
    def materials(self, item_id: str, quantity: int = 1) -> Counter:
        """Raw resources to craft `quantity`, walking recipes recursively.

        Batch recipes (`yield`) round up: 63 rounds cost the same as 64.
        """
        item = self.raw["items"][item_id]
        out = Counter()
        for material, amount in item.get("recipe", {}).items():
            count = amount * math.ceil(quantity / item.get("yield", 1))
            if material in self.raw["items"] and self.raw["items"][material].get("recipe"):
                out += self.materials(material, count)
            else: out[material] += count
        return out
    def intermediates(self, item_id: str, quantity: int = 1) -> Counter:
        """All craftable recipe inputs, accumulated across recursive recipes."""
        out = Counter()
        item = self.raw["items"][item_id]
        for material, amount in item.get("recipe", {}).items():
            count = amount * math.ceil(quantity / item.get("yield", 1))
            if material in self.raw["items"] and self.raw["items"][material].get("recipe"):
                out[material] += count
                out += self.intermediates(material, count)
        return out
    def icon(self, item_id: str) -> str | None:
        """Picture URL for an item, when its shortName is known."""
        short = ITEM_ICONS.get(item_id)
        return ICON_URL.format(short) if short else None
    def raid(self, target_id: str) -> dict | None:
        """Legacy raid target by key or alias (English or Spanish)."""
        q = normalized(target_id)
        for key, target in self.raw["targets"].items():
            if q == normalized(key) or q in [normalized(x) for x in target.get("aliases", [])]:
                return target
        return None
