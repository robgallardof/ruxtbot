"""/me, /sv, /ip, /setserver, /server cards, /serverstats, /leaderboard, /serversearch, /rust, /player extras and /version."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from rustbot import maintenance
from rustbot.serverinfo import server_matches, spark
from test_integration import STEAMID, FakeInteraction, bm_player, bot, cmd, fake_http, find, iso, run  # noqa: F401  (bot is a fixture)

DETAILS = {'map': 'Procedural Map', 'rust_world_size': 4250, 'rust_queued_players': 5, 'rust_last_wipe': iso(60 * 24), 'rust_next_wipe': iso(-60 * 24 * 6),
           'rust_type': 'community', 'rust_fps_avg': 58, 'rust_uptime': 7200, 'pve': False,
           'rust_settings': {'rates': {'gather': 2, 'craft': 2, 'scrap': 2}, 'groupLimit': 3, 'teamUILimit': 3, 'upkeep': 0.5, 'decay': 1, 'blueprints': False},
           'rust_maps': {'url': 'https://rustmaps.com/map/abc', 'thumbnailUrl': 'https://content.rustmaps.com/thumb.webp'},
           'rust_wipes': [{'type': 'map', 'timestamp': iso(-60 * 24 * 6)}, {'type': 'map', 'timestamp': iso(-60 * 24 * 13)}]}


def points(values):
    return {'data': [{'type': 'dataPoint', 'attributes': {'timestamp': iso(60 * (len(values) - i)), 'value': v}} for i, v in enumerate(values)]}


def handler(request):
    path, url = request.url.path, str(request.url)
    if path.endswith('/player-count-history'):
        return httpx.Response(200, json=points([100, 150, 200, 180]))
    if path.endswith('/rank-history'):
        return httpx.Response(200, json=points([30, 12, 15]))
    if path.endswith('/unique-player-history'):
        return httpx.Response(200, json=points([900, 1200]))
    if path.endswith('/first-time-history'):
        return httpx.Response(200, json=points([40, 60]))
    if path.endswith('/relationships/outages'):
        return httpx.Response(200, json={'data': [{'type': 'serverOutage', 'attributes': {'start': iso(120), 'stop': iso(110)}}]})
    if path.endswith('/relationships/leaderboards/time'):
        offset = int(request.url.params.get('page[offset]', 0))
        rows = [{'type': 'leaderboardPlayer', 'id': str(1000 + offset + n), 'attributes': {'name': f'Grinder{offset + n}', 'value': 36000 - n, 'rank': offset + n + 1}} for n in range(10)]
        return httpx.Response(200, json={'data': rows, 'links': {'next': 'more'} if offset == 0 else {}})
    if '/time-played-history/' in path:
        return httpx.Response(200, json=points([3600, 7200, 0, 10800]))
    if path.startswith('/players/') and '/servers/' in path:
        return httpx.Response(200, json={'data': {'type': 'playerServerInformation', 'attributes': {'firstSeen': iso(9000), 'lastSeen': iso(2), 'timePlayed': 72000, 'online': True}}})
    if path == '/games/rust':
        return httpx.Response(200, json={'data': {'attributes': {'players': 113122, 'servers': 7334, 'minPlayers24H': 51521, 'maxPlayers24H': 115741, 'maxPlayers7D': 115741}}})
    if path == '/servers':
        rows = [{'id': '1', 'attributes': {'name': 'Trio 2x Fresh', 'status': 'online', 'players': 300, 'maxPlayers': 400, 'country': 'US', 'details': DETAILS}},
                {'id': '2', 'attributes': {'name': 'Vanilla Solo', 'status': 'online', 'players': 200, 'maxPlayers': 200, 'country': 'US',
                                           'details': {'rust_settings': {'rates': {'gather': 1}, 'groupLimit': 1}, 'rust_last_wipe': iso(60 * 24 * 20)}}}]
        return httpx.Response(200, json={'data': rows})
    if path.startswith('/servers/') and path.count('/') == 2 and 'include' not in url:
        return httpx.Response(200, json={'data': {'attributes': {'name': 'Rusty Moose |US Medium|', 'status': 'online', 'players': 190, 'maxPlayers': 200, 'rank': 12,
                                                                 'country': 'US', 'ip': '1.2.3.4', 'port': 28015, 'details': DETAILS}}})
    return fake_http(request)


def use(bot):
    transport = httpx.MockTransport(handler)
    bot.bm.client = httpx.AsyncClient(transport=transport)
    bot.who.client = httpx.AsyncClient(transport=transport, follow_redirects=True)


def test_spark_and_filters():
    assert spark([0, 5, 10]) == '▁▄█' and len(spark(list(range(100)), 24)) == 24
    a = {'details': DETAILS}
    assert server_matches(a, '2', '3', 'community', 2, False)
    assert not server_matches(a, '1', None, None, None, None) and not server_matches(a, None, '2', None, None, None)
    assert not server_matches(a, None, None, 'official', None, None) and not server_matches(a, None, None, None, None, True)


def test_me_settings_drive_default_servers(bot):
    async def go():
        use(bot)
        i = FakeInteraction(user_id=20)
        await cmd(bot, 'me')(i, battlemetrics='https://www.battlemetrics.com/players/1128280744')
        e = i.sent()['embed']
        assert 'Saved' in e.description and '1128280744' in e.fields[0].value and 'Rusty Moose' in e.fields[1].value
        assert bot.users_cfg.get(20) == ('1128280744', None)
        # /online with no server: the server this member is playing on.
        o = FakeInteraction(user_id=20)
        await cmd(bot, 'online')(o)
        assert 'Rusty Moose' in o.sent()['embed'].title
        # /findplayer lists matches on that server first.
        f = FakeInteraction(user_id=20)
        await cmd(bot, 'findplayer')(f, 'bob')
        assert f.sent()['embed'].fields[0].name.startswith('🖥️ On your server') and '`77`' in f.sent()['embed'].fields[0].value
        card = FakeInteraction(user_id=20)
        await cmd(bot, 'me')(card)
        assert [b.label for b in card.sent()['view'].children] == ['Set my BattleMetrics', 'Who is on my server', 'Find a player here', 'Forget me']
        bad = FakeInteraction(user_id=20)
        await cmd(bot, 'me')(bad, battlemetrics='https://evil.test/1')
        assert 'numbers only' in bad.sent()['embed'].description
        gone = FakeInteraction(user_id=20)
        await cmd(bot, 'me')(gone, forget=True)
        assert bot.users_cfg.get(20) == (None, None)
        nothing = FakeInteraction(user_id=21)
        await cmd(bot, 'online')(nothing)
        assert 'Which server' in nothing.sent()['embed'].description
    run(go())


def test_sv_ip_setserver_and_copy(bot):
    async def go():
        use(bot)
        empty = FakeInteraction()
        await cmd(bot, 'sv')(empty)
        assert 'No server saved' in empty.sent()['embed'].description
        member = FakeInteraction(admin=False)
        await cmd(bot, 'setserver')(member, 'Main', '1.2.3.4:28015')
        assert 'Manage Server' in member.sent()['embed'].description
        bad = FakeInteraction()
        await cmd(bot, 'setserver')(bad, 'Main', 'not an address')
        assert 'IP:port' in bad.sent()['embed'].description
        ok = FakeInteraction()
        await cmd(bot, 'setserver')(ok, 'Main', 'client.connect 1.2.3.4:28015', '5931597')
        assert 'client.connect 1.2.3.4:28015' in ok.sent()['embed'].fields[0].value
        await cmd(bot, 'setserver')(FakeInteraction(), 'Backup', 'play.backup.gg:28016')
        for name in ('sv', 'ip'):
            i = FakeInteraction(admin=False)
            await cmd(bot, name)(i)
            sent = i.sent()
            assert sent.get('ephemeral') is False                      # public: everyone sees the connect line
            assert any(f.value == '```\nclient.connect 1.2.3.4:28015\n```' for f in sent['embed'].fields) and '2x' in sent['embed'].description
        b = FakeInteraction()
        await cmd(bot, 'sv')(b, 'backup')
        assert 'play.backup.gg:28016' in str(b.sent()['embed'].fields)
        copy = next(c for c in b.sent()['view'].children if getattr(c, 'label', '') == 'Copy connect')
        clicked = FakeInteraction()
        await copy.callback(clicked)
        assert clicked.response.calls[-1][1][0] == 'client.connect play.backup.gg:28016' and clicked.response.calls[-1][2]['ephemeral']
        choices = await bot.tree.get_command('sv')._params['name'].autocomplete(FakeInteraction(), '')
        assert choices[0].name.startswith('⭐ Main')
        rm = FakeInteraction()
        await cmd(bot, 'delserver')(rm, 'Backup')
        assert 'Removed' in rm.sent()['embed'].description and len(bot.presets.all(1)) == 1
    run(go())


def test_server_card_stats_leaderboard_search_and_rust(bot):
    async def go():
        use(bot)
        i = FakeInteraction()
        await cmd(bot, 'server')(i, '5931597')
        e, view = i.sent()['embed'], i.sent()['view']
        assert '2x' in e.description and 'max 3 per group' in e.description and 'Community' in e.description
        assert e.thumbnail.url.endswith('thumb.webp') and any('RustMaps' in f.value for f in e.fields) and any('58 FPS' in f.value for f in e.fields)
        labels = [c.label for c in view.children]
        assert labels[:4] == ['Copy connect', 'Online', 'Stats', 'Top'] and 'RustMaps' in labels
        stats_click = FakeInteraction()
        await next(c for c in view.children if c.label == 'Stats').callback(stats_click)
        s = stats_click.sent()['embed']
        values = [f.value for f in s.fields]
        assert 'Peak **200**' in s.description and 'best **#12**' in values[0] and '**1,200**' in values and '**100**' in values
        assert values[-1].startswith('**1** · 10 min')
        top = FakeInteraction()
        await cmd(bot, 'leaderboard')(top, '5931597', 7)
        lb = top.sent()
        assert '🥇 **Grinder0** · 10 h' in lb['embed'].description
        page2 = FakeInteraction()
        await next(c for c in lb['view'].children if str(getattr(c, 'emoji', '')) == '▶️').callback(page2)
        assert 'Grinder10' in page2.response.calls[-1][2]['embed'].description
        search = FakeInteraction()
        await cmd(bot, 'serversearch')(search, '', 'US', 0, '2', '3', None, 3, None)
        desc = search.sent()['embed'].description
        assert 'Trio 2x Fresh' in desc and 'Vanilla Solo' not in desc
        picker = find(search.sent()['view'], placeholder='Open a server card')
        opened = FakeInteraction(values=['1'])
        await picker.callback(opened)
        assert '🖥️' in opened.sent()['embed'].title
        r = FakeInteraction('es-ES')
        await cmd(bot, 'rust')(r)
        assert '113,122' in r.sent()['embed'].description
    run(go())


def test_player_on_a_server_shows_hours_and_graph(bot):
    async def go():
        use(bot)
        i = FakeInteraction()
        await cmd(bot, 'player')(i, STEAMID, '5931597')
        e = i.sent()['embed']
        assert '**20.0 h**' in str(e.fields) and '6.0 h** in total' in str(e.fields) and '```' in str(e.fields)
    run(go())


def test_version_update_and_restart_are_owner_only(bot):
    async def go():
        v = FakeInteraction()
        with patch.object(maintenance, 'git_info', AsyncMock(return_value={'commit': 'abc1234', 'date': 1790000000, 'subject': 'Ship it', 'branch': 'main'})):
            await cmd(bot, 'version')(v)
        e = v.sent()['embed']
        assert e.title.startswith('🏷️ RuxtBot 3.') and 'abc1234' in e.fields[0].value and 'view' not in v.sent()
        stranger = FakeInteraction()
        await cmd(bot, 'update')(stranger)
        assert 'Only the bot owner' in stranger.sent()['embed'].description
        bot.is_owner = AsyncMock(return_value=True)
        owner = FakeInteraction()
        owner.client = bot
        with patch.object(maintenance, 'update', AsyncMock(return_value=('update.done', '• abc Fix', True))), \
                patch.object(maintenance, 'restart', AsyncMock()) as restart, patch('asyncio.create_task') as task:
            await cmd(bot, 'update')(owner)
            assert 'Updated' in owner.sent()['embed'].description and task.called
            again = FakeInteraction()
            again.client = bot
            await cmd(bot, 'restart')(again)
            assert 'Restarting' in again.sent()['embed'].description
            restart.assert_called()
    run(go())


def test_upkeep_uses_the_server_multiplier(bot):
    async def go():
        use(bot)
        i = FakeInteraction()
        await cmd(bot, 'upkeep')(i, stone=100, server='5931597')
        e = i.sent()['embed']
        assert 'upkeep ×0.5' in e.description and '**2,400** / day' in e.fields[0].value   # 100 × 300 × 16% × 0.5
    run(go())


def test_clickable_commands_and_welcome(bot):
    from rustbot.ui import linkify
    assert linkify('`/sv` · `/who player:1`', {'sv': 42, 'who': 7}) == '</sv:42> · `/who player:1`'
    assert linkify('`/sv`', {}) == '`/sv`'

    async def go():
        bot.command_ids = {'sv': 11, 'server': 12, 'who': 13, 'examples': 14}
        h = FakeInteraction()
        await cmd(bot, 'help')(h)
        text = '\n'.join(i.content for i in h.sent()['view'].walk_children() if isinstance(getattr(i, 'content', None), str))
        assert '</sv:11>' in text and '</server:12>' in text
        ex = FakeInteraction()
        await cmd(bot, 'examples')(ex)
        text = '\n'.join(i.content for i in ex.sent()['view'].walk_children() if isinstance(getattr(i, 'content', None), str))
        assert '`/who player:76561198848618940`' in text            # commands with options stay copyable
        me = SimpleNamespace(id=1)
        channel = SimpleNamespace(permissions_for=lambda _: SimpleNamespace(send_messages=True), send=AsyncMock())
        guild = SimpleNamespace(id=1, me=me, system_channel=channel, text_channels=[], preferred_locale='es-ES')
        await bot.on_guild_join(guild)
        e = channel.send.call_args.kwargs['embed']
        assert e.title.startswith('👋 ¡Gracias') and '</sv:11>' in e.description
        assert [c.label for c in channel.send.call_args.kwargs['view'].children] == ['Ver ejemplos']
    run(go())


def test_binds_guide_is_public_and_split_by_part(bot):
    import re
    from rustbot.info_commands import split_sections

    async def go():
        i = FakeInteraction()
        await cmd(bot, 'binds')(i)
        first = i.response.calls[0]
        rest = [c.args[0] for c in i.followup.send.call_args_list]
        messages = [first[1][0], *rest]
        assert len(messages) == 3 and all(len(m) <= 2000 for m in messages)
        assert [m.split('\n')[0] for m in messages] == ['# 🤖 RUXTBOT — MOVIMIENTO, COMBATE Y FOV', '# 🤖 RUXTBOT — AUDIO, AIM Y RENDIMIENTO',
                                                        '# 🤖 RUXTBOT — ITEMS, CHAT Y UTILIDADES']
        text = '\n'.join(messages)
        assert 'ZERGDOS' not in text and '🐷' not in text and not re.findall(r':[a-z_]+:', text)   # bots must send real emoji
        assert 'bind x +meta.if_true "graphics.fov 70";+meta.if_false "graphics.fov 90"' in text
        assert 'gametip.showgametip \\"<#ff0000>On Live: <#00ff00>M2cGTTV\\""' in text
        assert all(m.count('```') % 2 == 0 for m in messages) and 'ephemeral' not in first[2]
    run(go())
    long = '# T\n' + '\n\n'.join(f'**{n}**\n```\nbind {n} x\n```' for n in range(200))
    chunks = split_sections(long)
    assert all(len(c) <= 2000 and c.count('```') % 2 == 0 for c in chunks) and len(chunks) > 1


def test_server_suggestions_follow_the_chosen_player(bot):
    async def go():
        use(bot)
        for command in ('player', 'sessions', 'track'):
            i = FakeInteraction()
            i.namespace = SimpleNamespace(player='1128280744')
            choices = await bot.tree.get_command(command)._params['server'].autocomplete(i, '')
            mine = [c for c in choices if c.value != '*']
            assert mine[0].value == '5931597' and mine[0].name.startswith('🟢 Rusty Moose') and mine[0].name.endswith('· 2 h'), command
        # A SteamID linked in this Discord also works; an unknown name falls back to the normal list.
        bot.store.remember_player(1, 'KingGallardo', STEAMID, '1128280744')
        linked = FakeInteraction()
        linked.namespace = SimpleNamespace(player=STEAMID)
        assert (await bot.tree.get_command('player')._params['server'].autocomplete(linked, ''))[0].value == '5931597'
        unknown = FakeInteraction()
        unknown.namespace = SimpleNamespace(player='nobody here')
        assert not any(c.name.startswith('🟢') for c in await bot.tree.get_command('player')._params['server'].autocomplete(unknown, 'rust'))
    run(go())


def test_titles_are_not_markdown_escaped(bot):
    async def go():
        use(bot)
        s = FakeInteraction()
        await cmd(bot, 'serverstats')(s, '5931597', 7)
        assert s.sent()['embed'].title.startswith('📈 Rusty Moose |US Medium|')
        top = FakeInteraction()
        await cmd(bot, 'leaderboard')(top, '5931597', 7)
        assert chr(92) not in top.sent()['embed'].title   # no backslashes
    run(go())


def test_who_is_public_but_errors_stay_private(bot):
    async def go():
        use(bot)
        i = FakeInteraction()
        await cmd(bot, 'who')(i, '1128280744')
        assert i.response.calls[0] == ('defer', (), {'ephemeral': False, 'thinking': True})
        sent = i.sent()
        assert sent['ephemeral'] is False and sent['embeds']
        stranger = FakeInteraction(user_id=99)
        assert await sent['view'].interaction_check(stranger) is True       # anyone can press Watch / Sessions
        wait = FakeInteraction()
        await cmd(bot, 'who')(wait, '1128280744')
        assert wait.response.calls[-1][2]['ephemeral'] is True              # cooldown notice: only the requester
        bad = FakeInteraction(user_id=50)
        await cmd(bot, 'who')(bad, '!!!')
        assert bad.sent()['ephemeral'] is True
        private = FakeInteraction(user_id=51)
        await cmd(bot, 'who')(private, '1128280744', share=False)
        assert private.sent()['ephemeral'] is True
    run(go())


def test_copy_buttons_send_plain_ids(bot):
    from rustbot.who import build_embeds

    async def go():
        use(bot)
        w = FakeInteraction()
        await cmd(bot, 'who')(w, STEAMID, '1128280744')
        copy = next(b for b in w.sent()['view'].children if getattr(b, 'label', '') == 'Copy IDs')
        clicked = FakeInteraction(user_id=99)
        await copy.callback(clicked)
        text, kwargs = clicked.response.calls[-1][1][0], clicked.response.calls[-1][2]
        assert text.split('\n') == [f'{STEAMID} — SteamID64', 'STEAM_0:0:444176606 — SteamID', '[U:1:888353212] — SteamID3',
                                    '888353212 — Account ID', '1128280744 — BattleMetrics'] and kwargs['ephemeral']
        f = FakeInteraction()
        await cmd(bot, 'findplayer')(f, 'KingGallardo')
        fc = FakeInteraction()
        await next(b for b in f.sent()['view'].children if getattr(b, 'label', '') == 'Copy IDs').callback(fc)
        assert fc.response.calls[-1][1][0].startswith('1128280744 — KingGallardo')
        o = FakeInteraction()
        await cmd(bot, 'online')(o, '5931597')
        oc = FakeInteraction()
        await next(b for b in o.sent()['view'].children if getattr(b, 'label', '') == 'Copy IDs').callback(oc)
        assert '1128280744 — KingGallardo' in oc.response.calls[-1][1][0]
    run(go())
    report = {'steamid': STEAMID, 'bm_id': None, 'errors': [], 'steam': {'name': 'X', 'online_state': 'in-game', 'game': ''}}
    assert 'In a game' in build_embeds(report, False)[0].description and 'a game' not in build_embeds(report, False, 'es')[0].description


def test_lookups_are_public_errors_private_and_alerts_go_where_requested(bot):
    async def go():
        use(bot)
        bot.store.set_settings(1, 999, 'es', True, 10)                       # an old /settings channel is no longer used
        t = FakeInteraction(admin=False, user_id=20)
        t.channel_id = 55
        await cmd(bot, 'track')(t, 'add', '1128280744')
        assert t.sent()['ephemeral'] is False and {w.channel_id for w in bot.store.watches()} == {55}
        assert '<#55>' in str(t.sent()['embed'].fields)
        other = FakeInteraction(admin=False, user_id=20)                      # same Discord, different channel
        other.channel_id = 77
        bot.get_channel = lambda _: SimpleNamespace(guild=SimpleNamespace(id=1))
        await cmd(bot, 'track')(other, 'remove', '1128280744')
        assert 'removed' in other.sent()['embed'].description and not bot.store.watches()
        for name, args in (('player', ('1128280744', '5931597')), ('presence', ('1128280744',)), ('findplayer', ('KingGallardo',)),
                           ('server', ('5931597',)), ('serverstats', ('5931597',)), ('online', ('5931597',))):
            i = FakeInteraction()
            await cmd(bot, name)(i, *args)
            assert i.sent()['ephemeral'] is False, name
        bad = FakeInteraction()
        await cmd(bot, 'player')(bad, 'nobody known', '5931597')
        assert bad.sent()['ephemeral'] is True and "don't know" in bad.sent()['embed'].description
        missing = FakeInteraction(user_id=123)
        await cmd(bot, 'serverstats')(missing)
        assert missing.sent()['ephemeral'] is True
        w = FakeInteraction()
        await cmd(bot, 'wipealert')(w, 'add', '5931597')
        assert w.sent().get('ephemeral') is not True
    run(go())


def test_cctv_codes_are_public_with_one_copyable_block_per_code(bot):
    import re

    async def go():
        i = FakeInteraction()
        await cmd(bot, 'cctv')(i)
        first = i.response.calls[0]
        messages = [first[1][0], *(c.args[0] for c in i.followup.send.call_args_list)]
        assert 'ephemeral' not in first[2] and messages[0].startswith('# 📷 Códigos CCTV · Computer Station')
        assert all(len(m) <= 2000 and m.count('```') % 2 == 0 for m in messages)
        text = '\n'.join(messages)
        assert re.findall(r'^## (.+)$', text, re.M) == ['🛢️ Oil Rig chico', '🛢️ Oil Rig grande', '🚢 Cargo Ship', '☢️ Missile Silo',
                                                         '⛴️ Ferry Terminal', '🏘️ Outpost', '🎰 Bandit Camp', '🛰️ Dome', '🏙️ Radtown', '✈️ Airfield']
        # Each code sits alone in its own block, so Discord's copy button copies just that code.
        codes = re.findall(r'```\n([A-Z0-9]+)\n```', text)
        assert len(codes) == text.count('```') // 2 == len(set(codes)) == 46
        assert {'OILRIG1HELI', 'OILRIG2L6D', 'CARGOHOLD2', 'SILOMISSILE', 'COBALT1', 'RADTOWNSBL', 'AIRFIELDHELIPAD'} <= set(codes)
        assert 'LAB1234' in text
    run(go())




def test_gamma_card_opens_a_private_wizard_in_each_users_language(bot):
    import re
    from types import SimpleNamespace
    from test_integration import text_of
    from rustbot.gamma import STEPS, GammaButton, KeyMenu, KeysModal, compact, gamma_script, parse_key

    def controls(view):
        return {getattr(c, 'custom_id', None): c for c in view.walk_children() if getattr(c, 'custom_id', None)}

    def in_wizard(locale='es-ES', **kwargs):
        i = FakeInteraction(locale, **kwargs)
        i.message = SimpleNamespace(flags=SimpleNamespace(ephemeral=True))
        return i

    async def go():
        # The public card: short, with Start, a quick download and the AutoHotkey page.
        i = FakeInteraction('es-ES')
        await cmd(bot, 'gamma')(i, key='XButton1', reset='F8')
        card = i.response.calls[0][2]
        assert 'ephemeral' not in card
        card['view'].to_components()
        assert 'Ve de noche en Rust' in text_of(card['view']) and '**Mouse 4**' in text_of(card['view'])
        ids = controls(card['view'])
        assert ids['gamma:start:1:XButton1:F8'].item.label == 'Empezar' and ids['gamma:download:0:XButton1:F8'].item.label == 'Descargar (Mouse 4)'

        # Start opens the wizard only for the clicker, in their own language.
        for locale, words in (('en-US', ('Step 1 of 4', 'Install AutoHotkey v2', 'Download v2.0')),
                              ('es-419', ('Paso 1 de 4', 'Instala AutoHotkey v2', 'Download v2.0'))):
            click = FakeInteraction(locale)
            await GammaButton('start', 1, 'XButton1', 'F8').callback(click)
            kind, _, sent = click.response.calls[0]
            assert kind == 'send' and sent['ephemeral'] and sent['files'] == []
            assert all(w in text_of(sent['view']) for w in words)
            assert controls(sent['view'])['gamma:back:1:XButton1:F8'].item.disabled

        # Next / Back move the same message; each step fits Discord's 4000 characters.
        for step in range(1, STEPS + 1):
            for locale in ('en-US', 'es-ES'):
                move = in_wizard(locale)
                await GammaButton('next', step, 'XButton1', 'F8').callback(move)
                kind, _, edit = move.response.calls[0]
                edit['view'].to_components()
                assert kind == 'edit' and len(text_of(edit['view'])) <= 4000
                assert (step == 3) == bool(edit['attachments'])
        assert 'gamma:restart:1:XButton1:F8' in controls(edit['view']) and '**Shift + F8**' in text_of(edit['view'])

        # Step 3 carries the script with the keys and the clicker's language.
        move = in_wizard('es-ES')
        await GammaButton('next', 3, 'XButton1', 'F8').callback(move)
        attached = move.response.calls[0][2]['attachments'][0].fp.read().decode('utf-8-sig')
        assert attached == gamma_script(GammaButton.script, 'XButton1', 'F8', 'es') and 'No se pudo iniciar NVIDIA NVAPI' in attached

        # Step 2: menus and the typed key update the wizard in place.
        pick = in_wizard(values=['F6'])
        await KeyMenu('toggle', 'XButton1', 'F8', 'es').callback(pick)
        kind, _, edit = pick.response.calls[0]
        assert kind == 'edit' and 'gamma:reset:2:F6:F8' in controls(edit['view']) and 'Paso 2 de 4' in text_of(edit['view'])
        assert parse_key('mouse 5') == 'XButton2' and parse_key('f13') == 'F13' and parse_key('Inicio') == 'Home' and parse_key('F10::') is None
        modal = KeysModal('es', 'F10', 'F9')
        modal.toggle._value, modal.reset._value = 'numpad 5', 'x'
        typed = in_wizard()
        await modal.on_submit(typed)
        assert 'gamma:next:3:Numpad5:X' in controls(typed.response.calls[0][2]['view'])
        modal.toggle._value = 'F10::Run'
        bad = in_wizard()
        await modal.on_submit(bad)
        assert 'No conozco' in bad.response.calls[0][1][0]

        en, es = gamma_script(GammaButton.script, 'XButton1', 'F8'), gamma_script(GammaButton.script, 'XButton1', 'F8', 'es')
        assert 'TOGGLE_KEY := "XButton1"' in en and 'RESET_KEY  := "+F8"' in en and '*RunAs' in en and 'Failed to initialize' in en
        assert 'Hotkey(TOGGLE_KEY, ToggleGamma)' in en and '; Mouse 4    -> Toggle' in en and '; Shift + F8 -> Emergency' in en
        assert 'Gamma: ALTO (' in es and 'Failed' not in es

        click = FakeInteraction('es-ES')
        await GammaButton('download', 3, 'XButton1', 'F8').callback(click)
        sent = click.response.calls[0][2]
        assert sent['ephemeral'] and sent['file'].filename == 'gamma.ahk' and sent['file'].fp.read().decode('utf-8-sig') == es

        click = FakeInteraction('en-US')
        await GammaButton('copy', 3, 'XButton1', 'F8').callback(click)
        calls = click.followup.send.call_args_list
        assert len(calls) == 3 and all(len(c.args[0]) <= 2000 and c.kwargs['ephemeral'] for c in calls)
        parts = [re.fullmatch(rf'\*\*{n}/3\*\*\n```ahk\n(.*)\n```', c.args[0], re.S)[1] for n, c in enumerate(calls, 1)]
        assert '\n'.join(parts) == compact(en)   # nothing lost between parts
        assert GammaButton.__discord_ui_compiled_template__.fullmatch('gamma:type:2:F10:F9')
        assert KeyMenu.__discord_ui_compiled_template__.fullmatch('gamma:reset:2:F10:F9')
    run(go())
