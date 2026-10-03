"""/who: full player profile combining Steam, RustWho and BattleMetrics.

All sources are queried in parallel; a failing source never breaks the reply,
it is just listed in the footer. Name history is merged from every source.
"""
from __future__ import annotations
import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
import discord
import httpx
from discord import app_commands
from .battlemetrics import online_state, steamid_from
from .i18n import lang_for, t
from .players import expand, hub, player_autocomplete, player_error, remember, scope_of
from .servers import profile_id
from .tracking import STEAMID64_MIN as STEAM64_BASE, valid_steamid64
from .ui import ORANGE, RED, STEAM_BLUE, YELLOW, OwnedView, error_embed

RUST_APP_ID = 252490
COOLDOWN_SECONDS = 10
MAX_NAMES = 15
HEADERS = {'User-Agent': 'Mozilla/5.0 (RuxtBot; +https://github.com/robgallardof/ruxtbot)', 'Accept-Language': 'en'}


class VanityNotFound(ValueError):
    """No Steam profile uses that custom URL."""

    def __init__(self, vanity: str):
        super().__init__(vanity)
        self.vanity = vanity


@dataclass(frozen=True)
class Target:
    steamid: str | None = None
    vanity: str | None = None
    bm_id: str | None = None


def parse_target(value: str) -> Target:
    """Accepts SteamID64/2/3, a vanity name, or Steam, steamid.io, SteamDB, RustWho and BattleMetrics links."""
    v = value.strip().strip('<>').strip()
    if re.fullmatch(r'[0-9]{1,16}', v):
        return Target(bm_id=v)
    if m := re.search(r'battlemetrics\.com/players/(\d{1,16})', v):
        return Target(bm_id=m[1])
    if m := re.search(r'steamid\.io/lookup/([^/?#\s]+)', v):
        return parse_target(m[1])
    if m := re.search(r'steamcommunity\.com/id/([\w-]{2,32})', v):
        return Target(vanity=m[1])
    if m := re.search(r'(?<!\d)(765611\d{11})(?!\d)', v):
        if valid_steamid64(m[1]):
            return Target(steamid=m[1])
    if m := re.fullmatch(r'STEAM_[0-5]:([01]):(\d{1,10})', v, re.I):
        return Target(steamid=str(STEAM64_BASE + int(m[2]) * 2 + int(m[1])))
    if m := re.fullmatch(r'\[?U:1:(\d{1,10})\]?', v, re.I):
        return Target(steamid=str(STEAM64_BASE + int(m[1])))
    if re.fullmatch(r'[A-Za-z_][\w-]{1,31}', v):
        return Target(vanity=v)
    raise ValueError('unrecognized player')


def steam_ids(steamid: str) -> dict[str, str]:
    """Every SteamID format, computed exactly like steamid.io does."""
    account = int(steamid) - STEAM64_BASE
    return {'steam64': steamid, 'steam2': f'STEAM_0:{account % 2}:{account // 2}', 'steam3': f'[U:1:{account}]', 'account': str(account)}


def links(steamid: str | None, bm_id: str | None) -> dict[str, str]:
    out = {}
    if steamid:
        out |= {'Steam': f'https://steamcommunity.com/profiles/{steamid}', 'SteamID I/O': f'https://steamid.io/lookup/{steamid}',
                'SteamDB': f'https://steamdb.info/calculator/{steamid}/?cc=mx', 'RustWho': f'https://www.rustwho.com/stats/{steamid}'}
    if bm_id:
        out['BattleMetrics'] = f'https://www.battlemetrics.com/players/{bm_id}'
    return out


