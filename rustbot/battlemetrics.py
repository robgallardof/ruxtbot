"""Minimal BattleMetrics API client with retries and a brake for rate limits."""
import asyncio
from datetime import datetime, timezone
import time
from urllib.parse import urlencode
import httpx


class BattleMetrics:
    def __init__(self, token: str | None):
        # blocked_until: after a 429 no request is made until this monotonic time.
        # cache: recent profiles (8 s) so several watches on the same player share one request.
        self.token = token
        self.client = httpx.AsyncClient(timeout=15)
        self.blocked_until = 0.0
        self.cache = {}

    async def request(self, path: str, *, body: dict | None = None) -> dict:
        """Authenticated GET. Retries 5xx with exponential backoff; a 429 blocks the following calls."""
        if not self.token:
            raise PermissionError('BattleMetrics is not configured')
        if time.monotonic() < self.blocked_until:
            raise RuntimeError('BattleMetrics rate limit cooldown')
        for attempt in range(3):
            headers = {'Authorization': f'Bearer {self.token}'}
            if body is None:
                r = await self.client.get('https://api.battlemetrics.com/' + path, headers=headers)
            else:
                r = await self.client.post('https://api.battlemetrics.com/' + path, headers=headers, json=body)
            if r.status_code == 429:
                try:
                    delay = float(r.headers.get('Retry-After', '60'))
                except ValueError:
                    delay = 60
                self.blocked_until = time.monotonic() + max(10, delay)
                r.raise_for_status()
            if r.status_code not in (500, 502, 503, 504):
                r.raise_for_status()
                return r.json()
            await asyncio.sleep(2 ** attempt)
        r.raise_for_status()
        raise RuntimeError('Unexpected BattleMetrics response')

    async def server(self, server_id: str) -> dict:
        return (await self.request(f'servers/{server_id}'))['data']

    async def profile(self, player_id: str) -> dict:
        cached = self.cache.get(player_id)
        if cached and time.monotonic() - cached[0] < 8:
            return cached[1]
        data = await self.request(f'players/{player_id}?include=server')
        self.cache[player_id] = (time.monotonic(), data)
        return data

    async def player_online(self, server_id: str, player_id: str) -> bool | None:
        """True/False only with an explicit, fresh (< 5 min) observation; None in every other case."""
        # Legacy SteamID watches remain unknown, never treated as disconnected.
        if not player_id.startswith('bm:'):
            return None
        data = await self.profile(player_id[3:])
        if data.get('data', {}).get('attributes', {}).get('private'):
            return None
        for server in data.get('included', []):
            if server.get('type') != 'server' or server.get('id') != server_id:
                continue
            attrs = server.get('attributes', {})
            if attrs.get('status') != 'online' or attrs.get('queryStatus') != 'valid':
                return None
            try:
                updated = datetime.fromisoformat(attrs['updatedAt'].replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - updated).total_seconds()
                if not 0 <= age <= 300:
                    return None
            except (KeyError, ValueError, TypeError):
                return None
            online = server.get('meta', {}).get('online')
            return online if isinstance(online, bool) else None
        return None

    async def search_servers(self, query: str) -> list[dict]:
        """Live Rust servers matching a name, most players first."""
        params = urlencode({'filter[search]': query, 'filter[game]': 'rust', 'page[size]': 10, 'sort': '-players'})
        return (await self.request(f'servers?{params}'))['data']

    async def search_players(self, name: str) -> list[dict]:
        """Players by name (the public API cannot search by SteamID)."""
        query = urlencode({'filter[search]': name, 'page[size]': 25})
        return (await self.request(f'players?{query}'))['data']

    async def resolve_player(self, value: str) -> str:
        """Resolve an exact Steam identifier; never infer identity from a name."""
        from .servers import profile_id
        from .who import parse_target
        try:
            return profile_id(value)
        except ValueError:
            pass
        target = parse_target(value)
        if not target.steamid:
            raise ValueError('identity.input')
        payload = {'data': [{'type': 'identifier', 'attributes': {'type': 'steamID', 'identifier': target.steamid}}]}
        try:
            result = await self.request('players/quick-match', body=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ValueError('identity.permission') from exc
            raise
        ids = set()
        for row in result.get('data', []):
            attrs = row.get('attributes') or {}
            player = (row.get('relationships') or {}).get('player', {}).get('data') or {}
            if row.get('type') == 'identifier' and attrs.get('type') == 'steamID' and attrs.get('identifier') == target.steamid and player.get('type') == 'player' and str(player.get('id', '')).isdigit():
                ids.add(str(player['id']))
        if not ids:
            raise ValueError('identity.missing')
        if len(ids) != 1 or (result.get('links') or {}).get('next'):
            raise ValueError('identity.ambiguous')
        return ids.pop()

    async def sessions(self, player_id: str, server_id: str | None = None) -> dict:
        params = {'include': 'server', 'page[size]': 10}
        if server_id:
            params['filter[servers]'] = server_id
        return await self.request(f'players/{player_id}/relationships/sessions?{urlencode(params)}')
