import asyncio
import json
import httpx
import pytest
from rustbot.battlemetrics import BattleMetrics

ID = '76561198848618940'

def match(pid='42', steam=ID):
    return {'type': 'identifier', 'attributes': {'type': 'steamID', 'identifier': steam},
            'relationships': {'player': {'data': {'type': 'player', 'id': pid}}}}


def resolve(payload, status=200):
    async def run():
        bm = BattleMetrics('test-token')
        await bm.client.aclose()
        def handler(request):
            assert request.method == 'POST'
            assert request.url.path == '/players/quick-match'
            assert json.loads(request.content)['data'][0]['attributes'] == {'type': 'steamID', 'identifier': ID}
            return httpx.Response(status, json=payload)
        bm.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await bm.resolve_player(ID)
        finally:
            await bm.client.aclose()
    return asyncio.run(run())


def test_exact_match_contract():
    assert resolve({'data': [match(), match()]}) == '42'


@pytest.mark.parametrize('payload,key', [
    ({'data': []}, 'identity.missing'),
    ({'data': [match(steam='76561198848618941')]}, 'identity.missing'),
    ({'data': [match(), match('43')]}, 'identity.ambiguous'),
    ({'data': [match()], 'links': {'next': 'more'}}, 'identity.ambiguous'),
])
def test_no_false_identity(payload, key):
    with pytest.raises(ValueError, match=key):
        resolve(payload)


def test_permission_denied():
    with pytest.raises(ValueError, match='identity.permission'):
        resolve({}, 403)


def test_numeric_bm_id_does_not_call_api():
    async def run():
        bm = BattleMetrics(None)
        try:
            assert await bm.resolve_player('1128280744') == '1128280744'
        finally:
            await bm.client.aclose()
    asyncio.run(run())
