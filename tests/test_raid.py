import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from rustbot.raid import budget_layout, builder_layout, category_layout, compare_layout, compare_lines, home_layout, target_layout
from rustbot.raid_data import BEST, RaidData
from rustbot.ui import OwnedLayout, fmt_num, progress_bar

ROOT = Path(__file__).parents[1]
DATA = RaidData.load(ROOT / 'data' / 'raid.json')


def texts(view) -> str:
    """All visible text of a layout, joined."""
    return '\n'.join(i.content for i in view.walk_children() if isinstance(getattr(i, 'content', None), str))


def test_helpers_format_cleanly():
    assert progress_bar(0) == '░' * 10 and progress_bar(100) == '█' * 10 and progress_bar(55) == '█' * 6 + '░' * 4
    assert fmt_num(1000.0) == '1,000' and fmt_num(120.5) == '120.5'


def test_data_covers_many_targets_with_pictures():
    assert len(DATA.targets) >= 55
    assert set(DATA.categories()) == {'doors', 'walls', 'floors', 'windows', 'deployables', 'vehicles'}
    for key, target in DATA.targets.items():
        assert target['hp'] > 0 and target['hard'], key
        assert DATA.icon(key).startswith('https://wiki.rustclash.com/img/items180/')
    assert all(e['icon'].endswith('.png') for e in DATA.explosives.values())


def test_rustly_measured_values():
    # Values measured in game by Rustly (game build 2633.288.1).
    assert DATA.amount('armored-door', 'c4') == 3 and DATA.amount('armored-door', 'rocket') == 5
    assert DATA.amount('armored-door', 'explosive556') == 250
    assert DATA.cost('c4', 3)['sulfur'] == 6600
    assert DATA.cost('explosive556', 250)['sulfur'] == 6250
    assert DATA.sides('stone-wall') == ['hard', 'soft'] and DATA.sides('armored-door') == ['hard']


def test_find_accepts_names_and_spanish_aliases():
    assert DATA.find('puerta hq') == 'armored-door'
    assert DATA.find('Armored Door') == 'armored-door'
    assert DATA.find('muro piedra') == 'stone-wall'
    assert DATA.find('tc') == 'tool-cupboard'
    assert DATA.find('does not exist') is None
    assert 'high-external-stone-wall' in DATA.search('high ext')


def test_best_skips_siege_and_fire_and_is_cheapest():
    for key in DATA.targets:
        best = DATA.best(key)
        assert best, key
        practical = [r.sulfur for r in DATA.rows(key) if r.sulfur and r.group == 'explosive']
        if practical:
            assert DATA.explosives[best[0]]['group'] == 'explosive' and best[1] == min(practical)
    lines = compare_lines(DATA, 'en', 'armored-door')
    assert sum(line.startswith('🏆') for line in lines) == 1
    assert any('*(siege)*' in line for line in lines)
    assert 'cost not verified' in lines[-1]


def test_unknown_cost_is_never_free():
    assert DATA.cost('mlrs', 4) is None
    assert 'not free' in texts(asyncio.run(_layout(lambda: target_layout(DATA, 'en', 'armored-door', method='mlrs'))))


def test_plan_totals_and_missing_methods():
    plan = DATA.plan({'armored-door': 2, 'stone-wall': 1}, 'c4')
    units = {key: n for key, _, _, n in plan['rows']}
    assert units['armored-door'] == 6 and plan['totals']['sulfur'] == DATA.cost('c4', 6 + units['stone-wall'])['sulfur']
    # Siege-only methods are flagged, never guessed, on targets without data for them.
    plan = DATA.plan({'tool-cupboard': 1}, 'ram')
    assert plan['rows'][0][2] is None and plan['totals'].get('sulfur', 0) == 0
    best = DATA.plan({'armored-door': 1}, BEST)
    assert best['rows'][0][2] == DATA.best('armored-door')[0]


