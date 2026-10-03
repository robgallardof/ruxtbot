"""Server directory (name <-> BattleMetrics ID), BattleMetrics ID parsing and server autocomplete."""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from discord import app_commands


ANY = '*'  # pseudo server: "any server" watches


def profile_id(value: str) -> str:
    """BattleMetrics player ID: the bare number (a pasted profile link is tolerated too)."""
    match = re.fullmatch(r'(?:https?://(?:www\.)?battlemetrics\.com/players/)?([0-9]{1,16})/?', value.strip())
    if not match:
        raise ValueError('not a BattleMetrics player ID')
    return match[1]


class ServerDirectory:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding='utf-8'))['servers']

    def search(self, query: str):
        """Up to 25 name matches: the maximum Discord autocomplete accepts."""
        return [s for s in self.rows if query.casefold() in s['name'].casefold()][:25]

    def resolve(self, value: str) -> str:
        """BattleMetrics server ID from an ID, exact name (or a pasted link).

        Any numeric ID is accepted, even outside the directory; names must match exactly one server
        so the wrong server is never used.
        """
        value = re.sub(r'^https?://(?:www\.)?battlemetrics\.com/servers/rust/', '', value.strip()).rstrip('/')
        if value == ANY:
            return ANY
        if re.fullmatch(r'[0-9]{1,12}', value):
            return value
        matches = [s for s in self.rows if s['name'].casefold() == value.casefold()]
        if len(matches) != 1:
            raise ValueError('pick a server from the suggestions')
        return matches[0]['id']

    def name(self, server_id: str) -> str:
        if server_id == ANY:
            return '🌍'
        return next((s['name'] for s in self.rows if s['id'] == server_id), server_id)

    def merge(self, rows):
        """Add/update imported servers; new names replace old ones."""
        merged = {r['id']: r for r in self.rows}
        merged.update({r['id']: r for r in rows})
        self.rows = sorted(merged.values(), key=lambda r: r['name'].casefold())


def server_autocomplete(bot, include_any: bool = False):
    """Directory matches first; when the directory has few, live BattleMetrics results fill the list.

    Live searches need 3+ characters, are cached for a minute and give up after 2 s, because Discord
    drops autocomplete answers after 3 s and every keystroke triggers one.
    """
    cache: dict[str, tuple[float, list[dict]]] = {}
    last_live = [0.0]  # at most one live search per second, so typing never eats the tracker's rate limit

    async def complete(interaction, current: str):
        rows = [{'id': r['id'], 'name': r['name']} for r in bot.directory.search(current)]
        query = current.strip().casefold()
        if len(rows) < 5 and len(query) >= 3 and not query.isdigit() and bot.bm.token:
            hit = cache.get(query)
            if hit and time.monotonic() - hit[0] < 60:
                live = hit[1]
            elif time.monotonic() - last_live[0] < 1:
                live = []
            else:
                last_live[0] = time.monotonic()
                try:
                    found = await asyncio.wait_for(bot.bm.search_servers(current), 2)
                    live = [{'id': str(s['id']), 'name': f"{s['attributes'].get('name', s['id'])}"[:80] + f" · 👥 {s['attributes'].get('players', 0)}"} for s in found]
                except Exception as exc:
                    logging.debug('live server autocomplete failed: %r', exc)
                    live = []
                for key in [k for k, (stamp, _) in cache.items() if time.monotonic() - stamp >= 60]:
                    cache.pop(key, None)
                cache[query] = (time.monotonic(), live)
            known = {r['id'] for r in rows}
            rows += [r for r in live if r['id'] not in known]
        choices = [app_commands.Choice(name=r['name'][:100], value=r['id']) for r in rows[:25]]
        if include_any and (not query or any(word.startswith(query) for word in ('any', 'cualquier', 'todos', 'all', '🌍'))):
            choices.insert(0, app_commands.Choice(name='🌍 Any server · Cualquier servidor', value=ANY))
        if query.isdigit() and not any(c.value == query for c in choices):
            choices.insert(0, app_commands.Choice(name=f'ID {query}', value=query))
        return choices[:25]

    return complete
