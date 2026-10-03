"""Minimal BattleMetrics API client with retries and a brake for rate limits."""
import asyncio
from datetime import datetime, timezone
import time
from urllib.parse import urlencode
import httpx


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat().replace('+00:00', 'Z')


def _ts(value) -> int | None:
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except (AttributeError, ValueError, TypeError):
        return None


def fresh_server(server: dict) -> bool:
    """BattleMetrics queried this server successfully in the last 5 minutes, so its player flags are current."""
    attrs = server.get('attributes') or {}
    if attrs.get('status') != 'online' or attrs.get('queryStatus') != 'valid':
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(attrs['updatedAt'].replace('Z', '+00:00'))).total_seconds()
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    return 0 <= age <= 300


def online_state(server: dict) -> str:
    """'online' (confirmed now), 'stale' (BattleMetrics still says online but cannot reach the server) or 'offline'."""
    if (server.get('meta') or {}).get('online') is not True:
        return 'offline'
    return 'online' if fresh_server(server) else 'stale'


def steamid_from(profile: dict) -> str | None:
    """SteamID64 from a profile's identifiers, when the token is allowed to see them."""
    for row in profile.get('included', []):
        attrs = row.get('attributes') or {}
        if row.get('type') == 'identifier' and attrs.get('type') == 'steamID' and str(attrs.get('identifier', '')).isdigit():
            return str(attrs['identifier'])
    return None


