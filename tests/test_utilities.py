import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from rustbot.config import Settings
from rustbot import __main__ as app
from datetime import datetime, timezone
from rustbot.utility_commands import forced_wipes


def execute(tmp_path,case):
    async def run():
        captured=[]
        settings=Settings('test',None,str(tmp_path/'state.db'),10,'INFO','data/rust_catalog.yml')
        with patch.object(Settings,'from_env',return_value=settings),patch.object(app.RustBot,'run',lambda bot,token:captured.append(bot)):
            app.main()
        bot=captured[0]
        interaction=SimpleNamespace(guild=SimpleNamespace(id=1),guild_id=1,channel_id=2,user=SimpleNamespace(id=7,guild_permissions=SimpleNamespace(administrator=True)),response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        try:await case(bot,interaction)
        finally:await bot.bm.client.aclose();bot.store.conn.close()
    asyncio.run(run())


def test_all_commands_register_and_serialize(tmp_path):
    async def case(bot,i):
        assert len(bot.tree.get_commands())==36
        for command in bot.tree.get_commands():command.to_dict(bot.tree)
        assert bot.tree.get_command('raid').get_parameter('method').autocomplete
    execute(tmp_path,case)




def test_alert_toggle_preserves_channel_interval_and_watches(tmp_path):
    async def case(bot,i):
        bot.store.set_settings(1,2,'es',True,45);bot.store.add('bm:42','1',2)
        await bot.tree.get_command('pausealerts').callback(i)
        assert bot.store.settings(1)==(2,'es',0,45)
        await bot.tree.get_command('resumealerts').callback(i)
        assert bot.store.settings(1)==(2,'es',1,45)
        assert len(bot.store.watches())==1
    execute(tmp_path,case)


def test_sync_filters_non_rust_and_persists(tmp_path):
    async def case(bot,i):
        bot.bm.profile=AsyncMock(return_value={'included':[{'type':'server','id':'999','attributes':{'name':'New Rust'},'relationships':{'game':{'data':{'id':'rust'}}}},{'type':'server','id':'888','attributes':{'name':'Other Game'},'relationships':{'game':{'data':{'id':'ark'}}}}]})
        await bot.tree.get_command('syncservers').callback(i,'https://www.battlemetrics.com/players/42')
        assert bot.directory.resolve('New Rust')=='999'
        assert bot.store.servers()==[{'id':'999','name':'New Rust'}]
    execute(tmp_path,case)


def test_admin_commands_reject_dms(tmp_path):
    async def case(bot,i):
        i.guild=None
        await bot.tree.get_command('pausealerts').callback(i)
        assert bot.store.settings(1) is None
        assert 'server managers' in i.response.send_message.call_args.kwargs['embed'].description
    execute(tmp_path,case)


def test_server_list_paginates_all_imported_servers(tmp_path):
    async def case(bot,i):
        await bot.tree.get_command('servers').callback(i,'',8)
        e=i.response.send_message.call_args.kwargs['embed']
        assert e.title.endswith('8/8')
        assert len(e.description.splitlines())==5
    execute(tmp_path,case)


def test_wipe_missing_schedule_is_explicit(tmp_path):
    async def case(bot,i):
        bot.bm.server=AsyncMock(return_value={'attributes':{'name':'Test','details':{}}})
        await bot.tree.get_command('wipe').callback(i,'2942892')
        assert 'Not published' in i.followup.send.call_args.kwargs['embed'].description
    execute(tmp_path,case)


def test_forced_wipe_is_first_thursday_2pm_eastern():
    # October 2026: first Thursday is the 1st; EDT (UTC-4) -> 18:00 UTC. December: EST (UTC-5) -> 19:00 UTC.
    after = forced_wipes(datetime(2026, 10, 2, tzinfo=timezone.utc), 3)
    assert after[0] == datetime(2026, 11, 5, 19, tzinfo=timezone.utc)
    assert after[1] == datetime(2026, 12, 3, 19, tzinfo=timezone.utc)
    assert forced_wipes(datetime(2026, 9, 30, tzinfo=timezone.utc), 1)[0] == datetime(2026, 10, 1, 18, tzinfo=timezone.utc)
    assert all(d.weekday() == 3 and d.day <= 7 for d in after)


def test_raid_commands_answer_with_picture_layouts(tmp_path):
    async def case(bot,i):
        i.locale='es-ES'
        i.original_response=AsyncMock()
        await bot.tree.get_command('raid').callback(i,'puerta hq',None,'hard')
        view=i.response.send_message.call_args.kwargs['view']
        assert 'Puertas' in '\n'.join(x.content for x in view.walk_children() if isinstance(getattr(x,'content',None),str))
        await bot.tree.get_command('raidbudget').callback(i,5000)
        assert i.response.send_message.call_args.kwargs['ephemeral'] is True
    execute(tmp_path,case)