class WhoService:
    """Fetches every source in parallel; one failure never breaks the others."""

    def __init__(self, bm, steam_api_key: str | None = None, client: httpx.AsyncClient | None = None):
        self.bm = bm
        self.steam_api_key = steam_api_key
        self.client = client or httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True)

    async def resolve_vanity(self, vanity: str) -> str:
        r = await self.client.get(f'https://steamcommunity.com/id/{vanity}', params={'xml': 1})
        r.raise_for_status()
        if m := re.search(r'<steamID64>(\d{17})</steamID64>', r.text):
            return m[1]
        raise VanityNotFound(vanity)

    async def steam_profile(self, steamid: str) -> dict:
        """Public profile XML: status, VAC flag, trade ban, limited account, location…"""
        r = await self.client.get(f'https://steamcommunity.com/profiles/{steamid}', params={'xml': 1})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        if root.tag != 'profile':
            raise LookupError(root.findtext('error') or 'Steam profile not found')
        text = lambda tag: (root.findtext(tag) or '').strip()
        return {'name': text('steamID'), 'online_state': text('onlineState'), 'game': (root.findtext('inGameInfo/gameName') or '').strip(),
                'privacy': text('privacyState'), 'avatar': text('avatarFull'), 'vac_banned': text('vacBanned') == '1',
                'trade_ban': text('tradeBanState'), 'limited': text('isLimitedAccount') == '1', 'custom_url': text('customURL'),
                'member_since': text('memberSince'), 'location': text('location'), 'real_name': text('realname'),
                'hours_2wk': text('hoursPlayed2Wk')}

    async def steam_page(self, steamid: str) -> dict:
        """Level and counters (games, badges…) scraped from the public profile page."""
        r = await self.client.get(f'https://steamcommunity.com/profiles/{steamid}/')
        r.raise_for_status()
        out = {}
        if m := re.search(r'friendPlayerLevelNum">(\d+)', r.text):
            out['level'] = int(m[1])
        for label, total in re.findall(r'count_link_label">([^<]+)</span>\s*&nbsp;\s*<span class="profile_count_link_total">\s*([\d,]+)', r.text):
            out[label.strip().casefold()] = int(total.replace(',', ''))
        return out

    async def steam_aliases(self, steamid: str) -> list[dict]:
        """Steam's own public name history (empty when the user cleared it)."""
        r = await self.client.get(f'https://steamcommunity.com/profiles/{steamid}/ajaxaliases')
        r.raise_for_status()
        return r.json() or []

    async def steam_games(self, steamid: str) -> dict | None:
        """Rust hours and game count; only with STEAM_API_KEY."""
        if not self.steam_api_key:
            return None
        r = await self.client.get('https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/',
                                  params={'key': self.steam_api_key, 'steamid': steamid, 'include_played_free_games': 1})
        r.raise_for_status()
        data = r.json().get('response', {})
        games = data.get('games', [])
        rust = next((g for g in games if g.get('appid') == RUST_APP_ID), None)
        return {'count': data.get('game_count'), 'rust_minutes': rust.get('playtime_forever') if rust else None,
                'rust_2wk_minutes': rust.get('playtime_2weeks') if rust else None,
                'total_minutes': sum(g.get('playtime_forever', 0) for g in games) if games else None}

    async def rustwho(self, steamid: str) -> dict:
        r = await self.client.get(f'https://fetch-v1.rustwho.com/stats/public/{steamid}')
        r.raise_for_status()
        return r.json()

    async def bm_detail(self, bm_id: str) -> dict:
        return await self.bm.request(f'players/{bm_id}?include=server,identifier')

    async def bm_candidates(self, name: str, known: set[str] | None = None) -> list[dict]:
        """Up to 5 BattleMetrics profiles named like the player, most likely first.

        `known` holds every name the player used on Steam/RustWho (casefolded). A profile that also used
        those names is far more likely to be the same person, so candidates are ranked by names in common.
        """
        known = (known or set()) | {name.casefold()}
        rows = await self.bm.search_players(name)
        named = [p for p in rows if p['attributes'].get('name', '').casefold() in known]
        top = sorted(named, key=lambda p: p['attributes'].get('updatedAt') or '', reverse=True)[:5]
        details = await asyncio.gather(*(self.bm_detail(p['id']) for p in top), return_exceptions=True)
        for p, d in zip(top, details):
            p['shared'], p['names'] = [], []
            if isinstance(d, dict):
                p['detail'], p['steamid'] = d, steamid_from(d)
                used = list(dict.fromkeys(i['attributes'].get('identifier', '') for i in d.get('included', [])
                                          if i.get('type') == 'identifier' and i['attributes'].get('type') == 'name'))
                p['shared'] = [n for n in used if n.casefold() in known]
                p['names'] = [n for n in used if n.casefold() != name.casefold()][:5]
                servers = [s for s in d.get('included', []) if s.get('type') == 'server']
                p['hours'] = sum((s.get('meta') or {}).get('timePlayed') or 0 for s in servers) / 3600
                p['servers'] = len(servers)
                live = [s for s in servers if online_state(s) == 'online']
                stale = [s for s in servers if online_state(s) == 'stale']
                p['online'] = bool(live)
                p['online_server'] = (live[0].get('attributes') or {}).get('name') if live else None
                p['stale_server'] = (stale[0].get('attributes') or {}).get('name') if stale and not live else None
                p['seen'] = max((ts for s in servers if (ts := iso_ts((s.get('meta') or {}).get('lastSeen')))), default=None)
        # Online first (they are usually the one being looked up), then names in common, then hours.
        top.sort(key=lambda p: (p.get('online', False), bool(p.get('stale_server')), len({n.casefold() for n in p['shared']}), p.get('hours', 0)), reverse=True)
        return top

    async def lookup(self, target: Target, bm_id: str | None = None) -> dict:
        steamid = target.steamid or (await self.resolve_vanity(target.vanity) if target.vanity else None)
        bm_id = bm_id or target.bm_id
        resolution_error = None
        # Only a BattleMetrics ID: its profile may expose the SteamID, which unlocks Steam and RustWho.
        prefetched, prefetch_failed = None, False
        if bm_id and not steamid and self.bm.token:
            try:
                prefetched = await self.bm_detail(bm_id)
                steamid = steamid_from(prefetched)
                if steamid:
                    self.bm.verified(steamid, bm_id)
            except Exception as exc:
                logging.info('who: bm prefetch failed: %r', exc)
                prefetch_failed = True
        if steamid and not bm_id and self.bm.token:
            try:
                bm_id = await self.bm.resolve_player(steamid)
            except ValueError as exc:
                resolution_error = str(exc)
            except Exception:
                resolution_error = 'identity.unavailable'
        jobs = {}
        if steamid:
            jobs |= {'steam': self.steam_profile(steamid), 'page': self.steam_page(steamid), 'aliases': self.steam_aliases(steamid),
                     'games': self.steam_games(steamid), 'rustwho': self.rustwho(steamid)}
        if bm_id and self.bm.token and prefetched is None and not prefetch_failed:
            jobs['bm'] = self.bm_detail(bm_id)
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        report = {'steamid': steamid, 'bm_id': bm_id, 'errors': ['bm'] if prefetch_failed else [], 'resolution_error': resolution_error}
        if prefetched is not None:
            report['bm'] = prefetched
        for key, result in zip(jobs, results):
            if isinstance(result, BaseException):
                logging.info('who: %s failed: %r', key, result)
                report['errors'].append(key)
            else:
                report[key] = result
        name = (report.get('steam') or {}).get('name') or ((report.get('rustwho') or {}).get('steamInfo') or {}).get('name')
        if steamid and not bm_id and name and self.bm.token:
            try:
                report['bm_candidates'] = await self.bm_candidates(name, {n.casefold() for n, _, _ in name_history(report)})
                in_rust = (report.get('steam') or {}).get('online_state') == 'in-game' and (report.get('steam') or {}).get('game') == 'Rust'
                for p in report['bm_candidates']:
                    p['playing_now'] = in_rust and p.get('online', False)
            except Exception as exc:
                logging.info('who: bm search failed: %r', exc)
            # Plan B: a same-name profile that lists this exact SteamID is the player; load it as if quick-match found it.
            verified = [p for p in report.get('bm_candidates') or [] if p.get('steamid') == steamid]
            if len(verified) == 1:
                match = verified[0]
                report.update(bm_id=self.bm.verified(steamid, str(match['id'])), bm=match['detail'], resolution_error=None, bm_candidates=[])
        return report


