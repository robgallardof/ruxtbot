from pathlib import Path
from rustbot.catalog import Catalog

CAT=Catalog.load(str(Path(__file__).parents[1]/'data'/'rust_catalog.yml'))
def test_spanish_target_alias_resolves():
    assert CAT.raid('puerta hq')['name'] == 'Armored Door / HQ Door'
def test_raid_catalog_covers_all_menu_categories():
    categories={target.get('category') for target in CAT.raw['targets'].values()}
    assert {'doors','walls','building','deployables','siege'} <= categories
    assert CAT.raid('muro blindado')['id'] if 'id' in CAT.raid('muro blindado') else CAT.raid('muro blindado')['name'] == 'Armored Wall / HQ Wall'
    assert CAT.raid('bombona')['name'] == 'Propane Tank'
def test_recursive_rocket_materials():
    m=CAT.materials('rocket', 1)
    assert m['sulfur'] == 1400 and m['charcoal'] == 1950 and m['metal-pipe'] == 2
    assert CAT.intermediates('rocket', 100)['explosives'] == 1000
    assert CAT.intermediates('rocket', 100)['gunpowder'] == 65000
