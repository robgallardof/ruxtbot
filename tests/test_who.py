import asyncio
import httpx
import pytest
from rustbot.who import Target, WhoService, build_embeds, links, name_history, parse_target, steam_ids

ID = '76561198848618940'


@pytest.mark.parametrize('value,expected', [
    (ID, Target(steamid=ID)),
    (f'https://steamid.io/lookup/{ID}', Target(steamid=ID)),
    (f'https://steamdb.info/calculator/{ID}/?cc=mx', Target(steamid=ID)),
    (f'https://www.rustwho.com/stats/{ID}', Target(steamid=ID)),
    (f'https://steamcommunity.com/profiles/{ID}/', Target(steamid=ID)),
    ('https://steamcommunity.com/id/ikinggallardo/', Target(vanity='ikinggallardo')),
    ('https://steamid.io/lookup/ikinggallardo', Target(vanity='ikinggallardo')),
    ('STEAM_0:0:444176606', Target(steamid=ID)),
    ('[U:1:888353212]', Target(steamid=ID)),
    ('https://www.battlemetrics.com/players/1128280744', Target(bm_id='1128280744')),
])
def test_parse_target_accepts_every_supported_link(value, expected):
    assert parse_target(value) == expected


@pytest.mark.parametrize('value', ['', 'https://evil.test/x y', 'two words', '<@123>'])
def test_parse_target_rejects_garbage(value):
    with pytest.raises(ValueError):
        parse_target(value)


def test_steam_id_formats_match_steamid_io():
    assert steam_ids(ID) == {'steam64': ID, 'steam2': 'STEAM_0:0:444176606', 'steam3': '[U:1:888353212]', 'account': '888353212'}
    assert links(ID, None)['SteamDB'] == f'https://steamdb.info/calculator/{ID}/?cc=mx'
    assert 'BattleMetrics' not in links(ID, None)


def test_name_history_merges_sources_newest_first():
    report = {
        'aliases': [{'newname': 'OldSteam', 'timechanged': '4 Jun, 2021 @ 6:33am'}],
        'rustwho': {'extraNameHistory': {'nameHistory': [{'name': 'King', 'date': '2025-06-04T06:33:22.000Z'}]}},
        'bm': {'included': [{'type': 'identifier', 'attributes': {'type': 'name', 'identifier': 'king', 'lastSeen': '2026-01-01T00:00:00Z'}},
                            {'type': 'server', 'attributes': {'name': 'ignored'}}]},
    }
    rows = name_history(report)
    assert [r[0] for r in rows] == ['king', 'OldSteam']
    assert rows[0][2] == 'RW·BM'


def report_fixture():
    return {
        'steamid': ID, 'bm_id': '42', 'errors': ['games'],
        'steam': {'name': 'King', 'online_state': 'in-game', 'game': 'Rust', 'privacy': 'public', 'avatar': 'https://a/x.jpg',
                  'vac_banned': False, 'trade_ban': 'None', 'limited': False, 'custom_url': 'king', 'location': 'Mexico'},
        'page': {'level': 27, 'games': 24},
        'rustwho': {'steamInfo': {'timeCreated': 1531931993}, 'steamBans': {'vacBans': 1, 'gameBans': 0, 'economyBan': 'none', 'daysSinceLastBan': 30},
                    'serverBanCount': 0, 'rustStats': {'kills': 10, 'deaths': 5, 'kd': 2.0, 'accuracyPct': 22, 'headshotPct': 12.5, 'observedAt': '2026-10-03T01:54:50.403Z'}},
        'bm': {'data': {'attributes': {'name': 'King'}}, 'included': [
            {'type': 'server', 'id': '1', 'attributes': {'name': 'Rusty Moose'}, 'meta': {'timePlayed': 7200, 'online': True, 'firstSeen': '2023-01-01T00:00:00Z', 'lastSeen': '2026-10-01T00:00:00Z'}}]},
    }


def test_embeds_show_every_section():
    embeds = build_embeds(report_fixture())
    steam, rust, bm = embeds
    assert steam.title == '👤 King' and steam.color.value == 0xC0392B  # VAC => rojo
    assert '🎮 Playing **Rust**' in steam.description
    assert '🎮 Jugando **Rust**' in build_embeds(report_fixture(), lang='es')[0].description
    fields = {f.name: f.value for f in steam.fields}
    assert 'STEAM_0:0:444176606' in fields['🆔 Identifiers']
    assert '⛔ VAC: **1**' in fields['🛡️ Bans'] and '**30** days ago' in fields['🛡️ Bans']
    assert '⭐ Level: **27**' in fields['📋 Account']
    assert '🔥 K/D **2**' in rust.description and '12.5%' in rust.description
    assert '🟢 **Online now**' in bm.description
    assert {f.name: f.value for f in bm.fields}['⏱️ Time played'] == '**2 h**'
    assert 'Steam API' in bm.footer.text
    assert sum(len(e) for e in embeds) <= 6000


def test_private_stats_and_bm_only_input():
    report = report_fixture() | {'rustwho': {'rustStats': {'noData': True}}}
    assert 'private' in build_embeds(report)[1].description
    assert 'privadas' in build_embeds(report, lang='es')[1].description
    only_bm = {'steamid': None, 'bm_id': '42', 'errors': [], 'bm': report_fixture()['bm']}
    embeds = build_embeds(only_bm)
    assert embeds[0].title.startswith('📊') and 'SteamID64' in embeds[-1].description


def test_lookup_survives_a_failing_source_and_resolves_vanity():
    def handler(req):
        url = str(req.url)
        if '/id/king' in url:
            return httpx.Response(200, text=f'<profile><steamID64>{ID}</steamID64></profile>')
        if url.endswith('?xml=1'):
            return httpx.Response(200, text='<profile><steamID><![CDATA[King]]></steamID><vacBanned>0</vacBanned></profile>')
        if 'ajaxaliases' in url:
            return httpx.Response(200, json=[{'newname': 'Old', 'timechanged': '1 Jan, 2020 @ 1:00pm'}])
        if 'rustwho' in url:
            return httpx.Response(503)
        return httpx.Response(200, text='<span class="friendPlayerLevelNum">9</span>')

    class FakeBM:
        token = 'x'
        async def search_players(self, name):
            return [{'id': '1', 'attributes': {'name': 'king', 'updatedAt': '2026-01-01T00:00:00Z'}},
                    {'id': '2', 'attributes': {'name': 'Kingston'}}]

    async def run():
        service = WhoService(FakeBM(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        report = await service.lookup(parse_target('https://steamcommunity.com/id/king'))
        await service.client.aclose()
        return report

    report = asyncio.run(run())
    assert report['steamid'] == ID and report['steam']['name'] == 'King' and report['page'] == {'level': 9}
    assert report['errors'] == ['rustwho']
    assert [p['id'] for p in report['bm_candidates']] == ['1']
    assert len(build_embeds(report)) == 2


def test_numeric_battlemetrics_input():
    assert parse_target('123').bm_id == '123'
