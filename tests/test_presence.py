import asyncio
from datetime import datetime, timezone, timedelta
import httpx
import pytest
from rustbot.battlemetrics import BattleMetrics
from rustbot.servers import ServerDirectory, profile_id
from rustbot.tracking import transition
from pathlib import Path

def test_named_servers_and_profile_input():
    d=ServerDirectory(Path('data/servers.json'))
    assert len(d.rows)==75
    assert d.resolve('Rustoria.co - US Mondays')=='12410930'
    assert d.resolve('https://www.battlemetrics.com/servers/rust/5931597')=='5931597'
    assert profile_id('https://www.battlemetrics.com/players/1128280744')=='1128280744'
    with pytest.raises(ValueError):profile_id('76561197960265728')
    with pytest.raises(ValueError):profile_id('https://evil.test/1128280744')
    assert len(d.search(''))<=25

@pytest.mark.parametrize('online,status,age,expected',[(True,'online',0,True),(False,'online',0,False),(False,'offline',0,None),(True,'online',600,None),(None,'online',0,None)])
def test_only_explicit_fresh_presence(online,status,age,expected):
    async def run():
        bm=BattleMetrics('test')
        async def request(path):
            return {'data':{'attributes':{}},'included':[{'type':'server','id':'1','attributes':{'status':status,'queryStatus':'valid','updatedAt':(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat()},'meta':{'online':online}}]}
        bm.request=request
        assert await bm.player_online('1','bm:42') is expected
        assert await bm.player_online('missing','bm:42') is None
        assert await bm.player_online('1','76561197960265728') is None
        await bm.client.aclose()
    asyncio.run(run())

def test_unknown_is_never_a_disconnect():
    assert transition(True,None) is None

def test_rate_limit_stops_following_requests():
    async def run():
        bm=BattleMetrics('test');await bm.client.aclose();seen=[]
        def handler(req):
            seen.append(req)
            return httpx.Response(429,headers={'Retry-After':'20'})
        bm.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):await bm.profile('42')
        with pytest.raises(RuntimeError):await bm.profile('42')
        assert len(seen)==1
        await bm.client.aclose()
    asyncio.run(run())


def test_profile_cache_has_a_hard_size_limit():
    async def run():
        bm = BattleMetrics('test')
        async def request(path):
            return {'data': {}, 'included': []}
        bm.request = request
        for pid in range(300):
            await bm.profile(str(pid))
        assert len(bm.cache) <= 256
        await bm.client.aclose()
    asyncio.run(run())
