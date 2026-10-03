"""Cliente mínimo de la API de BattleMetrics con reintentos y freno ante límites de uso."""
import asyncio
from datetime import datetime, timezone
import time
from urllib.parse import urlencode
import httpx


class BattleMetrics:
    def __init__(self, token: str | None):
        # blocked_until: tras un 429 no se hace ninguna petición hasta esta marca de tiempo.
        # cache: perfiles recientes (8 s) para que varias vigilancias del mismo jugador compartan consulta.
        self.token = token
        self.client = httpx.AsyncClient(timeout=15)
        self.blocked_until = 0.0
        self.cache = {}

    async def request(self, path: str) -> dict:
        """GET autenticado. Reintenta errores 5xx con backoff exponencial; un 429 bloquea las siguientes llamadas."""
        if not self.token:
            raise PermissionError('BattleMetrics is not configured')
        if time.monotonic() < self.blocked_until:
            raise RuntimeError('BattleMetrics rate limit cooldown')
        for attempt in range(3):
            r = await self.client.get('https://api.battlemetrics.com/' + path,
                                      headers={'Authorization': f'Bearer {self.token}'})
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
        """True/False solo con una observación explícita y reciente (< 5 min); en cualquier otro caso None."""
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

    async def search_players(self, name: str) -> list[dict]:
        """Busca jugadores por nombre (la API pública no permite buscar por SteamID)."""
        query = urlencode({'filter[search]': name, 'page[size]': 25})
        return (await self.request(f'players?{query}'))['data']
