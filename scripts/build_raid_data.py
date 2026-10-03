"""Build data/raid.json from the raw source snapshots in data/sources/.

Sources (both fetched through a real browser because they sit behind bot checks):
  - rustly_raid.json          Rustly API v1 /raid/ (datamined + measured in game, hard and soft sides)
  - rustclash_durability.json RustClash item durability tables (targets Rustly does not cover)

Rustly is preferred whenever a target exists in both. Siege methods (catapult, mortar, ballista,
ram, MLRS, 40mm HE, cannon) are not in Rustly, so they are taken from RustClash or the legacy
catalog. Re-run after a wipe/patch:  python scripts/build_raid_data.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'data' / 'sources'
ICON = 'https://wiki.rustclash.com/img/items180/{}.png'

# Explosive key -> (display name, icon shortName, group). Group drives the "cheapest" pick:
# only "explosive" is recommended by default; "fire" and "siege" are shown but tagged.
EXPLOSIVES = {
    'explosive556': ('Explosive 5.56 Rifle Ammo', 'ammo.rifle.explosive', 'explosive'),
    'c4': ('Timed Explosive Charge (C4)', 'explosive.timed', 'explosive'),
    'rocket': ('Rocket', 'ammo.rocket.basic', 'explosive'),
    'satchel': ('Satchel Charge', 'explosive.satchel', 'explosive'),
    'propane_bomb': ('Propane Explosive Bomb', 'catapult.ammo.explosive', 'explosive'),
    'hv_rocket': ('High Velocity Rocket', 'ammo.rocket.hv', 'explosive'),
    'beancan': ('Beancan Grenade', 'grenade.beancan', 'explosive'),
    'f1': ('F1 Grenade', 'grenade.f1', 'explosive'),
    'incendiary_rocket': ('Incendiary Rocket', 'ammo.rocket.fire', 'fire'),
    'molotov': ('Molotov Cocktail', 'grenade.molotov', 'fire'),
    'fire_arrow': ('Fire Arrow', 'arrow.fire', 'fire'),
    'catapult_propane': ('Catapult · Propane Bomb', 'catapult.ammo.explosive', 'siege'),
    'mortar': ('Mortar Shell', 'ammo.mortar.basic', 'siege'),
    'mlrs': ('MLRS Rocket', 'ammo.rocket.mlrs', 'siege'),
    'he_grenade': ('40mm HE Grenade', 'ammo.grenadelauncher.he', 'siege'),
    'hammerhead': ('Ballista · Hammerhead Bolt', 'ballista.bolt.hammerhead', 'siege'),
    'ram': ('Battering Ram (hits)', 'batteringram', 'siege'),
    'cannonball': ('Cannon · Cannonball', 'cannonball', 'siege'),
}

# Per-unit raw cost for methods Rustly does not price (from the Facepunch recipes in rust_catalog.yml).
# None = no craft recipe verified, shown as "unknown cost" (never as free).
SIEGE_COST = {
    'catapult_propane': {'sulfur': 900, 'charcoal': 1350, 'metalFragments': 0},
    'mortar': {'sulfur': 300, 'charcoal': 450, 'metalFragments': 0},
    'cannonball': {'sulfur': 15, 'charcoal': 22.5, 'metalFragments': 0},
    'hammerhead': {'sulfur': 0, 'charcoal': 0, 'metalFragments': 0},
    'mlrs': None, 'ram': None, 'he_grenade': None,
}

# RustClash "tool" column -> explosive key. Planted grenades ("Stuck") win over thrown ones.
RUSTCLASH_TOOLS = [
    ('Assault RifleExplosive 5.56 Rifle Ammo', 'explosive556'),
    ('Timed Explosive Charge', 'c4'),
    ('Rocket', 'rocket'),
    ('Satchel Charge', 'satchel'),
    ('Propane Explosive BombPlanting', 'propane_bomb'),
    ('High Velocity Rocket', 'hv_rocket'),
    ('Beancan GrenadeStuck (right click)', 'beancan'),
    ('Beancan Grenade', 'beancan'),
    ('F1 GrenadeStuck (right click)', 'f1'),
    ('F1 Grenade', 'f1'),
    ('Incendiary Rocket', 'incendiary_rocket'),
    ('Molotov Cocktail', 'molotov'),
    ('CatapultPropane Explosive Bomb', 'catapult_propane'),
    ('Mortar Shell', 'mortar'),
    ('MLRS Rocket', 'mlrs'),
    ('40mm HE Grenade', 'he_grenade'),
    ('BallistaHammerhead Bolt', 'hammerhead'),
    ('Battering Ram', 'ram'),
    ('Cannonball', 'cannonball'),
]

# Target key -> (category, icon shortName, extra aliases in English/Spanish).
TARGETS = {
    # Doors
    'wooden-door': ('doors', 'door.hinged.wood', ['wood door', 'wooddoor', 'puerta madera']),
    'sheet-metal-door': ('doors', 'door.hinged.metal', ['sheet door', 'metal door', 'puerta metal']),
    'garage-door': ('doors', 'wall.frame.garagedoor', ['garage', 'garaje', 'puerta garaje']),
    'armored-door': ('doors', 'door.hinged.toptier', ['hq door', 'hqdoor', 'puerta hq', 'puerta blindada']),
    'wood-double-door': ('doors', 'door.double.hinged.wood', ['wood double door', 'puerta doble madera']),
    'sheet-metal-double-door': ('doors', 'door.double.hinged.metal', ['metal double door', 'puerta doble metal']),
    'armored-double-door': ('doors', 'door.double.hinged.toptier', ['hq double door', 'puerta doble blindada']),
    # Walls
    'wooden-wall': ('walls', 'wood', ['wood wall', 'muro madera', 'pared madera']),
    'stone-wall': ('walls', 'stones', ['muro piedra', 'pared piedra']),
    'sheet-metal-wall': ('walls', 'sheetmetal', ['metal wall', 'muro metal', 'pared metal']),
    'armored-wall': ('walls', 'metal.refined', ['hq wall', 'hqwall', 'muro blindado', 'pared blindada']),
    'high-external-wooden-wall': ('walls', 'wall.external.high', ['high wood wall', 'muro externo madera']),
    'high-external-stone-wall': ('walls', 'wall.external.high.stone', ['high stone wall', 'muro externo piedra']),
    'high-external-wooden-gate': ('walls', 'gates.external.high.wood', ['wood gate', 'puerta externa madera']),
    'high-external-stone-gate': ('walls', 'gates.external.high.stone', ['stone gate', 'puerta externa piedra']),
    # Floors and hatches
    'wooden-floor': ('floors', 'wood', ['wood floor', 'piso madera', 'suelo madera']),
    'stone-floor': ('floors', 'stones', ['piso piedra', 'suelo piedra']),
    'sheet-metal-floor': ('floors', 'sheetmetal', ['metal floor', 'piso metal']),
    'armored-floor': ('floors', 'metal.refined', ['hq floor', 'piso blindado']),
    'ladder-hatch': ('floors', 'floor.ladder.hatch', ['hatch', 'escotilla']),
    'triangle-ladder-hatch': ('floors', 'floor.triangle.ladder.hatch', ['triangle hatch', 'escotilla triangular']),
    'armored-ladder-hatch': ('floors', 'floor.ladder.hatch.toptier', ['hq hatch', 'escotilla blindada']),
    'armored-triangle-ladder-hatch': ('floors', 'floor.triangle.ladder.hatch.toptier', ['hq triangle hatch']),
    'floor-grill': ('floors', 'floor.grill', ['grill', 'rejilla']),
    # Windows, bars and barricades
    'reinforced-glass-window': ('windows', 'wall.window.glass.reinforced', ['reinforced window', 'ventana reforzada']),
    'strengthened-glass-window': ('windows', 'wall.window.bars.toptier', ['glass window', 'ventana cristal']),
    'metal-window-bars': ('windows', 'wall.window.bars.metal', ['window bars', 'barrotes']),
    'metal-horizontal-embrasure': ('windows', 'shutter.metal.embrasure.a', ['embrasure', 'tronera']),
    'metal-vertical-embrasure': ('windows', 'shutter.metal.embrasure.b', ['vertical embrasure', 'tronera vertical']),
    'metal-shop-front': ('windows', 'wall.frame.shopfront.metal', ['shop front', 'mostrador']),
    'prison-cell-gate': ('windows', 'wall.frame.cell.gate', ['cell gate', 'reja celda']),
    'prison-cell-wall': ('windows', 'wall.frame.cell', ['cell wall', 'pared celda']),
    'chainlink-fence': ('windows', 'wall.frame.fence', ['fence', 'valla']),
    'chainlink-fence-gate': ('windows', 'wall.frame.fence.gate', ['fence gate', 'puerta valla']),
    'metal-barricade': ('windows', 'barricade.metal', ['barricada metal']),
    'concrete-barricade': ('windows', 'barricade.concrete', ['barricada concreto']),
    # Deployables
    'tool-cupboard': ('deployables', 'cupboard.tool', ['tc', 'cupboard', 'armario']),
    'auto-turret': ('deployables', 'autoturret', ['turret', 'torreta']),
    'sam-site': ('deployables', 'samsite', ['sam', 'antiaereo']),
    'shotgun-trap': ('deployables', 'guntrap', ['gun trap', 'trampa escopeta']),
    'flame-turret': ('deployables', 'flameturret', ['lanzallamas']),
    'tesla-coil': ('deployables', 'electric.teslacoil', ['tesla', 'bobina tesla']),
    'large-wood-box': ('deployables', 'box.wooden.large', ['box', 'caja', 'caja grande']),
    'vending-machine': ('deployables', 'vending.machine', ['vending', 'maquina expendedora']),
    'large-furnace': ('deployables', 'furnace.large', ['furnace', 'horno grande']),
    'workbench-level-3': ('deployables', 'workbench3', ['t3', 'workbench', 'banco de trabajo 3']),
    # Vehicles (no item icon: the UI falls back to the cheapest explosive's icon)
    'minicopter': ('vehicles', None, ['mini', 'minicoptero']),
    'scrap-transport-helicopter': ('vehicles', None, ['scrap heli', 'heli', 'helicoptero']),
    'attack-helicopter': ('vehicles', None, ['attack heli', 'helicoptero ataque']),
    'hot-air-balloon': ('vehicles', 'hab.armor', ['hab', 'balloon', 'globo']),
    'rhib': ('vehicles', None, ['boat', 'lancha']),
    'motor-rowboat': ('vehicles', None, ['rowboat', 'bote']),
    'pt-boat': ('vehicles', None, ['pt', 'patrol boat']),
    'tugboat': ('vehicles', None, ['tug', 'remolcador']),
    'solo-submarine': ('vehicles', None, ['solo sub', 'submarino']),
    'duo-submarine': ('vehicles', None, ['duo sub', 'submarino doble']),
    'bradley-apc': ('vehicles', None, ['bradley', 'tanque']),
}

# Legacy siege data (from the previous RustClash-based catalog) for targets Rustly prices without siege.
LEGACY_KEYS = {'wooden-door': 'wood-door', 'sheet-metal-door': 'sheet-door', 'garage-door': 'garage-door',
               'armored-door': 'hq-door', 'wooden-wall': 'wood-wall', 'stone-wall': 'stone-wall',
               'sheet-metal-wall': 'sheet-wall', 'armored-wall': 'hq-wall'}
LEGACY_METHODS = {'catapult-propane': 'catapult_propane', 'mortar': 'mortar', 'mlrs': 'mlrs', 'he-grenade': 'he_grenade',
                  'hammerhead': 'hammerhead', 'ram': 'ram', 'cannonball': 'cannonball'}


def to_int(text: str) -> int | None:
    digits = re.sub(r'[^0-9]', '', text or '')
    return int(digits) if digits else None


def rustclash_methods(rows: list[dict]) -> dict[str, int]:
    """First (hard side) table only; the first matching label per explosive wins."""
    found: dict[str, int] = {}
    for label, key in RUSTCLASH_TOOLS:
        if key in found:
            continue
        for row in rows:
            if row['t'] == 0 and row['cells'][1] == label and (qty := to_int(row['cells'][3])):
                found[key] = qty
                break
    return found


def main() -> None:
    import yaml
    rustly = json.loads((SOURCES / 'rustly_raid.json').read_text(encoding='utf-8'))
    rustclash = json.loads((SOURCES / 'rustclash_durability.json').read_text(encoding='utf-8'))
    legacy = yaml.safe_load((ROOT / 'data' / 'rust_catalog.yml').read_text(encoding='utf-8'))['targets']

    costs: dict[str, dict | None] = dict(SIEGE_COST)
    targets: dict[str, dict] = {}

    for t in rustly['targets']:
        key = t['slug']
        category, icon, aliases = TARGETS[key]
        sides = {}
        for side in ('hard', 'soft'):
            data = t.get(side)
            if not data:
                continue
            methods = {}
            for e in data['explosives'] + data.get('fireAndMelee', []):
                methods[e['slug']] = e['amount']
                if 'sulfur' in e and e['slug'] not in costs:
                    costs[e['slug']] = {k: round(e[k] / e['amount'], 3) for k in ('sulfur', 'charcoal', 'metalFragments')}
                elif e['slug'] not in costs:
                    costs[e['slug']] = {'sulfur': 0, 'charcoal': 0, 'metalFragments': 0}
            sides[side] = methods
        if (old := legacy.get(LEGACY_KEYS.get(key, ''))):
            for old_key, new_key in LEGACY_METHODS.items():
                if old_key in old.get('methods', {}):
                    sides['hard'].setdefault(new_key, old['methods'][old_key]['count'])
        targets[key] = {'name': t['name'], 'category': category, 'hp': t['hp'], 'icon': icon, 'aliases': aliases,
                        'source': 'rustly', 'url': t['hard']['target']['url'], **sides}

    for key, page in rustclash.items():
        if key in targets or key not in TARGETS or not page.get('rows'):
            continue
        category, icon, aliases = TARGETS[key]
        icon_from_page = (page.get('img') or '').rsplit('/', 1)[-1].removesuffix('.png') or None
        targets[key] = {'name': page['name'].replace('Metal horizontal', 'Metal Horizontal').replace('Metal Vertical embrasure', 'Metal Vertical Embrasure'),
                        'category': category, 'hp': page['hp'], 'icon': icon_from_page or icon, 'aliases': aliases,
                        'source': 'rustclash', 'url': f'https://wiki.rustclash.com/item/{key}', 'hard': rustclash_methods(page['rows'])}

    explosives = {k: {'name': n, 'icon': ICON.format(s), 'group': g, 'cost': costs.get(k)} for k, (n, s, g) in EXPLOSIVES.items()}
    out = {
        'meta': {
            'version': 'Raid data 2026-10-02',
            'rustly': {'url': 'https://rustly.com/raid/', 'note': 'Rustly API v1, datamine + measured in game', 'gameVersion': '2633.288.1'},
            'rustclash': {'url': 'https://wiki.rustclash.com/', 'note': 'RustClash durability tables, hard side'},
            'icons': 'https://wiki.rustclash.com/img/items180/',
        },
        'explosives': explosives,
        'targets': {k: {**v, 'icon': ICON.format(v['icon']) if v['icon'] else None} for k, v in targets.items()},
    }
    (ROOT / 'data' / 'raid.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    # Keep the committed RustClash snapshot small: only the rows the bot actually uses.
    labels = {label for label, _ in RUSTCLASH_TOOLS}
    slim = {k: {**v, 'rows': [r for r in v.get('rows', []) if r['t'] == 0 and r['cells'][1] in labels]} for k, v in rustclash.items()}
    (SOURCES / 'rustclash_durability.json').write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"{len(out['targets'])} targets, {len(explosives)} explosives")


if __name__ == '__main__':
    main()
