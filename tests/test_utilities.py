import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from rustbot.config import Settings
from rustbot import __main__ as app
from rustbot.utility_commands import comparison


def execute(tmp_path,case):
    async def run():
        captured=[]
        settings=Settings('test',None,str(tmp_path/'state.db'),10,'INFO','data/rust_catalog.yml')
        with patch.object(Settings,'from_env',return_value=settings),patch.object(app.RustBot,'run',lambda bot,token:captured.append(bot)):
            app.main()
        bot=captured[0]
        interaction=SimpleNamespace(guild=SimpleNamespace(id=1),guild_id=1,channel_id=2,user=SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)),response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        try:await case(bot,interaction)
        finally:await bot.bm.client.aclose();bot.store.conn.close()
    asyncio.run(run())


def test_all_commands_register_and_serialize(tmp_path):
    async def case(bot,i):
        assert len(bot.tree.get_commands())==20
        for command in bot.tree.get_commands():command.to_dict(bot.tree)
        assert bot.tree.get_command('raid').get_parameter('method').autocomplete
    execute(tmp_path,case)


def test_raidplan_rounds_each_target_before_multiplication(tmp_path):
    async def case(bot,i):
        await bot.tree.get_command('raidplan').callback(i,'hqdoor','c4',2)
        e=i.response.send_message.call_args.kwargs['embed']
        assert '6 ×' in e.description and '13,200 Sulfur' in e.description
    execute(tmp_path,case)


def test_comparison_unknown_costs_last(tmp_path):
    async def case(bot,i):
        rows=comparison(bot.catalog,bot.catalog.raid('hqdoor'))
        assert 'costo no verificado' in rows[-1]
        assert any('6,600 azufre' in row and 'C4' in row for row in rows)
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
        assert 'administrador' in i.response.send_message.call_args.args[0]
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
        assert 'No publicado' in i.followup.send.call_args.kwargs['embed'].description
    execute(tmp_path,case)
