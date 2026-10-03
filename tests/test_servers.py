"""/me, /sv, /ip, /setserver, /server cards, /serverstats, /leaderboard, /serversearch, /rust, /player extras and /version."""
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
