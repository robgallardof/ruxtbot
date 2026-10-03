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
    steam = [{'type': 'identifier', 'attributes': {'type': 'steamID', 'identifier': STEAMID}}] if pid == '1128280744' else []
    return {'data': {'id': pid, 'attributes': {'name': 'KingGallardo' if pid == '1128280744' else f'Player{pid}', 'private': False}},
            'included': [server, *names, *steam]}


def fake_http(request: httpx.Request) -> httpx.Response:
    """Routes every outgoing request of the bot to canned responses."""
    url = str(request.url)
    if request.url.path == '/players/quick-match':
        return httpx.Response(200, json={'data': [{'type': 'identifier', 'attributes': {'type': 'steamID', 'identifier': STEAMID},
            'relationships': {'player': {'data': {'type': 'player', 'id': '1128280744'}}}}]})
    if '/relationships/sessions' in url:
        return httpx.Response(200, json={'data': [{'type': 'session', 'attributes': {'start': iso(120), 'stop': iso(60)},
            'relationships': {'server': {'data': {'id': '5931597'}}}}], 'included': bm_player()['included']})
    if 'api.battlemetrics.com/servers?' in url:
        return httpx.Response(200, json={'data': [{'id': '9611162', 'attributes': {'name': 'Rusty Moose |US Monthly|', 'status': 'online', 'players': 833,
                                                                                    'maxPlayers': 850, 'rank': 40, 'country': 'US',
                                                                                    'details': {'rust_queued_players': 30}}}]})
    if 'api.battlemetrics.com/servers/' in url and 'include=player' in url:
        players = [{'type': 'player', 'id': pid, 'attributes': {'name': name}} for pid, name in
                   [('1128280744', 'KingGallardo'), ('77', 'Bob <@everyone>'), *[(str(100 + n), f'Filler{n}') for n in range(25)]]]
        sessions = [{'type': 'session', 'attributes': {'start': iso(90), 'stop': None}, 'relationships': {'player': {'data': {'type': 'player', 'id': '1128280744'}}}}]
        return httpx.Response(200, json={'data': {'id': '5931597', 'attributes': {'name': 'Rusty Moose |US Medium|', 'players': 27, 'maxPlayers': 200}},
                                         'included': players + sessions})
    if 'api.battlemetrics.com/servers/' in url:
        return httpx.Response(200, json={'data': {'attributes': {'name': 'Rusty Moose |US Medium|', 'status': 'online', 'players': 190, 'maxPlayers': 200,
                                                                 'rank': 12, 'country': 'US', 'ip': '1.2.3.4', 'port': 28015,
                                                                 'details': {'map': 'Procedural Map', 'rust_world_size': 4250, 'rust_queued_players': 5,
                                                                             'rust_last_wipe': iso(60 * 24), 'rust_next_wipe': iso(-60 * 24 * 6)}}}})
    if 'api.battlemetrics.com/players?' in url:
        return httpx.Response(200, json={'data': [{'id': '1128280744', 'attributes': {'name': 'KingGallardo', 'updatedAt': iso(5)}}]})
    if 'api.battlemetrics.com/players/' in url:
        return httpx.Response(200, json=bm_player(request.url.path.split('/')[2]))
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
        assert names == sorted(['online', 'findplayer', 'playercompare', 'steamid', 'presence', 'sessions', 'author', 'craft', 'examples', 'forcewipe', 'help', 'item', 'pausealerts', 'ping', 'player', 'raid', 'raidbudget',
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
        assert 'En línea ahora' in bm.description
        assert 'robgallardof' in names.value
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
        assert 'No active watches' in nope.sent()['embed'].description
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


def test_steamid_tracking_presence_sessions_and_who(bot):
    async def go():
        i = FakeInteraction(locale='es-ES')
        await cmd(bot, 'track')(i, 'add', STEAMID)
        assert bot.store.watches()[0].steamid == 'bm:1128280744'
        for command in ('presence', 'sessions'):
            i = FakeInteraction(locale='es-ES')
            await cmd(bot, command)(i, STEAMID)
            e = i.followup.send.call_args.kwargs['embed']
            assert 'Rusty Moose' in e.description
            assert len(e) <= 6000
        report = await bot.who.lookup(__import__('rustbot.who', fromlist=['parse_target']).parse_target(STEAMID))
        assert report['bm_id'] == '1128280744'
        assert 'bm' in report and not report.get('bm_candidates')
    run(go())


def test_member_tracking_ownership_expiry_and_public_share(bot):
    async def go():
        import time
        member = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'track')(member, 'add', STEAMID, days=15, share=True)
        watch = bot.store.watches()[0]
        assert watch.owner_id == 20
        assert 14.99 * 86400 < watch.expires_at-time.time() <= 15*86400
        assert member.sent()['ephemeral'] is False
        stranger = FakeInteraction(admin=False, user_id=21)
        await cmd(bot, 'track')(stranger, 'remove', STEAMID)
        assert 'belongs to another' in stranger.sent()['embed'].description
        assert len(bot.store.watches()) == 1
        for name, args in [('player', (STEAMID, '5931597')), ('presence', (STEAMID,)), ('sessions', (STEAMID,)), ('who', (STEAMID,))]:
            i = FakeInteraction(user_id=30)
            await cmd(bot, name)(i, *args, share=True)
            assert i.sent()['ephemeral'] is False
        owner = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'track')(owner, 'remove', STEAMID)
        assert not bot.store.watches()
    run(go())


