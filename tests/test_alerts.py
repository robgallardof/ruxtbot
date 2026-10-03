"""/upkeep, /decay, /wipealert, /serverwatch, /team and "any server" tracking."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from rustbot import __main__ as app
from rustbot.alerts import check_alerts, forced_window, pop_state
from rustbot.base import group_tax, upkeep, upkeep_fraction
from test_integration import STEAMID, FakeInteraction, bot, cmd, iso, run  # noqa: F401  (bot is a fixture)


def test_upkeep_rules():
    assert upkeep_fraction(15) == 0.10
    assert round(upkeep_fraction(100), 4) == 0.16           # 15×10% + 50×15% + 35×20%
    assert round(upkeep_fraction(400), 4) == round((1.5 + 7.5 + 25 + 210 / 3) / 400, 4)
    assert group_tax(4) == 0 and round(group_tax(12), 2) == 0.20 and group_tax(500) == 3.0
    one = upkeep({'stone': (1, 0)})
    assert one['daily'] == {'stones': 30}                    # "a stone wall is 30 stone a day"
    mixed = upkeep({'stone': (10, 4), 'hqm': (1, 0)}, players=12)
    assert mixed['blocks'] == 15 and mixed['daily'] == {'stones': 432, 'metal.refined': 3}


def test_upkeep_and_decay_commands(bot):
    async def go():
        i = FakeInteraction('es-ES')
        await cmd(bot, 'upkeep')(i, stone=100, players=12)
        e = i.sent()['embed']
        assert '100 piezas' in e.title and '16%' in e.description and '+20%' in e.description
        assert '**5,760** / día' in e.fields[0].value                # 100 × 300 × 16% × 1.2
        empty = FakeInteraction()
        await cmd(bot, 'upkeep')(empty)
        assert 'how many pieces' in empty.sent()['embed'].description
        d = FakeInteraction()
        await cmd(bot, 'decay')(d, 'stone', 50)
        assert '2 h 30 min' in d.sent()['embed'].description
        table = FakeInteraction()
        await cmd(bot, 'decay')(table)
        assert '12 h 00 min' in table.sent()['embed'].description and '1 h 00 min' in table.sent()['embed'].description
    run(go())


def test_forced_wipe_window_and_population_states():
    nov = datetime(2026, 11, 5, 19, 0, tzinfo=timezone.utc)   # first Thursday, 2 PM US Eastern (EST)
    assert forced_window(datetime(2026, 11, 5, 18, 30, tzinfo=timezone.utc)) == ('soon', nov)
    assert forced_window(datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)) == ('live', nov)
    assert forced_window(datetime(2026, 11, 10, tzinfo=timezone.utc)) is None
    assert pop_state(190, 150, None) == 'above' and pop_state(10, 150, 20) == 'below' and pop_state(100, 150, 20) == 'mid'


def channel_for(bot):
    channel = SimpleNamespace(guild=SimpleNamespace(id=1, roles=[]), send=AsyncMock())
    bot.get_channel = lambda _: channel
    return channel


def server(players=190, last_wipe=None):
    return {'attributes': {'name': 'Rusty Moose |US Medium|', 'players': players, 'maxPlayers': 200, 'ip': '1.2.3.4', 'port': 28015,
                           'details': {'rust_last_wipe': last_wipe or iso(60 * 24), 'rust_queued_players': 3}}}


def test_wipealert_pings_once_when_the_server_wipes(bot):
    async def go():
        i = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'wipealert')(i, 'add', '5931597')
        assert 'Rusty Moose' in i.sent()['embed'].description and 'Last wipe' in i.sent()['embed'].description
        channel = channel_for(bot)
        await check_alerts(bot)                                       # same wipe date: silent
        assert channel.send.await_count == 0
        bot.bm.server = AsyncMock(return_value=server(last_wipe=iso(5)))
        await check_alerts(bot)
        await check_alerts(bot)                                       # only once per wipe
        assert channel.send.await_count == 1
        args = channel.send.call_args
        assert args.args[0] == '<@20>' and 'just wiped' in args.kwargs['embed'].title and args.kwargs['allowed_mentions'].everyone is False
        lst = FakeInteraction()
        await cmd(bot, 'wipealert')(lst, 'list')
        assert 'Rusty Moose' in lst.sent()['embed'].description
        stranger = FakeInteraction(admin=False, user_id=99)
        await cmd(bot, 'wipealert')(stranger, 'remove', '5931597')
        assert 'Someone else created' in stranger.sent()['embed'].description
        forced = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'wipealert')(forced, forced=True)
        assert 'forced wipe' in forced.sent()['embed'].description
        need = FakeInteraction()
        await cmd(bot, 'wipealert')(need)
        assert 'forced:true' in need.sent()['embed'].description
    run(go())


def test_serverwatch_pings_when_crossing_the_threshold(bot):
    async def go():
        bot.bm.server = AsyncMock(return_value=server(players=190))
        i = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'serverwatch')(i, 'add', '5931597', above=150)
        assert '150+' in i.sent()['embed'].description
        channel = channel_for(bot)
        await check_alerts(bot)
        assert channel.send.await_count == 0                          # already above when created: silent
        bot.bm.server = AsyncMock(return_value=server(players=90))
        await check_alerts(bot)
        bot.bm.server = AsyncMock(return_value=server(players=160))
        await check_alerts(bot)
        assert channel.send.await_count == 1 and 'reached 150+' in channel.send.call_args.kwargs['embed'].title
        bad = FakeInteraction()
        await cmd(bot, 'serverwatch')(bad, 'add', '5931597', above=10, below=50)
        assert 'lower than' in bad.sent()['embed'].description
    run(go())


def test_team_show_and_connection_alerts(bot):
    async def go():
        gid_user = dict(admin=False, user_id=20)
        create = FakeInteraction(**gid_user)
        await cmd(bot, 'team')(create, 'create', 'Rivals')
        assert 'Rivals' in create.sent()['embed'].description
        add = FakeInteraction(**gid_user)
        await cmd(bot, 'team')(add, 'add', 'rivals', STEAMID)
        assert 'KingGallardo' in add.sent()['embed'].description
        show = FakeInteraction()
        await cmd(bot, 'team')(show, 'show', 'Rivals')
        e = show.sent()['embed']
        assert '1/1' in e.title and 'Rusty Moose' in e.description
        choices = await bot.tree.get_command('team')._params['name'].autocomplete(FakeInteraction(), 'riv')
        assert choices[0].value == 'Rivals'
        watch = FakeInteraction(**gid_user)
        await cmd(bot, 'team')(watch, 'watch', 'Rivals')
        channel = channel_for(bot)
        await check_alerts(bot)                                       # baseline
        assert channel.send.await_count == 0
        bot.bm.presence_any = AsyncMock(return_value=(False, '5931597', 'Rusty Moose |US Medium|'))
        await check_alerts(bot)
        assert channel.send.await_count == 1 and '0/1' in channel.send.call_args.kwargs['embed'].title
        bot.bm.presence_any = AsyncMock(return_value=(None, None, None))   # unknown never counts as a change
        await check_alerts(bot)
        assert channel.send.await_count == 1
        stranger = FakeInteraction(admin=False, user_id=99)
        await cmd(bot, 'team')(stranger, 'delete', 'Rivals')
        assert 'Someone else created' in stranger.sent()['embed'].description
        lst = FakeInteraction()
        await cmd(bot, 'team')(lst, 'list')
        assert '🔔' in lst.sent()['embed'].description
    run(go())


def test_track_any_server(bot):
    async def go():
        i = FakeInteraction(admin=False, user_id=20)
        await cmd(bot, 'track')(i, 'add', STEAMID, '*')
        assert bot.store.watches()[0].server_id == '*'
        choices = await bot.tree.get_command('track')._params['server'].autocomplete(FakeInteraction(), '')
        assert choices[0].value == '*'
        bot.store.set_state(bot.store.watches()[0], False)
        channel = channel_for(bot)
        await app.RustBot.poll.coro(bot)
        text = channel.send.call_args.args[0]
        assert text.startswith('<@20> 🟢') and 'connected to **Rusty Moose' in text
    run(go())