# ───────────────────────────── Formatting ─────────────────────────────

def esc(value) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


def num(value) -> str:
    if value is None or value == '':
        return '—'
    if isinstance(value, float) and not value.is_integer():
        return f'{value:,.2f}'.rstrip('0').rstrip('.')
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return str(value)


def iso_ts(value: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except (AttributeError, ValueError):
        return None


def clip(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[:limit - 1] + '…'


def check(ok: bool) -> str:
    return '✅' if ok else '⛔'


def name_history(report: dict) -> list[tuple[str, int | None, str]]:
    """Merge names from Steam, RustWho and BattleMetrics: newest first, no duplicates, sources joined."""
    seen: dict[str, tuple[str, int | None, str]] = {}

    def add(name, ts, source):
        name = (name or '').strip()
        if not name:
            return
        shown, latest, sources = seen.get(name.casefold(), (name, None, ''))
        if source not in sources.split('·'):
            sources = f'{sources}·{source}' if sources else source
        if (ts or 0) > (latest or 0):
            shown, latest = name, ts
        seen[name.casefold()] = (shown, latest, sources)

    for alias in report.get('aliases') or []:
        try:
            ts = int(datetime.strptime(alias.get('timechanged', ''), '%d %b, %Y @ %I:%M%p').replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            ts = None
        add(alias.get('newname'), ts, 'Steam')
    for row in ((report.get('rustwho') or {}).get('extraNameHistory') or {}).get('nameHistory') or []:
        add(row.get('name'), iso_ts(row.get('date')), 'RW')
    for row in (report.get('bm') or {}).get('included', []):
        if row.get('type') == 'identifier' and row['attributes'].get('type') == 'name':
            add(row['attributes'].get('identifier'), iso_ts(row['attributes'].get('lastSeen')), 'BM')
    return sorted(seen.values(), key=lambda r: r[1] or 0, reverse=True)


def names_field(report: dict, lang: str) -> tuple[str, str]:
    """(title, value) for the name history block, the first thing shown on a profile."""
    rw = report.get('rustwho') or {}
    names = name_history(report)
    total = ((rw.get('steamExtraInfo') or {}).get('nameHistory') or {}).get('nameHistoryCount')
    title = t(lang, 'who.names.count', n=num(total)) if total and total != '0' else t(lang, 'who.names')
    if not names:
        return title, t(lang, 'who.names.none')
    lines = [f"• **{esc(n)}**" + (f' · <t:{ts}:d>' if ts else '') + f' `{src}`' for n, ts, src in names[:MAX_NAMES]]
    if len(names) > MAX_NAMES:
        lines.append(t(lang, 'who.names.more', n=len(names) - MAX_NAMES))
    locked = (rw.get('extraNameHistory') or {}).get('lockedExtraCount')
    if locked:
        lines.append(t(lang, 'who.names.locked', n=locked))
    lines.append(t(lang, 'who.names.legend'))
    return title, clip('\n'.join(lines))


def steam_embed(report: dict, lang: str = 'en') -> discord.Embed:
    steamid = report['steamid']
    steam = report.get('steam') or {}
    rw = report.get('rustwho') or {}
    info = rw.get('steamInfo') or {}
    bans = rw.get('steamBans') or {}
    extra = rw.get('steamExtraInfo') or {}
    page = report.get('page') or {}
    games = report.get('games') or {}
    name = steam.get('name') or info.get('name') or steamid
    banned = steam.get('vac_banned') or (bans.get('vacBans') or 0) > 0 or (bans.get('gameBans') or 0) > 0

    state = steam.get('online_state')
    status = {'online': t(lang, 'who.status.online'), 'in-game': t(lang, 'who.status.ingame', game=esc(steam.get('game') or 'a game')),
              'offline': t(lang, 'who.status.offline')}.get(state, t(lang, 'who.status.unknown'))
    privacy = t(lang, 'who.privacy.' + steam['privacy']) if steam.get('privacy') in ('public', 'friendsonly', 'private') else ''
    country = steam.get('location') or info.get('country')
    desc = ' · '.join(x for x in (status, privacy, f'🌎 {esc(country)}' if country else '') if x)
    if steam.get('real_name'):
        desc += '\n' + t(lang, 'who.real_name', name=esc(steam['real_name']))
    e = discord.Embed(title=f'👤 {name}', url=f'https://steamcommunity.com/profiles/{steamid}', description=desc, color=RED if banned else STEAM_BLUE)
    if avatar := steam.get('avatar') or info.get('avatar'):
        e.set_thumbnail(url=avatar)

    # Name history goes first: it is the most asked-for part of a lookup.
    title, value = names_field(report, lang)
    e.add_field(name=title, value=value, inline=False)

    ids = steam_ids(steamid)
    rows = [('SteamID64', ids['steam64']), ('SteamID', ids['steam2']), ('SteamID3', ids['steam3']), ('Account ID', ids['account'])]
    if steam.get('custom_url'):
        rows.append(('Custom URL', steam['custom_url']))
    e.add_field(name=t(lang, 'who.ids'), value='```\n' + '\n'.join(f'{k:<11}{v}' for k, v in rows) + '\n```', inline=False)

    account = []
    if created := info.get('timeCreated'):
        account.append(t(lang, 'who.created', ts=created))
    elif steam.get('member_since'):
        account.append(t(lang, 'who.member_since', d=esc(steam['member_since'])))
    if 'level' in page:
        account.append(t(lang, 'who.level', n=page['level']))
    if game_count := games.get('count') or page.get('games'):
        account.append(t(lang, 'who.games', n=num(game_count)))
    if games.get('rust_minutes') is not None:
        line = t(lang, 'who.rust_hours', n=num(round(games['rust_minutes'] / 60)))
        if games.get('rust_2wk_minutes'):
            line += t(lang, 'who.rust_2wk', n=num(round(games['rust_2wk_minutes'] / 60, 1)))
        account.append(line)
    elif steam.get('hours_2wk') not in (None, '', '0.0'):
        account.append(t(lang, 'who.hours_2wk', n=esc(steam['hours_2wk'])))
    for key, label in (('badges', 'who.badges'), ('screenshots', 'who.screenshots'), ('workshop items', 'who.workshop')):
        if page.get(key):
            account.append(t(lang, label, n=num(page[key])))
    if steam:
        account.append(t(lang, 'who.limited', v=t(lang, 'common.yes' if steam.get('limited') else 'common.no')))
    e.add_field(name=t(lang, 'who.account'), value=clip('\n'.join(account) or t(lang, 'who.no_public')), inline=True)

    vac = bans.get('vacBans', 1 if steam.get('vac_banned') else 0)
    game_bans = bans.get('gameBans')
    trade = bans.get('economyBan') or steam.get('trade_ban') or 'none'
    ban_lines = [t(lang, 'who.vac', c=check(not vac), n=num(vac))]
    if game_bans is not None:
        ban_lines.append(t(lang, 'who.game_bans', c=check(not game_bans), n=num(game_bans)))
    if bans:
        ban_lines.append(t(lang, 'who.community', c=check(not bans.get('communityBanned')), v=t(lang, 'who.banned' if bans.get('communityBanned') else 'who.clean')))
    trade_clean = trade.casefold() == 'none'
    ban_lines.append(t(lang, 'who.trade', c=check(trade_clean), v=t(lang, 'who.clean') if trade_clean else esc(trade)))
    if rw.get('serverBanCount') is not None:
        ban_lines.append(t(lang, 'who.server_bans', c='⚠️' if rw['serverBanCount'] else '✅', n=num(rw['serverBanCount'])))
    if (vac or game_bans) and bans.get('daysSinceLastBan'):
        ban_lines.append(t(lang, 'who.last_ban', n=num(bans['daysSinceLastBan'])))
    e.add_field(name=t(lang, 'who.bans'), value='\n'.join(ban_lines), inline=True)

    friends = extra.get('friends') or {}
    if friends and not rw.get('richFriendsLimited') and friends.get('friendsCount') not in (None, '0'):
        e.add_field(name=t(lang, 'who.friends'), value=t(lang, 'who.friends.value', t=num(friends.get('friendsCount')), vac=num(friends.get('vacFriends')),
                                                       game=num(friends.get('gameBanFriends')), trade=num(friends.get('tradeBanFriends')),
                                                       com=num(friends.get('communityBanFriends'))), inline=False)
    return e


# (stat key, English label, Spanish label) grouped by theme.
STAT_GROUPS = [
    (('⚔️ PvP', '⚔️ PvP'), [('kills', 'Kills', 'Kills'), ('deaths', 'Deaths', 'Muertes'), ('headshots', 'Headshots', 'Headshots'),
                           ('wounded', 'Downed', 'Derribados'), ('shotgunHitPlayer', 'Shotgun hits', 'Escopetazos')]),
    (('🔫 Shooting', '🔫 Disparos'), [('bulletsFired', 'Bullets', 'Balas'), ('bulletsHit', 'Bullets hit', 'Balas acertadas'), ('arrowsFired', 'Arrows', 'Flechas'),
                                     ('arrowsHitPlayer', 'Arrow hits', 'Flechas a jugador'), ('shotgunFired', 'Shotgun', 'Escopeta'),
                                     ('rocketsFired', 'Rockets', 'Cohetes'), ('grenadesThrown', 'Grenades', 'Granadas')]),
    (('🏗️ Building', '🏗️ Construcción'), [('buildingsPlaced', 'Placed', 'Bloques puestos'), ('buildingsUpgraded', 'Upgraded', 'Mejoras'),
                                         ('cupboardsOpened', 'TCs opened', 'TC abiertos'), ('wiresConnected', 'Wires', 'Cables'),
                                         ('pipesConnected', 'Pipes', 'Tuberías'), ('blueprintsStudied', 'BPs learned', 'BPs aprendidos')]),
    (('⛏️ Gathering', '⛏️ Recolección'), [('woodGathered', 'Wood', 'Madera'), ('stoneGathered', 'Stone', 'Piedra'), ('metalGathered', 'Metal', 'Metal'),
                                         ('sulfurGathered', 'Sulfur', 'Azufre'), ('clothGathered', 'Cloth', 'Tela'), ('leatherGathered', 'Leather', 'Cuero'),
                                         ('lowGradeGathered', 'Low grade', 'Low grade'), ('scrapGathered', 'Scrap', 'Scrap')]),
    (('🌲 World', '🌲 Mundo'), [('barrelsDestroyed', 'Barrels', 'Barriles'), ('oreHits', 'Ore hits', 'Golpes a nodos'), ('treeHits', 'Tree hits', 'Golpes a árboles'),
                               ('scientistsKilled', 'Scientists', 'Científicos'), ('woundedHealed', 'Revived', 'Revividos'), ('woundedAssisted', 'Assists', 'Asistencias')]),
]


def rust_embed(report: dict, lang: str = 'en') -> discord.Embed | None:
    rw = report.get('rustwho')
    if rw is None:
        return None
    stats = rw.get('rustStats') or {}
    e = discord.Embed(title=t(lang, 'who.rust.title'), url=f"https://www.rustwho.com/stats/{report['steamid']}", color=YELLOW)
    if stats.get('noData') or stats.get('availability') not in (None, 'available'):
        e.description = t(lang, 'who.rust.private')
        return e
    kd = stats.get('kd')
    rating = '🔥' if isinstance(kd, (int, float)) and kd >= 2 else '💪' if isinstance(kd, (int, float)) and kd >= 1 else '🙂'
    e.description = f"{rating} " + t(lang, 'who.rust.summary', kd=num(kd), acc=num(stats.get('accuracyPct')), hs=num(stats.get('headshotPct')))
    if stats.get('pvpScore') is not None:
        e.description += t(lang, 'who.rust.pvp_score', n=num(stats['pvpScore']))
    idx = 1 if lang == 'es' else 0
    for titles, keys in STAT_GROUPS:
        lines = [f'{labels[idx]}: **{num(stats[k])}**' for k, *labels in keys if stats.get(k) is not None]
        if lines:
            e.add_field(name=titles[idx], value='\n'.join(lines), inline=True)
    extra = []
    if stats.get('voiceChatTime'):
        extra.append(t(lang, 'who.rust.voice', n=num(round(stats['voiceChatTime'] / 3600, 1))))
    votes = rw.get('votes') or {}
    if votes.get('availability') == 'available':
        extra.append(f"👍 {num(votes.get('likes', 0))} · 👎 {num(votes.get('dislikes', 0))}")
    if rw.get('altsFound'):
        extra.append(t(lang, 'who.rust.alts', n=num(rw['altsFound'])))
    if extra:
        e.add_field(name=t(lang, 'who.rust.extra'), value='\n'.join(extra), inline=True)
    e.set_footer(text=t(lang, 'who.rust.footer'))
    if observed := iso_ts(stats.get('observedAt')):
        e.timestamp = datetime.fromtimestamp(observed, timezone.utc)
    return e


def bm_embed(report: dict, bm_configured: bool, lang: str = 'en') -> discord.Embed | None:
    data = report.get('bm')
    if data:
        attrs = data['data']['attributes']
        servers = [s for s in data.get('included', []) if s.get('type') == 'server']
        e = discord.Embed(title=f"📊 BattleMetrics · {attrs.get('name', report['bm_id'])}", url=f"https://www.battlemetrics.com/players/{report['bm_id']}", color=ORANGE)
        online = [s for s in servers if online_state(s) == 'online']
        stale = [s for s in servers if online_state(s) == 'stale']
        last = max(servers, key=lambda s: (s.get('meta') or {}).get('lastSeen') or '', default=None)
        if online:
            e.description = t(lang, 'who.bm.online', list=', '.join(f"**{esc(s['attributes']['name'])}**" for s in online[:3]))
        elif stale and (ts := iso_ts((stale[0].get('meta') or {}).get('lastSeen'))):
            e.description = t(lang, 'who.bm.stale', server=esc(stale[0]['attributes']['name']), ts=ts)
        elif last and (ts := iso_ts(last['meta'].get('lastSeen'))):
            e.description = t(lang, 'who.bm.last', ts=ts, server=esc(last['attributes']['name']))
        else:
            e.description = t(lang, 'who.bm.none')
        if attrs.get('private'):
            e.description += '\n' + t(lang, 'who.bm.private')
        seconds = sum((s.get('meta') or {}).get('timePlayed') or 0 for s in servers)
        firsts = [ts for s in servers if (ts := iso_ts((s.get('meta') or {}).get('firstSeen')))]
        e.add_field(name=t(lang, 'who.bm.played'), value=f'**{num(round(seconds / 3600))} h**', inline=True)
        e.add_field(name=t(lang, 'who.bm.servers'), value=f'**{len(servers)}**', inline=True)
        if firsts:
            e.add_field(name=t(lang, 'who.bm.first'), value=f'<t:{min(firsts)}:D>', inline=True)
        top = sorted(servers, key=lambda s: (s.get('meta') or {}).get('timePlayed') or 0, reverse=True)[:6]
        if top:
            lines = []
            for s in top:
                meta = s.get('meta') or {}
                seen = iso_ts(meta.get('lastSeen'))
                dot = {'online': '🟢', 'stale': '🟡'}.get(online_state(s), '▫️')
                lines.append(f"{dot} [{esc(s['attributes']['name'][:48])}](https://www.battlemetrics.com/servers/rust/{s['id']}) — "
                             f"**{num(round((meta.get('timePlayed') or 0) / 3600, 1))} h**" + (f' · <t:{seen}:R>' if seen else ''))
            e.add_field(name=t(lang, 'who.bm.top'), value=clip('\n'.join(lines)), inline=False)
        e.set_footer(text=t(lang, 'who.bm.footer'))
        return e
    if not bm_configured:
        return None
    e = discord.Embed(title='📊 BattleMetrics', color=ORANGE)
    candidates = report.get('bm_candidates') or []
    if candidates:
        lines = []
        best = likely(candidates)
        for n, p in enumerate(candidates, start=1):
            ts = iso_ts(p['attributes'].get('updatedAt'))
            icon = '⭐' if p is best else candidate_dot(p)
            line = f"**{n}.** {icon} [{esc(p['attributes']['name'])}](https://www.battlemetrics.com/players/{p['id']}) · `{p['id']}`" + (' · ' + t(lang, 'who.bm.active', ts=ts) if ts else '')
            shared = [n for n in p.get('shared', []) if n.casefold() != p['attributes']['name'].casefold()]
            if facts := candidate_facts(p, lang):
                line += '\n-# ' + ('🎮 ' + t(lang, 'who.link.playing') + ' · ' if p.get('playing_now') else '') + facts
            if shared:
                line += '\n-# 🔗 ' + t(lang, 'who.bm.shared', names=', '.join(esc(n) for n in shared[:5]))
            elif p.get('names'):
                line += '\n-# ' + t(lang, 'who.bm.candidate_names', names=', '.join(esc(n) for n in p['names']))
            lines.append(line)
        e.description = t(lang, 'who.bm.candidates') + '\n' + '\n'.join(lines) + '\n\n' + t(lang, 'who.bm.link_hint')
    else:
        e.description = t(lang, 'who.bm.no_candidates') + '\n\n' + t(lang, report.get('resolution_error') or 'identity.missing')
    return e


def likely(candidates: list[dict]) -> dict | None:
    """The clearly most likely candidate, or None when nothing tells them apart.

    Strongest hint: Steam says the player is in Rust right now and exactly one candidate is online on
    BattleMetrics. Otherwise: the only candidate sharing the most extra names with the Steam account.
    """
    playing = [p for p in candidates if p.get('playing_now')]
    if len(playing) == 1:
        return playing[0]
    scores = [len({n.casefold() for n in p.get('shared', []) if n.casefold() != p['attributes']['name'].casefold()}) for p in candidates]
    if not scores or max(scores) == 0 or scores.count(max(scores)) > 1:
        return None
    return candidates[scores.index(max(scores))]


def candidate_dot(p: dict) -> str:
    return '🟢' if p.get('online') else '🟡' if p.get('stale_server') else '⚫'


def candidate_facts(p: dict, lang: str) -> str:
    """Plain-text facts that help tell same-name profiles apart (used in select descriptions)."""
    facts = []
    if p.get('online'):
        facts.append(t(lang, 'who.link.online_on', server=p['online_server'][:40]) if p.get('online_server') else t(lang, 'who.link.online'))
    elif p.get('stale_server'):
        facts.append(t(lang, 'who.link.stale', server=p['stale_server'][:40]))
    elif p.get('seen'):
        facts.append(t(lang, 'who.link.seen', d=max(0, int((time.time() - p['seen']) // 86400))))
    if p.get('hours') is not None and 'hours' in p:
        facts.append(f"{num(round(p['hours']))} h")
    if p.get('servers'):
        facts.append(t(lang, 'who.link.servers', n=p['servers']))
    return ' · '.join(facts)


def build_embeds(report: dict, bm_configured: bool = True, lang: str = 'en') -> list[discord.Embed]:
    embeds = []
    if report.get('steamid'):
        embeds.append(steam_embed(report, lang))
        if rust := rust_embed(report, lang):
            embeds.append(rust)
    if bm := bm_embed(report, bm_configured, lang):
        embeds.append(bm)
    if not report.get('steamid'):
        embeds.append(discord.Embed(description=t(lang, 'who.bm_only'), color=YELLOW))
    missing = [{'steam': 'Steam', 'page': 'Steam', 'aliases': 'Steam', 'games': 'Steam API', 'rustwho': 'RustWho', 'bm': 'BattleMetrics'}[k]
               for k in report.get('errors', [])]
    if missing and embeds:
        last = embeds[-1]
        prefix = (last.footer.text + ' · ') if last.footer and last.footer.text else ''
        last.set_footer(text=prefix + t(lang, 'who.no_answer', list=', '.join(dict.fromkeys(missing))))
    # Discord caps all embeds of one message at 6000 characters.
    while sum(len(e) for e in embeds) > 6000 and len(embeds) > 1:
        embeds.pop()
    return embeds


def report_name(report: dict) -> str | None:
    return ((report.get('steam') or {}).get('name') or ((report.get('rustwho') or {}).get('steamInfo') or {}).get('name')
            or (((report.get('bm') or {}).get('data') or {}).get('attributes') or {}).get('name'))


class LinksView(OwnedView):
    """Links to every site, plus optional shortcut buttons (label, emoji, coroutine) that only the requester can use."""

    def __init__(self, steamid: str | None, bm_id: str | None, owner_id: int | None = None, actions=()):
        super().__init__(owner_id, timeout=600)
        emoji = {'Steam': '🎮', 'SteamID I/O': '🆔', 'SteamDB': '💰', 'RustWho': '🦀', 'BattleMetrics': '📊'}
        for label, url in links(steamid, bm_id).items():
            self.add_item(discord.ui.Button(label=label, url=url, emoji=emoji[label]))
        for label, icon, action in actions:
            button = discord.ui.Button(label=label, emoji=icon, style=discord.ButtonStyle.primary)
            button.callback = action
            self.add_item(button)


def steamid_embed(steamid: str, lang: str) -> discord.Embed:
    ids = steam_ids(steamid)
    rows = [('SteamID64', ids['steam64']), ('SteamID', ids['steam2']), ('SteamID3', ids['steam3']), ('Account ID', ids['account'])]
    e = discord.Embed(title=t(lang, 'steamid.title'), color=STEAM_BLUE, url=f'https://steamcommunity.com/profiles/{steamid}')
    e.description = '```\n' + '\n'.join(f'{k:<11}{v}' for k, v in rows) + '\n```'
    e.add_field(name=t(lang, 'steamid.copy'), value=f'`{steamid}`', inline=False)
    e.set_footer(text=t(lang, 'steamid.footer'))
    return e


def shortcut_actions(bot, report: dict, lang: str, in_guild: bool):
    """Buttons under a profile: watch the player and open their sessions without retyping anything."""
    if not report.get('bm_id') or not bot.bm.token:
        return []

    async def watch(interaction):
        await bot.tree.get_command('track').callback(interaction, action='add', player=report['bm_id'])

    async def sessions(interaction):
        await bot.tree.get_command('sessions').callback(interaction, player=report['bm_id'])

    actions = [(t(lang, 'who.button.watch'), '👀', watch)] if in_guild else []
    return actions + [(t(lang, 'who.button.sessions'), '🕒', sessions)]


def register_who(bot, service: WhoService):
    cooldowns: dict[int, float] = {}
    players = player_autocomplete(bot)

    @bot.tree.command(name='who', description='🕵️ Full player profile: Steam, bans, name history, Rust stats, BattleMetrics')
    @app_commands.describe(player='Name you looked up before, SteamID64, STEAM_0 or BattleMetrics player ID',
                           bm_id='BattleMetrics player ID (optional, numbers only)', share='Everyone in the channel sees the profile (default yes; false = only you)')
    @app_commands.autocomplete(player=players)
    async def who(interaction: discord.Interaction, player: str | None = None, bm_id: str | None = None, share: bool = True):
        lang = lang_for(interaction)
        if not player and not bm_id:
            embed, view = hub(bot, interaction, lang)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return
        player = expand(bot, interaction, player) or bm_id
        # Profiles are public by default, but mistakes and waits only ever go to whoever typed the command.
        try:
            target = parse_target(player)
        except ValueError:
            await player_error(bot, interaction, lang, 'identity.input', player, False)
            return
        try:
            bm_id = profile_id(bm_id) if bm_id else None
        except ValueError:
            await interaction.response.send_message(embed=error_embed(t(lang, 'bm.profile_link'), lang=lang), ephemeral=True)
            return
        now = time.monotonic()
        remaining = COOLDOWN_SECONDS - (now - cooldowns.get(interaction.user.id, 0))
        if remaining > 0:
            await interaction.response.send_message(t(lang, 'who.cooldown', s=int(remaining) + 1), ephemeral=True)
            return
        for uid, stamp in list(cooldowns.items()):
            if now - stamp >= COOLDOWN_SECONDS:
                cooldowns.pop(uid, None)
        cooldowns[interaction.user.id] = now
        await show(interaction, lang, target, bm_id, share)

    async def show(interaction, lang, target, bm_id, share):
        """Look the player up and send the profile; shared by /who and the link picker (which skips the cooldown)."""
        if target.steamid and not bm_id:
            bm_id = bot.store.bm_for_steam(scope_of(interaction), target.steamid)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=not share, thinking=True)
        try:
            report = await service.lookup(target, bm_id)
        except VanityNotFound as exc:
            # Not a Steam custom URL either: most likely an in-game name, so offer to search it.
            await drop_public_placeholder(interaction, share)
            await player_error(bot, interaction, lang, 'identity.name', exc.vanity, False)
            return
        except Exception:
            logging.exception('who lookup failed')
            await drop_public_placeholder(interaction, share)
            await interaction.followup.send(embed=error_embed(t(lang, 'who.fail'), lang=lang), ephemeral=True)
            return
        await remember(bot, interaction, bm_id=report['bm_id'], steamid=report['steamid'], name=report_name(report))
        linking = bool(report['steamid'] and not report['bm_id'] and report.get('bm_candidates'))
        # On a public profile anyone can use Watch / Sessions (their replies are private);
        # choosing which BattleMetrics profile to link stays with whoever asked.
        owner = interaction.user.id if linking or not share else None
        view = LinksView(report['steamid'], report['bm_id'], owner, shortcut_actions(bot, report, lang, bool(interaction.guild)))
        if linking:
            view.add_item(link_picker(report, lang, share))
            # Open each candidate on BattleMetrics to compare before choosing.
            for n, p in enumerate(report['bm_candidates'][:5], start=1):
                dot = candidate_dot(p)
                view.add_item(discord.ui.Button(label=f"{n}. {p['attributes']['name'][:24]}", emoji=dot, row=3,
                                                url=f"https://www.battlemetrics.com/players/{p['id']}"))
        if report['steamid'] and 'steam' in report['errors'] and 'rustwho' in report['errors']:
            await interaction.followup.send(embed=error_embed(t(lang, 'who.both_down'), lang=lang), view=view, ephemeral=not share)
        else:
            await interaction.followup.send(embeds=build_embeds(report, bool(service.bm.token), lang), view=view, ephemeral=not share)
        view.message = await interaction.original_response()

    async def drop_public_placeholder(interaction, share):
        """After a public "thinking…" message, delete it so the error that follows can be private."""
        if share and interaction.response.is_done():
            try:
                await interaction.delete_original_response()
            except Exception:
                pass

    def link_picker(report: dict, lang: str, share: bool) -> discord.ui.Select:
        """Pick which BattleMetrics profile is this SteamID; the link is saved in the guild's book and the profile reloads."""
        steamid, best = report['steamid'], likely(report['bm_candidates'])
        options = []
        for n, p in enumerate(report['bm_candidates'][:5], start=1):
            shared = [x for x in p.get('shared', []) if x.casefold() != p['attributes']['name'].casefold()]
            detail = ' · '.join(x for x in (t(lang, 'who.link.shared', n=len(shared)) if shared else '', candidate_facts(p, lang)) if x) or t(lang, 'who.link.no_shared')
            options.append(discord.SelectOption(label=f"{n}. {p['attributes']['name']} · BM {p['id']}"[:100], value=str(p['id']), description=detail[:100],
                                                emoji='⭐' if p is best else candidate_dot(p)))
        select = discord.ui.Select(placeholder=t(lang, 'who.link.pick'), options=options, row=2)

        async def chosen(interaction):
            pid = interaction.data['values'][0]
            name = next((p['attributes']['name'] for p in report['bm_candidates'] if str(p['id']) == pid), None)
            bot.store.remember_player(scope_of(interaction), report_name(report) or name, steamid, pid)
            await show(interaction, lang_for(interaction), Target(steamid=steamid), pid, share)
        select.callback = chosen
        return select

    @bot.tree.command(name='steamid', description='🆔 Convert a player to every SteamID format')
    @app_commands.describe(player='Name you looked up before, SteamID64, STEAM_0, [U:1:…] or Steam custom URL')
    @app_commands.autocomplete(player=players)
    async def steamid(interaction: discord.Interaction, player: str):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            target = parse_target(expand(bot, interaction, player))
        except ValueError:
            target = Target()
        try:
            if target.bm_id and bot.bm.token:
                target = Target(steamid=steamid_from(await service.bm_detail(target.bm_id)))
            sid = target.steamid or (await service.resolve_vanity(target.vanity) if target.vanity else None)
        except VanityNotFound as exc:
            await interaction.followup.send(embed=error_embed(t(lang, 'who.bad_vanity', v=esc(exc.vanity)), lang=lang), ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'steamid.fail'), lang=lang), ephemeral=True)
            return
        if not sid:
            await interaction.followup.send(embed=error_embed(t(lang, 'steamid.bad'), lang=lang), ephemeral=True)
            return
        await interaction.followup.send(embed=steamid_embed(sid, lang), view=LinksView(sid, None), ephemeral=True)

    return who