def test_guided_tracking_panel_and_modal(bot):
    async def go():
        from unittest.mock import AsyncMock
        from rustbot.track_ui import TrackModal
        i = FakeInteraction(locale='es-ES', admin=False)
        await cmd(bot, 'track')(i)
        panel = i.sent()['view']
        assert [b.label for b in panel.children] == ['Seguir · 7 días', 'Seguir · 15 días', 'Dejar de seguir', 'Mis seguimientos']
        click_i = FakeInteraction(locale='es-ES', admin=False)
        click_i.response.send_modal = AsyncMock()
        await panel.children[1].callback(click_i)
        modal = click_i.response.send_modal.call_args.args[0]
        assert modal.days == 15
        modal.player._value = STEAMID
        modal.nickname._value = 'Compañero'
        submit = FakeInteraction(locale='es-ES', admin=False)
        await modal.on_submit(submit)
        assert bot.store.watches()[0].label == 'Compañero'
        assert any(f.name == 'Finaliza automáticamente' for f in submit.sent()['embed'].fields)
        stop = TrackModal(cmd(bot, 'track'), 'es', 7, 'remove')
        stop.player._value = STEAMID
        await stop.on_submit(FakeInteraction(locale='es-ES', admin=False))
        assert not bot.store.watches()
    run(go())


def test_player_book_autocompletes_names_after_a_lookup(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'who')(i, STEAMID)
        complete = bot.tree.get_command('player')._params['player'].autocomplete
        choices = await complete(FakeInteraction(), 'king')
        assert [(c.name, c.value) for c in choices] == [(f'KingGallardo · {STEAMID}', STEAMID)]
        # Other guilds never see this guild's lookups.
        other = FakeInteraction()
        other.guild_id = 999
        assert await complete(other, 'king') == []
        typed = await complete(FakeInteraction(), '1128280744')
        assert typed[0].value == '1128280744' and 'BattleMetrics' in typed[0].name
        # The value picked from autocomplete works directly in every player command.
        p = FakeInteraction()
        await cmd(bot, 'player')(p, choices[0].value, '5931597')
        assert 'Online' in p.sent()['embed'].description
    run(go())


def test_who_with_only_a_battlemetrics_id_finds_the_steam_profile(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'who')(i, '1128280744')
        sent = i.sent()
        assert sent['embeds'][0].title == '👤 KingGallardo'
        assert any(e.title.startswith('📊 BattleMetrics') for e in sent['embeds'])
        labels = [b.label for b in sent['view'].children]
        assert 'Steam' in labels and 'Watch 7 days' in labels and 'Sessions' in labels
        sessions = await click(next(b for b in sent['view'].children if b.label == 'Sessions'))
        assert 'Rusty Moose' in sessions.sent()['embed'].description
        bad = FakeInteraction()
        await cmd(bot, 'who')(bad, STEAMID, 'https://evil.test/1')
        assert 'numbers only' in bad.sent()['embed'].description
    run(go())


def test_online_lists_players_marks_known_ones_and_opens_profiles(bot):
    async def go():
        bot.store.remember_player(1, 'KingGallardo', STEAMID, '1128280744')
        i = FakeInteraction()
        await cmd(bot, 'online')(i, '5931597')
        e, view = i.sent()['embed'], i.sent()['view']
        assert '⭐ **KingGallardo** · <t:' in e.description and '27/200' in e.fields[0].value
        assert '@everyone' not in e.description.replace('\\@everyone', '')
        picker = find(view, placeholder='Open a player profile')
        assert len(picker.options) == 20
        page2 = await click(next(c for c in view.children if str(getattr(c, 'emoji', '')) == '▶️'))
        assert '` 21` **Filler18**' in page2.response.calls[-1][2]['embed'].description
        opened = await click(picker, values=['1128280744'])
        assert opened.sent()['embeds'][0].title == '👤 KingGallardo'
        f = FakeInteraction('es-ES')
        await cmd(bot, 'online')(f, 'Rusty Moose |US Medium|', 'bob')
        assert 'filtro' in f.sent()['embed'].fields[0].value and 'Filler' not in f.sent()['embed'].description
    run(go())


