from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import math
import yaml

def normalized(value: str) -> str:
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
        q = normalized(query)
        matches = [i for i in self.raw["items"].values() if q == normalized(i["id"]) or q in [normalized(x) for x in i.get("aliases", [])]]
        return matches[0] if len(matches) == 1 else None
    def matches(self, query: str) -> list[dict]:
        q = normalized(query)
        return [i for i in self.raw["items"].values() if q in normalized(i["id"]) or any(q in normalized(a) for a in i.get("aliases", []))]
    def materials(self, item_id: str, quantity: int = 1) -> Counter:
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
    def raid(self, target_id: str) -> dict | None:
        q = normalized(target_id)
        for key, target in self.raw["targets"].items():
            if q == normalized(key) or q in [normalized(x) for x in target.get("aliases", [])]:
                return target
        return None
