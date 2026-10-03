import asyncio
from pathlib import Path
from rustbot.catalog import Catalog
from rustbot.__main__ import raid_embed, RaidProgressView

CAT=Catalog.load(str(Path(__file__).parents[1]/'data'/'rust_catalog.yml'))

def test_health_and_bar_describe_remaining_health():
    t=CAT.raid('hqdoor')
    assert t['hp']==1000
    assert '100% de vida' in raid_embed(CAT,t,'c4',0).description
    assert '120.000/1,000' in raid_embed(CAT,t,'c4',2).description
    final=raid_embed(CAT,t,'c4',3)
    assert '0.000/1,000' in final.description and '0% de vida' in final.description
    assert '░'*10 in final.description
    assert 'Reinicia' in final.fields[2].value
    assert '\\n' not in final.description

def test_all_catalog_damage_counts_destroy_only_on_last_unit():
    for t in CAT.raw['targets'].values():
        for m in t.get('methods',{}).values():
            assert (m['count']-1)*m['damage'] < t['hp'] <= m['count']*m['damage']

def test_all_views_fit_discord_limits():
    async def run():
        for t in CAT.raw['targets'].values():
            for method in t.get('methods',{}):
                view=RaidProgressView(CAT,t,method)
                assert len(view.children[0].options)<=25
                assert len(raid_embed(CAT,t,method))<6000
    asyncio.run(run())

def test_unknown_cost_never_claims_free():
    assert 'no significa gratis' in raid_embed(CAT,CAT.raid('hqdoor'),'mlrs').fields[1].value

def test_verified_recipe_costs_and_batch_rounding():
    assert CAT.materials('c4',2)['sulfur']==4400
    assert CAT.materials('satchel')['sulfur']==480
    assert CAT.materials('satchel')['rope']==1
    assert CAT.materials('explosive-ammo',63)['sulfur']==1600
    assert CAT.materials('explosive-ammo',64)['sulfur']==1600