def test_findplayer_playercompare_and_steamid(bot):
    async def go():
        f = FakeInteraction()
        await cmd(bot, 'findplayer')(f, 'KingGallardo')
        assert '`1128280744`' in f.sent()['embed'].description
        assert find(f.sent()['view'], placeholder='Open a player profile').options[0].value == '1128280744'
        c = FakeInteraction()
        await cmd(bot, 'playercompare')(c, STEAMID, '555')
        e = c.sent()['embed']
        assert 'KingGallardo' in e.title and 'Player555' in e.title
        assert 'Rusty Moose' in e.description and '🟢🟢' in e.description and '**1**' in e.fields[0].value
        same = FakeInteraction()
        await cmd(bot, 'playercompare')(same, STEAMID, '1128280744')
        assert 'same player' in same.sent()['embed'].description
        s = FakeInteraction()
        await cmd(bot, 'steamid')(s, 'STEAM_0:0:444176606')
        assert STEAMID in s.sent()['embed'].description and '[U:1:888353212]' in s.sent()['embed'].description
        b = FakeInteraction()
        await cmd(bot, 'steamid')(b, '!!!')
        assert 'SteamID64' in b.sent()['embed'].description
    run(go())


def test_servers_accept_any_id_and_autocomplete_live(bot):
    async def go():
        i = FakeInteraction()
        await cmd(bot, 'server')(i, '424242')
        assert '190/200' in i.sent()['embed'].description and '424242' in i.sent()['embed'].footer.text
        complete = bot.tree.get_command('online')._params['server'].autocomplete
        choices = await complete(FakeInteraction(), 'xyzq')
        assert any(c.value == '9611162' and '👥 833' in c.name for c in choices)
        typed = await complete(FakeInteraction(), '123456')
        assert typed[0].value == '123456'
    run(go())


def test_friendly_names_errors_and_hub(bot):
    async def go():
        # Unknown name: friendly error with a one-click search.
        u = FakeInteraction()
        await cmd(bot, 'player')(u, 'KingGallardo', '5931597')
        assert "don't know a player called «KingGallardo»" in u.sent()['embed'].description
        search = next(b for b in u.sent()['view'].children if b.label == 'Search «KingGallardo»')
        found = await click(search)
        assert '`1128280744`' in found.sent()['embed'].description
        # /who with nothing opens the hub; after one lookup the player is listed there.
        await cmd(bot, 'who')(FakeInteraction(), STEAMID)
        h = FakeInteraction()
        await cmd(bot, 'who')(h)
        assert h.sent()['embed'].title == '🕵️ Look up a player'
        recent = find(h.sent()['view'], placeholder='Recent players')
        assert recent.options[0].label == 'KingGallardo' and recent.options[0].value == STEAMID
        # A typed name (no suggestion picked) now resolves from the book.
        p = FakeInteraction()
        await cmd(bot, 'player')(p, 'kinggallardo', '5931597')
        assert 'Online' in p.sent()['embed'].description
        # Without a server, /player shows where the player is.
        w = FakeInteraction()
        await cmd(bot, 'player')(w, 'KingGallardo')
        assert 'Rusty Moose' in w.sent()['embed'].description
    run(go())


def test_track_panel_quick_watch_and_help_players_button(bot):
    async def go():
        bot.store.remember_player(1, 'KingGallardo', STEAMID, '1128280744')
        i = FakeInteraction(admin=False)
        await cmd(bot, 'track')(i)
        quick = find(i.sent()['view'], placeholder='Watch a recent player')
        assert quick.options[0].value == STEAMID
        done = await click(quick, values=[STEAMID], admin=False)
        assert 'Watching on **1**' in done.sent()['embed'].description
        assert 6.99 * 86400 < bot.store.watches()[0].expires_at - __import__('time').time() <= 7 * 86400
        h = FakeInteraction()
        await cmd(bot, 'help')(h)
        opened = await click(find(h.sent()['view'], label='Find player'))
        assert opened.sent()['embed'].title == '🕵️ Look up a player'
    run(go())


