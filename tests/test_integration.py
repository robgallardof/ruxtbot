"""End-to-end tests: boot the real bot, fake Discord interactions and the HTTP APIs, click through every panel."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import discord
import httpx
import pytest
from rustbot import __main__ as app
from rustbot.config import Settings

STEAMID = '76561198848618940'
NOW = datetime.now(timezone.utc)


def iso(delta_minutes=0):
    return (NOW - timedelta(minutes=delta_minutes)).isoformat().replace('+00:00', 'Z')


def bm_player(pid='1128280744', online=True):
    server = {'type': 'server', 'id': '5931597', 'attributes': {'name': 'Rusty Moose |US Medium|', 'status': 'online', 'queryStatus': 'valid',
                                                                 'updatedAt': iso(1)},
              'relationships': {'game': {'data': {'id': 'rust'}}},
              'meta': {'online': online, 'timePlayed': 7200, 'firstSeen': iso(9000), 'lastSeen': iso(2)}}
    names = [{'type': 'identifier', 'attributes': {'type': 'name', 'identifier': n, 'lastSeen': iso(i * 1000)}}
             for i, n in enumerate(['KingGallardo', 'robgallardof'])]
    return {'data': {'id': pid, 'attributes': {'name': 'KingGallardo', 'private': False}}, 'included': [server, *names]}


def fake_http(request: httpx.Request) -> httpx.Response:
    """Routes every outgoing request of the bot to canned responses."""
    url = str(request.url)
    if 'api.battlemetrics.com/servers?' in url:
        return httpx.Response(200, json={'data': [{'id': '9611162', 'attributes': {'name': 'Rusty Moose |US Monthly|', 'status': 'online', 'players': 833,
                                                                                    'maxPlayers': 850, 'rank': 40, 'country': 'US',
                                                                                    'details': {'rust_queued_players': 30}}}]})
    if 'api.battlemetrics.com/servers/' in url:
        return httpx.Response(200, json={'data': {'attributes': {'name': 'Rusty Moose |US Medium|', 'status': 'online', 'players': 190, 'maxPlayers': 200,
                                                                 'rank': 12, 'country': 'US', 'ip': '1.2.3.4', 'port': 28015,
                                                                 'details': {'map': 'Procedural Map', 'rust_world_size': 4250, 'rust_queued_players': 5,
                                                                             'rust_last_wipe': iso(60 * 24), 'rust_next_wipe': iso(-60 * 24 * 6)}}}})
    if 'api.battlemetrics.com/players?' in url:
        return httpx.Response(200, json={'data': [{'id': '1128280744', 'attributes': {'name': 'KingGallardo', 'updatedAt': iso(5)}}]})
    if 'api.battlemetrics.com/players/' in url:
        return httpx.Response(200, json=bm_player())
    if 'ajaxaliases' in url:
        return httpx.Response(200, json=[{'newname': 'OldName', 'timechanged': '4 Jun, 2021 @ 6:33am'}])
    if 'steamcommunity.com' in url and 'xml=1' in url:
        return httpx.Response(200, text=f'<profile><steamID64>{STEAMID}</steamID64><steamID><![CDATA[KingGallardo]]></steamID>'
                                        '<onlineState>in-game</onlineState><inGameInfo><gameName>Rust</gameName></inGameInfo>'
                                        '<privacyState>public</privacyState><vacBanned>0</vacBanned><tradeBanState>None</tradeBanState>'
                                        '<isLimitedAccount>0</isLimitedAccount><customURL>ikinggallardo</customURL><location>Mexico</location></profile>')
    if 'steamcommunity.com' in url:
        return httpx.Response(200, text='<span class="friendPlayerLevelNum">27</span>')
    if 'rustwho.com' in url:
        return httpx.Response(200, json={'steamInfo': {'name': 'KingGallardo', 'timeCreated': 1531931993},
                                         'steamBans': {'vacBans': 0, 'gameBans': 0, 'economyBan': 'none'}, 'serverBanCount': 1,
                                         'extraNameHistory': {'nameHistory': [{'name': 'KingGallardo', 'date': '2025-06-04T06:33:22.000Z'}], 'lockedExtraCount': 2},
                                         'rustStats': {'kills': 2187, 'deaths': 3252, 'kd': 0.67, 'accuracyPct': 22, 'headshotPct': 12.5}})
    return httpx.Response(404)


class FakeResponse:
    def __init__(self):
        self.calls = []

    async def send_message(self, *args, **kwargs):
        self.calls.append(('send', args, kwargs))

    async def edit_message(self, **kwargs):
        self.calls.append(('edit', (), kwargs))

    async def defer(self, **kwargs):
        self.calls.append(('defer', (), kwargs))

    def is_done(self):
        return bool(self.calls)


class FakeInteraction:
    """Just enough of discord.Interaction for command and component callbacks."""

    def __init__(self, locale='en-US', admin=True, values=None, user_id=7):
        self.locale = locale
        self.user = SimpleNamespace(id=user_id, display_name='Tester', guild_permissions=SimpleNamespace(administrator=admin))
        self.guild = SimpleNamespace(id=1, roles=[SimpleNamespace(name='wipe')])
        self.guild_id, self.channel_id = 1, 2
        self.channel = SimpleNamespace(id=2)
        self.response = FakeResponse()
        self.followup = SimpleNamespace(send=AsyncMock())
        self.data = {'values': values or []}
        self.message = None
        self.namespace = SimpleNamespace()

    async def original_response(self):
        return None

    def sent(self) -> dict:
        """kwargs of the last reply (response or followup)."""
        if self.followup.send.await_count:
            return self.followup.send.call_args.kwargs
        return self.response.calls[-1][2]


def text_of(view) -> str:
    return '\n'.join(i.content for i in view.walk_children() if isinstance(getattr(i, 'content', None), str))


def find(view, label=None, placeholder=None):
    for item in view.walk_children():
        if label and label in (getattr(item, 'label', None) or ''):
            return item
        if placeholder and placeholder in (getattr(item, 'placeholder', None) or ''):
            return item
    raise AssertionError(f'component not found: {label or placeholder}')


async def click(item, **kwargs):
    """Click a button / pick a select option; returns the interaction to inspect the new panel."""
    interaction = FakeInteraction(**kwargs)
    await item.callback(interaction)
    return interaction


@pytest.fixture
def bot(tmp_path):
    settings = Settings('test', 'bm-token', str(tmp_path / 'state.db'), 10, 'INFO', 'data/rust_catalog.yml')
    captured = []
    with patch.object(Settings, 'from_env', return_value=settings), patch.object(app.RustBot, 'run', lambda b, token: captured.append(b)):
        app.main()
    b = captured[0]
    transport = httpx.MockTransport(fake_http)
    b.bm.client = httpx.AsyncClient(transport=transport)
    b.who.client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    yield b
    b.store.conn.close()


def run(coro):
    return asyncio.run(coro)


def cmd(bot, name):
    return bot.tree.get_command(name).callback


def test_every_command_is_registered_localized_and_serializable(bot):
    async def go():
        from rustbot.i18n import CommandTranslator
        names = sorted(c.name for c in bot.tree.get_commands())
        assert names == sorted(['author', 'craft', 'examples', 'forcewipe', 'help', 'item', 'pausealerts', 'ping', 'player', 'raid', 'raidbudget',
                                'raidcalc', 'raidcompare', 'raidtools', 'resumealerts', 'server', 'servers', 'serversearch', 'settings',
                                'sources', 'status', 'syncservers', 'track', 'who', 'wipe'])
        for command in bot.tree.get_commands():
            payload = await command.get_translated_payload(bot.tree, CommandTranslator())
            assert payload['description_localizations'].get('es-ES'), command.name
    run(go())


@pytest.mark.parametrize('locale,word', [('en-US', 'KingGallardo'), ('es-ES', 'creado por')])
def test_author(bot, locale, word):
    i = FakeInteraction(locale)
    run(cmd(bot, 'author')(i))
    assert 'KingGallardo' in i.sent()['embed'].description and word in i.sent()['embed'].description


@pytest.mark.parametrize('locale,word', [('en-US', 'Crafting'), ('es-419', 'Crafteo')])
def test_examples(bot, locale, word):
    async def go():
        i = FakeInteraction(locale)
        await cmd(bot, 'examples')(i)
        view = i.sent()['view']
        view.to_components()
        assert word in text_of(view) and '/raidcalc' in text_of(view) and '/who' in text_of(view)
    run(go())


def test_help_buttons_open_tools(bot):
    async def go():
        i = FakeInteraction('es-ES')
        await cmd(bot, 'help')(i)
        menu = i.sent()['view']
        assert 'Crafteo' in text_of(menu)
        opened = await click(find(menu, label='Abrir'), locale='es-ES')
        assert 'Planificador de raid' in text_of(opened.sent()['view'])
        calc = await click(find(menu, label='Calculadora'), locale='es-ES')
        assert 'Calculadora de base' in text_of(calc.sent()['view'])
    run(go())


def test_raid_full_click_through(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'raid')(i, None, None, 'hard')
        home = i.sent()['view']
        doors = (await click(find(home, label='Open'))).sent()['view']
        assert 'Armored Door' in text_of(doors)
        sim = (await click(find(doors, placeholder='Pick a target'), values=['armored-door'])).sent()['view']
        assert 'Target intact' in text_of(sim) and '🏆 This is the cheapest option' in text_of(sim)
        c4 = (await click(find(sim, placeholder='Change method'), values=['c4'])).sent()['view']
        hit = (await click(find(c4, label='Apply 1'))).sent()['view']
        assert '1**/3' in text_of(hit) and 'Target damaged' in text_of(hit)
        undone = (await click(find(hit, label='Undo'))).sent()['view']
        assert '0**/3' in text_of(undone)
        done = (await click(find(undone, label='Complete'))).sent()['view']
        assert 'Target destroyed' in text_of(done) and find(done, label='Destroyed').disabled
        compare = await click(find(done, label='Compare'))
        assert compare.sent()['ephemeral'] and '🏆' in text_of(compare.sent()['view'])
        back = (await click(find(done, label='Back'))).sent()['view']
        assert 'Doors' in text_of(back)
    run(go())


def test_raid_soft_side_and_other_users_are_blocked(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'raid')(i, 'muro piedra', None, 'soft')
        wall = i.sent()['view']
        assert 'Soft side' in text_of(wall)
        hard = (await click(find(wall, label='Switch to Hard side'))).sent()['view']
        assert 'Hard side' in text_of(hard)
        stranger = FakeInteraction(user_id=99, locale='es-ES')
        assert await hard.interaction_check(stranger) is False
        bad = FakeInteraction()
        await cmd(bot, 'raid')(bad, 'not a target', None, 'hard')
        assert 'Unknown target' in bad.sent()['embed'].description
    run(go())


def test_raidcalc_flow_and_share(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'raidcalc')(i, 'armored door', 2, None)
        calc = i.sent()['view']
        assert '2×** Armored Door' in text_of(calc)
        walls = (await click(find(calc, placeholder='Category'), values=['walls'])).sent()['view']
        added = (await click(find(walls, placeholder='Add target'), values=['stone-wall'])).sent()['view']
        assert '1×** Stone Wall' in text_of(added)
        c4 = (await click(find(added, placeholder='Change method'), values=['c4'])).sent()['view']
        assert 'Timed Explosive Charge' in text_of(c4)
        removed = (await click(find(c4, placeholder='Remove one'), values=['stone-wall'])).sent()['view']
        assert 'Stone Wall' not in text_of(removed).split('Totals')[0]
        shared = await click(find(removed, label='Share'))
        assert 'Plan by Tester' in text_of(shared.sent()['view']) and not shared.sent().get('ephemeral')
        cleared = (await click(find(removed, label='Clear'))).sent()['view']
        assert 'Pick a category' in text_of(cleared)
    run(go())


def test_raidbudget_raidcompare_raidtools(bot):
    async def go():
        for name, args in [('raidbudget', (20000,)), ('raidcompare', ('garage door', 'hard')), ('raidtools', ('tc',))]:
            i = FakeInteraction('es-ES')
            await cmd(bot, name)(i, *args)
            view = i.sent()['view']
            view.to_components()
            assert text_of(view), name
    run(go())


def test_autocomplete(bot):
    async def go():
        i = FakeInteraction()
        target = bot.tree.get_command('raid')._params['target'].autocomplete
        choices = await target(i, 'armored')
        assert any(c.value == 'armored-door' for c in choices)
        i.namespace = SimpleNamespace(target='armored-door')
        methods = await bot.tree.get_command('raid')._params['method'].autocomplete(i, '')
        assert methods[0].value == 'explosive556' and 'sulfur' in methods[0].name
    run(go())


def test_item_and_craft(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'item')(i, 'c4')
        e = i.sent()['embed']
        assert e.thumbnail.url.endswith('explosive.timed.png') and 'Armored Door ×3' in e.fields[-1].value
        j = FakeInteraction('es-ES')
        await cmd(bot, 'craft')(j, 'rocket', 10)
        assert '14,000' in j.sent()['embed'].description and 'azufre' in j.sent()['embed'].description
        k = FakeInteraction()
        await cmd(bot, 'item')(k, 'zzz')
        assert 'unknown' in k.sent()['embed'].description
    run(go())


def test_server_commands(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'server')(i, 'Rustoria.co - US Mondays')
        e = i.sent()['embed']
        assert '190/200' in e.description and any('client.connect 1.2.3.4:28015' in f.value for f in e.fields)
        j = FakeInteraction('es-ES')
        await cmd(bot, 'serversearch')(j, 'moose')
        assert 'Rusty Moose' in j.sent()['embed'].description and '833/850' in j.sent()['embed'].description
        k = FakeInteraction()
        await cmd(bot, 'wipe')(k, 'Rustoria.co - US Mondays')
        assert '<t:' in k.sent()['embed'].description
        f = FakeInteraction()
        await cmd(bot, 'forcewipe')(f)
        assert 'first Thursday' in f.sent()['embed'].description
        p = FakeInteraction()
        await cmd(bot, 'servers')(p, '', 1)
        pages = p.sent()['view']
        nxt = await click(pages.next)
        assert nxt.response.calls[-1][2]['embed'].title.startswith('🖥️ Servers · 2/')
    run(go())


def test_player_presence(bot):
    async def go():
        i = FakeInteraction('es-ES')
        await cmd(bot, 'player')(i, 'https://www.battlemetrics.com/players/1128280744', '5931597')
        assert 'Conectado' in i.sent()['embed'].description
    run(go())


def test_who_end_to_end(bot):
    async def go():
        i = FakeInteraction('es-ES')
        await cmd(bot, 'who')(i, f'https://steamid.io/lookup/{STEAMID}', None)
        sent = i.sent()
        steam, rust, bm = sent['embeds']
        names = steam.fields[0]
        assert names.name.startswith('📝 Nombres anteriores') and 'OldName' in names.value and '+2' in names.value
        assert 'Jugando **Rust**' in steam.description
        assert 'también usó: robgallardof' in bm.description
        assert [b.label for b in sent['view'].children][:2] == ['Steam', 'SteamID I/O']
        again = FakeInteraction()
        await cmd(bot, 'who')(again, STEAMID, None)
        assert 'Wait' in again.response.calls[-1][1][0]  # per-user cooldown
    run(go())


def test_admin_flow_track_settings_alerts_status(bot):
    async def go():
        s = FakeInteraction('es-ES')
        await cmd(bot, 'settings')(s, 'es', True, 30, None)
        assert bot.store.settings(1) == (2, 'es', 1, 30)
        add = FakeInteraction()
        await cmd(bot, 'track')(add, 'add', 'https://www.battlemetrics.com/players/1128280744', None, 'King')
        assert 'Watching on **1**' in add.sent()['embed'].description
        bot.get_channel = lambda _: SimpleNamespace(guild=SimpleNamespace(id=1))
        lst = FakeInteraction()
        await cmd(bot, 'track')(lst, 'list', None, None, None)
        assert 'King' in lst.sent()['embed'].description
        await cmd(bot, 'pausealerts')(FakeInteraction())
        assert bot.store.settings(1)[2] == 0
        await cmd(bot, 'resumealerts')(FakeInteraction())
        st = FakeInteraction()
        await cmd(bot, 'status')(st)
        assert st.sent()['embed'].title.endswith('status')
        rm = FakeInteraction()
        await cmd(bot, 'track')(rm, 'remove', 'https://www.battlemetrics.com/players/1128280744', None, None)
        assert not bot.store.watches()
        nope = FakeInteraction(admin=False)
        await cmd(bot, 'track')(nope, 'list', None, None, None)
        assert 'administrators' in nope.sent()['embed'].description
    run(go())


def test_alert_is_sent_in_guild_language_on_transition(bot):
    async def go():
        bot.store.set_settings(1, 2, 'es', True, 10)
        bot.store.add('bm:1128280744', '5931597', 2, 'King @everyone')
        bot.store.set_state(bot.store.watches()[0], False)
        role = SimpleNamespace(name='wipe', mention='<@&55>', mentionable=True)
        channel = SimpleNamespace(guild=SimpleNamespace(id=1, roles=[role]), send=AsyncMock())
        bot.get_channel = lambda _: channel
        await app.RustBot.poll.coro(bot)
        text = channel.send.call_args.args[0]
        assert '<@&55>' in text and 'se conectó a' in text and '@everyone' not in text.replace('\\@everyone', '')
        assert channel.send.call_args.kwargs['allowed_mentions'].everyone is False
        assert bot.store.watches()[0].was_online == 1
    run(go())


def test_sources_and_ping(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'sources')(i)
        assert 'Rustly' in i.sent()['embed'].fields[0].value
        p = FakeInteraction('es-ES')
        await cmd(bot, 'ping')(p)
        assert 'Conectando' in p.response.calls[-1][1][0] or 'Pong' in p.response.calls[-1][1][0]
    run(go())


def test_global_error_handler_is_friendly(bot):
    async def go():
        i = FakeInteraction('es-ES')
        await bot.tree.on_error(i, discord.app_commands.AppCommandError('boom'))
        assert 'Algo salió mal' in i.sent()['embed'].description
    run(go())


def test_raid_json_matches_build_script_output(tmp_path):
    # The committed data must be exactly what the build script produces from the committed sources.
    import importlib.util
    from pathlib import Path
    root = Path(__file__).parents[1]
    before = json.loads((root / 'data' / 'raid.json').read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('build', root / 'scripts' / 'build_raid_data.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    assert json.loads((root / 'data' / 'raid.json').read_text(encoding='utf-8')) == before
