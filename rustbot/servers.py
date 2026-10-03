import json
import re
from pathlib import Path


def profile_id(value: str) -> str:
    match = re.fullmatch(r'(?:https://www\.battlemetrics\.com/players/)?([0-9]{1,16})/?', value.strip())
    if not match:
        raise ValueError('Usa el enlace del perfil de BattleMetrics, no un SteamID.')
    return match[1]


class ServerDirectory:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding='utf-8'))['servers']

    def search(self, query: str):
        return [s for s in self.rows if query.casefold() in s['name'].casefold()][:25]

    def resolve(self, value: str) -> str:
        value = value.removeprefix('https://www.battlemetrics.com/servers/rust/').rstrip('/')
        matches = [s for s in self.rows if s['id'] == value or s['name'].casefold() == value.casefold()]
        if len(matches) != 1:
            raise ValueError('Selecciona un servidor por nombre en las sugerencias.')
        return matches[0]['id']

    def name(self, server_id: str) -> str:
        return next((s['name'] for s in self.rows if s['id'] == server_id), server_id)

    def merge(self, rows):
        merged={r['id']:r for r in self.rows}
        merged.update({r['id']:r for r in rows})
        self.rows=sorted(merged.values(),key=lambda r:r['name'].casefold())