def test_steamid_loads_everything_even_without_quick_match(bot):
    """SteamID -> BattleMetrics: cached after the first match; when quick-match is denied, a same-name profile
    that lists the exact SteamID is used, and one that does not is never assumed."""
    calls = []

    def denied(request):
        calls.append(request.url.path)
        if request.url.path == '/players/quick-match':
            return httpx.Response(403, json={})
        return fake_http(request)

    async def go():
        transport = httpx.MockTransport(denied)
        bot.bm.client = httpx.AsyncClient(transport=transport)
        bot.who.client = httpx.AsyncClient(transport=transport, follow_redirects=True)
        i = FakeInteraction()
        await cmd(bot, 'presence')(i, STEAMID)
        assert 'Rusty Moose' in i.sent()['embed'].description
        assert bot.store.identity(STEAMID) == '1128280744'
        calls.clear()
        again = FakeInteraction()
        await cmd(bot, 'player')(again, STEAMID, '5931597')
        assert 'Online' in again.sent()['embed'].description and '/players/quick-match' not in calls
        # /who with a SteamID loads Steam + RustWho + BattleMetrics together.
        bot.store.conn.execute('DELETE FROM identities')
        w = FakeInteraction()
        await cmd(bot, 'who')(w, STEAMID)
        titles = [e.title or '' for e in w.sent()['embeds']]
        assert titles[0] == '👤 KingGallardo' and any(x.startswith('📊 BattleMetrics · KingGallardo') for x in titles)
    run(go())


def test_link_steamid_once_like_the_real_api(bot):
    """Real token behaviour: quick-match answers 200 with no data and profiles only list names.
    The user links the right profile once (ranked by names shared with Steam) and the SteamID loads everything after."""
    def handler(request):
        path, url = request.url.path, str(request.url)
        if path == '/players/quick-match':
            return httpx.Response(200, json={'data': []})
        if 'api.battlemetrics.com/players?' in url:
            return httpx.Response(200, json={'data': [{'id': '950321455', 'attributes': {'name': 'kingGallardo', 'updatedAt': iso(1)}},
                                                      {'id': '1128280744', 'attributes': {'name': 'KingGallardo', 'updatedAt': iso(500)}},
                                                      {'id': '600486137', 'attributes': {'name': '[Gallardo] King Khalil', 'updatedAt': iso(2)}}]})
        if path.startswith('/players/') and 'relationships' not in path:
            data = bm_player(path.split('/')[2])
            data['included'] = [r for r in data['included'] if (r.get('attributes') or {}).get('type') != 'steamID']
            if path.split('/')[2] != '1128280744':
                data['included'] = [r for r in data['included'] if r['type'] == 'server'] + [
                    {'type': 'identifier', 'attributes': {'type': 'name', 'identifier': 'kingGallardo'}}]
            return httpx.Response(200, json=data)
        if 'ajaxaliases' in url:
            return httpx.Response(200, json=[{'newname': 'robgallardof', 'timechanged': '4 Jun, 2021 @ 6:33am'}])
        return fake_http(request)

    async def go():
        transport = httpx.MockTransport(handler)
        bot.bm.client = httpx.AsyncClient(transport=transport)
        bot.who.client = httpx.AsyncClient(transport=transport, follow_redirects=True)
        t1 = FakeInteraction()
        await cmd(bot, 'track')(t1, 'add', STEAMID)
        assert 'linked once' in t1.sent()['embed'].description and not bot.store.watches()
        opened = await click(next(b for b in t1.sent()['view'].children if b.label == 'Open profile and link'))
        sent = opened.sent()
        bm = next(e for e in sent['embeds'] if e.title == '📊 BattleMetrics')
        assert '⭐ [KingGallardo](https://www.battlemetrics.com/players/1128280744)' in bm.description and 'robgallardof' in bm.description
        assert '[Gallardo] King Khalil' not in bm.description  # different name: never offered
        assert '🟢 online on Rusty Moose |US Medium|' in bm.description
        picker = find(sent['view'], placeholder='Which BattleMetrics profile')
        assert picker.options[0].value == '1128280744' and str(picker.options[0].emoji) == '⭐'
        linked = await click(picker, values=['1128280744'])
        titles = [e.title or '' for e in linked.sent()['embeds']]
        assert titles[0] == '👤 KingGallardo' and any(x.startswith('📊 BattleMetrics · KingGallardo') for x in titles)
        # From now on the SteamID alone works everywhere.
        t2 = FakeInteraction()
        await cmd(bot, 'track')(t2, 'add', STEAMID)
        assert 'Watching on **1**' in t2.sent()['embed'].description and bot.store.watches()[0].steamid == 'bm:1128280744'
        # Links are per Discord server: another guild still has to link it itself.
        other = FakeInteraction()
        other.guild_id = 999
        await cmd(bot, 'presence')(other, STEAMID)
        assert 'linked once' in other.sent()['embed'].description
    run(go())
