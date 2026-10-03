import asyncio
from rustbot.battlemetrics import BattleMetrics

def test_rustwho_uses_only_the_requested_public_profile():
    seen = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"steamInfo": {"name": "Test"}}
    class Client:
        async def get(self, url): seen.append(url); return Response()
    client = BattleMetrics(None)
    client.client = Client()
    result = asyncio.run(client.rustwho_profile('76561197960265728'))
    assert result['steamInfo']['name'] == 'Test'
    assert seen == ['https://fetch-v1.rustwho.com/stats/public/76561197960265728']
