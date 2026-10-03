import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from rustbot.catalog import Catalog
from rustbot.help import SECTIONS, HelpView, home_embed, section_embed
from rustbot.raid import (BEST, FIRE, SIEGE, RaidBuilderView, RaidProgressView, best_method, budget, budget_embed, category_embed,
                          comparison, plan_embed, plan_totals, raidable, sulfur_per_unit, target_cost)
from rustbot.ui import OwnedView, fmt_num, progress_bar

CAT = Catalog.load(str(Path(__file__).parents[1] / 'data' / 'rust_catalog.yml'))


def test_helpers_format_cleanly():
    assert progress_bar(0) == '░' * 10 and progress_bar(100) == '█' * 10 and progress_bar(55) == '█' * 6 + '░' * 4
    assert fmt_num(1000.0) == '1,000' and fmt_num(120.5) == '120.5'


def test_best_method_is_cheapest_known_cost():
    for t in raidable(CAT).values():
        method, cost = best_method(CAT, t)
        known = [c for m in t['methods'] if m not in SIEGE | FIRE and (c := target_cost(CAT, t, m))]
        assert method not in SIEGE | FIRE and cost == min(known)
    # Exactamente una línea de la comparación lleva la corona; asedio y fuego van etiquetados.
    rows = comparison(CAT, CAT.raid('hqdoor'))
    assert sum(r.startswith('🏆') for r in rows) == 1
    assert any('*(asedio)*' in r for r in rows)


def test_sulfur_per_unit_respects_batches():
    assert sulfur_per_unit(CAT, 'c4') == 2200
    assert sulfur_per_unit(CAT, 'explosive-ammo') == 25  # receta x2 → 50 azufre por lote
    assert sulfur_per_unit(CAT, 'mlrs') is None


def test_plan_totals_with_fixed_method_and_best():
    plan = plan_totals(CAT, {'hq-door': 2, 'stone-wall': 1}, 'c4')
    hq, wall = plan['rows']
    assert hq.units == 6 and wall.units == CAT.raid('stone-wall')['methods']['c4']['count']
    assert plan['sulfur'] == CAT.materials('c4', hq.units + wall.units)['sulfur']
    best = plan_totals(CAT, {'hq-door': 1}, BEST)
    assert best['rows'][0].method == best_method(CAT, CAT.raid('hqdoor'))[0]


def test_plan_flags_targets_without_that_method():
    # Los muros no admiten todos los métodos de las puertas: deben quedar marcados, no inventados.
    door_only = next(m for m in CAT.raid('wooddoor')['methods'] if m not in CAT.raid('wood-wall')['methods'])
    plan = plan_totals(CAT, {'wood-wall': 1}, door_only)
    assert plan['rows'][0].method is None and plan['sulfur'] == 0
    assert 'sin datos' in plan_embed(CAT, {'wood-wall': 1}, door_only).fields[0].value


def test_budget_never_exceeds_sulfur():
    data = budget(CAT, 10_000)
    for method, units, per in data['craftable']:
        assert units * per <= 10_000
    hq = next(r for r in data['destroyable'] if r[0] == 'hq-door')
    assert hq[1] * hq[3] <= 10_000 < (hq[1] + 1) * hq[3]
    assert len(budget_embed(CAT, 10_000)) < 6000


def test_embeds_fit_discord_limits():
    assert len(category_embed(CAT)) < 6000
    big = {k: 50 for k in raidable(CAT)}
    assert len(plan_embed(CAT, big)) < 6000
    assert all(len(section_embed(CAT, k)) < 6000 for k in SECTIONS) and len(home_embed(CAT)) < 6000


def test_progress_view_buttons_enable_by_state():
    async def run():
        t = CAT.raid('hqdoor')
        start = RaidProgressView(CAT, t, 'c4', 0)
        labels = {c.label: c for c in start.children if getattr(c, 'label', None)}
        assert labels['Deshacer'].disabled and labels['Reiniciar'].disabled and not labels['Completar'].disabled
        done = RaidProgressView(CAT, t, 'c4', 3)
        labels = {c.label: c for c in done.children if getattr(c, 'label', None)}
        assert labels['Destruido'].disabled and labels['Completar'].disabled and not labels['Deshacer'].disabled
    asyncio.run(run())


def test_builder_view_components_fit_and_update():
    async def run():
        empty = RaidBuilderView(CAT)
        assert len(empty.children) == 4  # añadir, método, vaciar, compartir (sin «quitar»)
        full = RaidBuilderView(CAT, {k: 1 for k in raidable(CAT)})
        assert len(full.children) == 5
        assert all(len(c.options) <= 25 for c in full.children if hasattr(c, 'options'))
        # Simula seleccionar «añadir» y comprueba que la vista nueva suma uno.
        edited = {}
        async def edit_message(**kwargs): edited.update(kwargs)
        interaction = SimpleNamespace(data={'values': ['hq-door']}, message=None, user=SimpleNamespace(id=1),
                                      response=SimpleNamespace(edit_message=edit_message))
        await empty._add(interaction)
        assert edited['view'].entries == {'hq-door': 1} and '1×' in edited['embed'].fields[0].value
    asyncio.run(run())


def test_owned_view_blocks_other_users():
    async def run():
        view = OwnedView(owner_id=1)
        other = SimpleNamespace(user=SimpleNamespace(id=2), response=SimpleNamespace(send_message=AsyncMock()))
        assert await view.interaction_check(other) is False
        assert other.response.send_message.call_args.kwargs['ephemeral'] is True
        assert await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=1))) is True
    asyncio.run(run())


def test_help_view_builds():
    async def run():
        view = HelpView(CAT, 1)
        select = next(c for c in view.children if hasattr(c, 'options'))
        assert len(select.options) == len(SECTIONS) + 1
    asyncio.run(run())