class BattleMetrics:
    def __init__(self, token: str | None):
        # blocked_until: after a 429 no request is made until this monotonic time.
        # cache: recent profiles (8 s) so several watches on the same player share one request.
        self.token = token
        self.client = httpx.AsyncClient(timeout=15)
        self.blocked_until = 0.0
        self.cache = {}
        self.identities = None  # Store with identity()/save_identity(): skips quick-match for known SteamIDs

    async def request(self, path: str, *, body: dict | None = None) -> dict:
        """Authenticated GET (or POST with `body`). Retries 5xx with exponential backoff; a 429 blocks the following calls."""
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
        self.cache = {key: value for key, value in self.cache.items() if time.monotonic() - value[0] < 8}
        if len(self.cache) >= 256:
            self.cache.pop(next(iter(self.cache)))
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
            if not fresh_server(server):
                return None
            online = server.get('meta', {}).get('online')
            return online if isinstance(online, bool) else None
        return None

    async def presence_any(self, player_id: str) -> tuple[bool | None, str | None, str | None]:
        """(online, server ID, server name) across every server, with the same freshness rules as player_online.

        True: a fresh, valid server reports the player online. False: the server they were seen on last
        is fresh and reports them offline. None (no server) in every other case.
        """
        data = await self.profile(player_id)
        if data.get('data', {}).get('attributes', {}).get('private'):
            return None, None, None
        servers = [s for s in data.get('included', []) if s.get('type') == 'server']
        fresh = fresh_server
        name = lambda s: (s.get('attributes') or {}).get('name', s.get('id'))
        live = [s for s in servers if fresh(s) and (s.get('meta') or {}).get('online') is True]
        if live:
            return True, live[0]['id'], name(live[0])
        latest = max(servers, key=lambda s: (s.get('meta') or {}).get('lastSeen') or '', default=None)
        if latest and fresh(latest) and (latest.get('meta') or {}).get('online') is False:
            return False, latest['id'], name(latest)
        return None, None, None

    async def search_servers(self, query: str) -> list[dict]:
        """Live Rust servers matching a name, most players first."""
        params = urlencode({'filter[search]': query, 'filter[game]': 'rust', 'page[size]': 10, 'sort': '-players'})
        return (await self.request(f'servers?{params}'))['data']

    async def find_servers(self, search: str = '', country: str | None = None, min_players: int = 0, size: int = 100) -> list[dict]:
        """Up to `size` live Rust servers, most players first. Feature filters are applied by the caller,
        because BattleMetrics ignores or rejects most Rust feature filters (checked 2026-10-03)."""
        params = {'filter[game]': 'rust', 'filter[status]': 'online', 'sort': '-players', 'page[size]': size}
        if search:
            params['filter[search]'] = search
        if country:
            params['filter[countries][]'] = country.upper()
        if min_players:
            params['filter[players][min]'] = min_players
        return (await self.request(f'servers?{urlencode(params)}'))['data']

    async def history(self, server_id: str, kind: str, days: int, resolution: str | None = None) -> list[tuple[int, float]]:
        """(timestamp, value) points of a server history: player-count, rank, time-played, first-time or unique-player."""
        stop = datetime.now(timezone.utc).replace(microsecond=0)
        params = {'start': _iso(stop.timestamp() - days * 86400), 'stop': _iso(stop.timestamp())}
        if resolution:
            params['resolution'] = resolution
        data = (await self.request(f'servers/{server_id}/{kind}-history?{urlencode(params)}')).get('data', [])
        points = []
        for row in data:
            attrs = row.get('attributes') or {}
            try:
                stamp = int(datetime.fromisoformat(attrs['timestamp'].replace('Z', '+00:00')).timestamp())
            except (KeyError, ValueError, AttributeError):
                continue
            if isinstance(attrs.get('value'), (int, float)):
                points.append((stamp, attrs['value']))
        return sorted(points)

    async def outages(self, server_id: str, days: int) -> list[tuple[int, int | None]]:
        """(start, stop) of the server's outages in the last `days` days, newest first; stop None = still down."""
        rows = (await self.request(f'servers/{server_id}/relationships/outages?page[size]=50')).get('data', [])
        cutoff, out = time.time() - days * 86400, []
        for row in rows:
            attrs = row.get('attributes') or {}
            start, stop = _ts(attrs.get('start')), _ts(attrs.get('stop'))
            if start and start >= cutoff:
                out.append((start, stop))
        return sorted(out, reverse=True)

    async def leaderboard(self, server_id: str, days: int | None = None, offset: int = 0, size: int = 10) -> tuple[list[dict], bool]:
        """Players with the most time on a server (all time, or the last `days` days) and whether more pages exist."""
        if days:
            now = time.time()
            period = f'{_iso(now - days * 86400)}:{_iso(now)}'
        else:
            period = 'AT'
        params = urlencode({'filter[period]': period, 'page[size]': size, 'page[offset]': offset})
        data = await self.request(f'servers/{server_id}/relationships/leaderboards/time?{params}')
        rows = [{'id': str(r['id']), 'name': (r.get('attributes') or {}).get('name') or str(r['id']),
                 'seconds': (r.get('attributes') or {}).get('value') or 0, 'rank': (r.get('attributes') or {}).get('rank')} for r in data.get('data', [])]
        return rows, bool((data.get('links') or {}).get('next'))

    async def player_server(self, player_id: str, server_id: str) -> dict:
        """firstSeen, lastSeen, timePlayed and online for one player on one server."""
        return (await self.request(f'players/{player_id}/servers/{server_id}')).get('data', {}).get('attributes') or {}

    async def player_history(self, player_id: str, server_id: str, days: int = 30) -> list[tuple[int, float]]:
        """Seconds played per day on a server (BattleMetrics allows at most three months)."""
        stop = time.time()
        params = urlencode({'start': _iso(stop - min(days, 90) * 86400), 'stop': _iso(stop)})
        data = (await self.request(f'players/{player_id}/time-played-history/{server_id}?{params}')).get('data', [])
        return sorted((stamp, (r.get('attributes') or {}).get('value') or 0) for r in data if (stamp := _ts((r.get('attributes') or {}).get('timestamp'))))

    async def game(self, game_id: str = 'rust') -> dict:
        return (await self.request(f'games/{game_id}')).get('data', {}).get('attributes') or {}

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
        if self.identities and (known := self.identities.identity(target.steamid)):
            return known
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
        return self.verified(target.steamid, ids.pop())

    def verified(self, steamid: str, bm_id: str) -> str:
        """Remember an exact SteamID -> BattleMetrics match and return the ID."""
        if self.identities:
            self.identities.save_identity(steamid, bm_id)
        return bm_id

    async def verify_by_name(self, steamid: str, name: str | None) -> str | None:
        """Plan B when quick-match is denied: among players with exactly this name, the one whose profile lists this SteamID.

        A same-name profile is only accepted when BattleMetrics shows the SteamID on it; otherwise None.
        """
        if not name:
            return None
        rows = await self.search_players(name)
        exact = sorted((p for p in rows if (p.get('attributes') or {}).get('name', '').casefold() == name.casefold()),
                       key=lambda p: (p.get('attributes') or {}).get('updatedAt') or '', reverse=True)[:3]
        for row in exact:
            detail = await self.request(f"players/{row['id']}?include=identifier")
            if steamid_from(detail) == steamid:
                return self.verified(steamid, str(row['id']))
        return None

    async def server_players(self, server_id: str) -> tuple[dict, list[dict]]:
        """(server attributes, online players) with the start of each current session when BattleMetrics shares it."""
        try:
            data = await self.request(f'servers/{server_id}?include=player,session')
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            data = await self.request(f'servers/{server_id}?include=player')
        started = {}
        for row in data.get('included', []):
            if row.get('type') == 'session' and not (row.get('attributes') or {}).get('stop'):
                pid = ((row.get('relationships') or {}).get('player') or {}).get('data', {}).get('id')
                if pid:
                    started[str(pid)] = (row.get('attributes') or {}).get('start')
        players = [{'id': str(r['id']), 'name': (r.get('attributes') or {}).get('name') or str(r['id']), 'start': started.get(str(r['id']))}
                   for r in data.get('included', []) if r.get('type') == 'player' and r.get('id')]
        players.sort(key=lambda p: p['start'] or '9999')
        return data['data'], players

    async def sessions(self, player_id: str, server_id: str | None = None) -> dict:
        params = {'include': 'server', 'page[size]': 10}
        if server_id:
            params['filter[servers]'] = server_id
        return await self.request(f'players/{player_id}/relationships/sessions?{urlencode(params)}')