def test_budget_never_exceeds_sulfur():
    info = DATA.budget(10_000)
    for _, units, per in info['crafts']:
        assert units * per <= 10_000
    door = next(r for r in info['kills'] if r[0] == 'armored-door')
    assert door[1] * door[3] <= 10_000 < (door[1] + 1) * door[3]


async def _layout(factory):
    return factory()


def test_every_panel_fits_discord_limits_in_both_languages():
    async def run():
        for lang in ('en', 'es'):
            views = [home_layout(DATA, lang), builder_layout(DATA, lang, {}), builder_layout(DATA, lang, {k: 3 for k in DATA.targets}),
                     budget_layout(DATA, lang, 250_000)]
            views += [category_layout(DATA, lang, c) for c in DATA.categories()]
            for key in DATA.targets:
                for side in DATA.sides(key):
                    views += [target_layout(DATA, lang, key, side), compare_layout(DATA, lang, key, side)]
            for view in views:
                view.to_components()
                assert view.total_children_count <= 40
                assert len(texts(view)) <= 4000
    asyncio.run(run())


def test_target_panel_progress_and_buttons():
    async def run():
        start = target_layout(DATA, 'en', 'armored-door', method='c4')
        buttons = {b.label: b for b in start.walk_children() if getattr(b, 'label', None)}
        assert buttons['Undo'].disabled and buttons['Reset'].disabled and not buttons['Complete'].disabled
        assert '100%' in texts(start) and 'Target intact' in texts(start)
        mid = target_layout(DATA, 'es', 'armored-door', method='c4', used=2)
        assert 'Objetivo dañado' in texts(mid) and '333.3/1,000 HP' in texts(mid)
        done = target_layout(DATA, 'en', 'armored-door', method='c4', used=3)
        buttons = {b.label: b for b in done.walk_children() if getattr(b, 'label', None)}
        assert buttons['Destroyed'].disabled and not buttons['Undo'].disabled and '0%' in texts(done)
        # Walls get a side toggle; doors do not.
        wall = target_layout(DATA, 'en', 'stone-wall')
        assert any('Soft side' in (getattr(b, 'label', '') or '') for b in wall.walk_children())
    asyncio.run(run())


def test_panels_show_pictures():
    async def run():
        doors = category_layout(DATA, 'en', 'doors')
        gallery = next(i for i in doors.walk_children() if i.__class__.__name__ == 'MediaGallery')
        assert len(gallery.items) == len(DATA.in_category('doors'))
        sim = target_layout(DATA, 'en', 'armored-door')
        thumbs = [i.media.url for i in sim.walk_children() if i.__class__.__name__ == 'Thumbnail']
        assert DATA.targets['armored-door']['icon'] in thumbs and len(thumbs) == 2
    asyncio.run(run())


def test_builder_add_target_redraws_with_one_more():
    async def run():
        view = builder_layout(DATA, 'en', {}, owner_id=1)
        add = next(s for s in view.walk_children() if getattr(s, 'placeholder', '') and 'Add target' in s.placeholder)
        edited = {}

        async def edit_message(**kwargs):
            edited.update(kwargs)

        interaction = SimpleNamespace(data={'values': ['armored-door']}, message=None, user=SimpleNamespace(id=1), locale='en-US',
                                      response=SimpleNamespace(edit_message=edit_message))
        await add.callback(interaction)
        assert '1×** Armored Door' in texts(edited['view'])
    asyncio.run(run())


def test_owner_lock_blocks_other_users():
    async def run():
        view = OwnedLayout(owner_id=1)
        other = SimpleNamespace(user=SimpleNamespace(id=2), locale='es-ES', response=SimpleNamespace(send_message=AsyncMock()))
        assert await view.interaction_check(other) is False
        assert 'otra persona' in other.response.send_message.call_args.args[0]
        assert await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=1))) is True
    asyncio.run(run())


@pytest.mark.parametrize('path', ['data/raid.json', 'data/sources/rustly_raid.json', 'data/sources/rustclash_durability.json'])
def test_data_files_are_valid_json(path):
    json.loads((ROOT / path).read_text(encoding='utf-8'))
