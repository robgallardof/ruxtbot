"""/who: perfil completo de un jugador combinando Steam, RustWho y BattleMetrics."""
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
from .servers import profile_id
from .tracking import STEAMID64_MIN as STEAM64_BASE, valid_steamid64

RUST_APP_ID = 252490
YELLOW = 0xD5A522
RED = 0xC0392B
STEAM_BLUE = 0x1B2838
BM_ORANGE = 0xE67E22
COOLDOWN_SECONDS = 10
HEADERS = {'User-Agent': 'Mozilla/5.0 (RuxtBot; +https://github.com/robgallardof/ruxtbot)', 'Accept-Language': 'en'}


@dataclass(frozen=True)
class Target:
    steamid: str | None = None
    vanity: str | None = None
    bm_id: str | None = None


def parse_target(value: str) -> Target:
    """Acepta SteamID64/2/3, vanity, o enlaces de Steam, steamid.io, SteamDB, RustWho y BattleMetrics."""
    v = value.strip().strip('<>').strip()
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
    raise ValueError('No reconozco ese jugador. Usa un SteamID64, un enlace de Steam, steamid.io, SteamDB, RustWho o BattleMetrics.')


def steam_ids(steamid: str) -> dict[str, str]:
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
    """Consulta todas las fuentes en paralelo; un fallo en una no rompe las demás."""

    def __init__(self, bm, steam_api_key: str | None = None, client: httpx.AsyncClient | None = None):
        self.bm = bm
        self.steam_api_key = steam_api_key
        self.client = client or httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True)

    async def resolve_vanity(self, vanity: str) -> str:
        r = await self.client.get(f'https://steamcommunity.com/id/{vanity}', params={'xml': 1})
        r.raise_for_status()
        if m := re.search(r'<steamID64>(\d{17})</steamID64>', r.text):
            return m[1]
        raise ValueError(f'No existe un perfil de Steam con la URL personalizada «{vanity}».')

    async def steam_profile(self, steamid: str) -> dict:
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
        r = await self.client.get(f'https://steamcommunity.com/profiles/{steamid}/')
        r.raise_for_status()
        out = {}
        if m := re.search(r'friendPlayerLevelNum">(\d+)', r.text):
            out['level'] = int(m[1])
        for label, total in re.findall(r'count_link_label">([^<]+)</span>\s*&nbsp;\s*<span class="profile_count_link_total">\s*([\d,]+)', r.text):
            out[label.strip().casefold()] = int(total.replace(',', ''))
        return out

    async def steam_aliases(self, steamid: str) -> list[dict]:
        r = await self.client.get(f'https://steamcommunity.com/profiles/{steamid}/ajaxaliases')
        r.raise_for_status()
        return r.json() or []

    async def steam_games(self, steamid: str) -> dict | None:
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

    async def bm_candidates(self, name: str) -> list[dict]:
        rows = await self.bm.search_players(name)
        exact = [p for p in rows if p['attributes'].get('name', '').casefold() == name.casefold()]
        return sorted(exact, key=lambda p: p['attributes'].get('updatedAt') or '', reverse=True)[:3]

    async def lookup(self, target: Target, bm_id: str | None = None) -> dict:
        steamid = target.steamid or (await self.resolve_vanity(target.vanity) if target.vanity else None)
        bm_id = bm_id or target.bm_id
        jobs = {}
        if steamid:
            jobs |= {'steam': self.steam_profile(steamid), 'page': self.steam_page(steamid), 'aliases': self.steam_aliases(steamid),
                     'games': self.steam_games(steamid), 'rustwho': self.rustwho(steamid)}
        if bm_id and self.bm.token:
            jobs['bm'] = self.bm_detail(bm_id)
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        report = {'steamid': steamid, 'bm_id': bm_id, 'errors': []}
        for key, result in zip(jobs, results):
            if isinstance(result, BaseException):
                logging.info('who: %s failed: %r', key, result)
                report['errors'].append(key)
            else:
                report[key] = result
        name = (report.get('steam') or {}).get('name') or ((report.get('rustwho') or {}).get('steamInfo') or {}).get('name')
        if steamid and not bm_id and name and self.bm.token:
            try:
                report['bm_candidates'] = await self.bm_candidates(name)
            except Exception as exc:
                logging.info('who: bm search failed: %r', exc)
        return report


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
    """Fusiona nombres de Steam, RustWho y BattleMetrics, el más reciente primero, sin duplicados."""
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


def steam_embed(report: dict) -> discord.Embed:
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
    status = {'online': '🟢 En línea', 'in-game': f"🎮 Jugando **{esc(steam.get('game') or 'un juego')}**", 'offline': '⚫ Desconectado'}.get(state, '⚪ Estado desconocido')
    privacy = {'public': '🔓 Perfil público', 'friendsonly': '👥 Solo amigos', 'private': '🔒 Perfil privado'}.get(steam.get('privacy') or '', '')
    country = steam.get('location') or info.get('country')
    desc = ' · '.join(x for x in (status, privacy, f'🌎 {esc(country)}' if country else '') if x)
    if steam.get('real_name'):
        desc += f"\n🪪 Nombre real: **{esc(steam['real_name'])}**"
    e = discord.Embed(title=f'👤 {name}', url=f'https://steamcommunity.com/profiles/{steamid}', description=desc, color=RED if banned else STEAM_BLUE)
    avatar = steam.get('avatar') or info.get('avatar')
    if avatar:
        e.set_thumbnail(url=avatar)
    ids = steam_ids(steamid)
    rows = [('SteamID64', ids['steam64']), ('SteamID', ids['steam2']), ('SteamID3', ids['steam3']), ('Account ID', ids['account'])]
    if steam.get('custom_url'):
        rows.append(('Custom URL', steam['custom_url']))
    e.add_field(name='🆔 Identificadores', value='```\n' + '\n'.join(f'{k:<11}{v}' for k, v in rows) + '\n```', inline=False)
    created = info.get('timeCreated')
    account = []
    if created:
        account.append(f'📅 Creada: <t:{created}:D> (<t:{created}:R>)')
    elif steam.get('member_since'):
        account.append(f"📅 Miembro desde: {esc(steam['member_since'])}")
    if 'level' in page:
        account.append(f"⭐ Nivel: **{page['level']}**")
    game_count = games.get('count') or page.get('games')
    if game_count:
        account.append(f'🎮 Juegos: **{num(game_count)}**')
    if games.get('rust_minutes') is not None:
        account.append(f"🦀 Horas en Rust: **{num(round(games['rust_minutes'] / 60))} h**" + (f" ({num(round(games['rust_2wk_minutes'] / 60, 1))} h últimas 2 sem.)" if games.get('rust_2wk_minutes') else ''))
    elif steam.get('hours_2wk') not in (None, '', '0.0'):
        account.append(f"⏳ Horas últimas 2 sem.: **{esc(steam['hours_2wk'])} h**")
    for key, label in (('badges', '🏅 Insignias'), ('screenshots', '🖼️ Capturas'), ('workshop items', '🧰 Workshop')):
        if page.get(key):
            account.append(f'{label}: **{num(page[key])}**')
    if steam:
        account.append(f"🚧 Cuenta limitada: **{'Sí' if steam.get('limited') else 'No'}**")
    e.add_field(name='📋 Cuenta', value=clip('\n'.join(account) or 'Sin datos públicos.'), inline=True)
    vac = bans.get('vacBans', 1 if steam.get('vac_banned') else 0)
    game_bans = bans.get('gameBans')
    trade = bans.get('economyBan') or steam.get('trade_ban') or 'none'
    ban_lines = [f'{check(not vac)} VAC: **{num(vac)}**']
    if game_bans is not None:
        ban_lines.append(f'{check(not game_bans)} Game bans: **{num(game_bans)}**')
    if bans:
        ban_lines.append(f"{check(not bans.get('communityBanned'))} Comunidad: **{'Baneado' if bans.get('communityBanned') else 'Limpio'}**")
    ban_lines.append(f"{check(trade.casefold() == 'none')} Tradeo: **{'Limpio' if trade.casefold() == 'none' else esc(trade)}**")
    if rw.get('serverBanCount') is not None:
        ban_lines.append(f"{'⚠️' if rw['serverBanCount'] else '✅'} Bans en servidores: **{num(rw['serverBanCount'])}**")
    if (vac or game_bans) and bans.get('daysSinceLastBan'):
        ban_lines.append(f"🕒 Último ban hace **{num(bans['daysSinceLastBan'])}** días")
    e.add_field(name='🛡️ Baneos', value='\n'.join(ban_lines), inline=True)
    friends = extra.get('friends') or {}
    if friends and not rw.get('richFriendsLimited') and friends.get('friendsCount') not in (None, '0'):
        e.add_field(name='👥 Amigos', value=(f"Total: **{num(friends.get('friendsCount'))}**\n"
                                            f"Con VAC: **{num(friends.get('vacFriends'))}** · Game ban: **{num(friends.get('gameBanFriends'))}**\n"
                                            f"Trade ban: **{num(friends.get('tradeBanFriends'))}** · Comunidad: **{num(friends.get('communityBanFriends'))}**"), inline=False)
    names = name_history(report)
    total = (extra.get('nameHistory') or {}).get('nameHistoryCount')
    if names:
        lines = [f"• **{esc(n)}**" + (f' · <t:{ts}:d>' if ts else '') + f' `{src}`' for n, ts, src in names[:12]]
        more = len(names) - 12
        if more > 0:
            lines.append(f'…y {more} más')
        title = '📝 Nombres usados' + (f' ({num(total)} registrados en Steam)' if total and total != '0' else '')
        e.add_field(name=title, value=clip('\n'.join(lines)), inline=False)
    return e


STAT_GROUPS = [
    ('⚔️ PvP', [('kills', 'Kills'), ('deaths', 'Muertes'), ('headshots', 'Headshots'), ('wounded', 'Derribados'), ('shotgunHitPlayer', 'Escopetazos a jugador')]),
    ('🔫 Disparos', [('bulletsFired', 'Balas'), ('bulletsHit', 'Balas acertadas'), ('arrowsFired', 'Flechas'), ('arrowsHitPlayer', 'Flechas a jugador'), ('shotgunFired', 'Escopeta'), ('rocketsFired', 'Cohetes'), ('grenadesThrown', 'Granadas')]),
    ('🏗️ Construcción', [('buildingsPlaced', 'Bloques puestos'), ('buildingsUpgraded', 'Mejoras'), ('cupboardsOpened', 'TC abiertos'), ('wiresConnected', 'Cables'), ('pipesConnected', 'Tuberías'), ('blueprintsStudied', 'BPs aprendidos')]),
    ('⛏️ Recolección', [('woodGathered', 'Madera'), ('stoneGathered', 'Piedra'), ('metalGathered', 'Metal'), ('sulfurGathered', 'Azufre'), ('clothGathered', 'Tela'), ('leatherGathered', 'Cuero'), ('lowGradeGathered', 'Low grade'), ('scrapGathered', 'Scrap')]),
    ('🌲 Mundo', [('barrelsDestroyed', 'Barriles'), ('oreHits', 'Golpes a nodos'), ('treeHits', 'Golpes a árboles'), ('scientistsKilled', 'Científicos'), ('woundedHealed', 'Revividos'), ('woundedAssisted', 'Asistencias')]),
]


def rust_embed(report: dict) -> discord.Embed | None:
    rw = report.get('rustwho')
    if rw is None:
        return None
    stats = rw.get('rustStats') or {}
    e = discord.Embed(title='🦀 Estadísticas de Rust', url=f"https://www.rustwho.com/stats/{report['steamid']}", color=YELLOW)
    if stats.get('noData') or stats.get('availability') not in (None, 'available'):
        e.description = '🔒 Estadísticas privadas o sin datos. El jugador debe tener los detalles de juego públicos en Steam.'
        return e
    kd = stats.get('kd')
    rating = '🔥' if isinstance(kd, (int, float)) and kd >= 2 else '💪' if isinstance(kd, (int, float)) and kd >= 1 else '🙂'
    e.description = f"{rating} K/D **{num(kd)}** · 🎯 Precisión **{num(stats.get('accuracyPct'))}%** · 💀 HS **{num(stats.get('headshotPct'))}%**"
    if stats.get('pvpScore') is not None:
        e.description += f" · 🏆 PvP score **{num(stats['pvpScore'])}**"
    for title, keys in STAT_GROUPS:
        lines = [f'{label}: **{num(stats[k])}**' for k, label in keys if stats.get(k) is not None]
        if lines:
            e.add_field(name=title, value='\n'.join(lines), inline=True)
    extra = []
    if stats.get('voiceChatTime'):
        extra.append(f"🎙️ Voz: **{num(round(stats['voiceChatTime'] / 3600, 1))} h**")
    votes = rw.get('votes') or {}
    if votes.get('availability') == 'available':
        extra.append(f"👍 {num(votes.get('likes', 0))} · 👎 {num(votes.get('dislikes', 0))}")
    if rw.get('altsFound'):
        extra.append(f"🕵️ Posibles alts: **{num(rw['altsFound'])}**")
    if extra:
        e.add_field(name='✨ Extra', value='\n'.join(extra), inline=True)
    observed = iso_ts(stats.get('observedAt'))
    e.set_footer(text='RustWho · estadísticas de Steam · orientativo, no es prueba de trampas')
    if observed:
        e.timestamp = datetime.fromtimestamp(observed, timezone.utc)
    return e


def bm_embed(report: dict, bm_configured: bool) -> discord.Embed | None:
    data = report.get('bm')
    if data:
        attrs = data['data']['attributes']
        servers = [s for s in data.get('included', []) if s.get('type') == 'server']
        e = discord.Embed(title=f"📊 BattleMetrics · {attrs.get('name', report['bm_id'])}", url=f"https://www.battlemetrics.com/players/{report['bm_id']}", color=BM_ORANGE)
        online = [s for s in servers if (s.get('meta') or {}).get('online')]
        last = max(servers, key=lambda s: (s.get('meta') or {}).get('lastSeen') or '', default=None)
        if online:
            e.description = '🟢 **En línea ahora** en ' + ', '.join(f"**{esc(s['attributes']['name'])}**" for s in online[:3])
        elif last and (ts := iso_ts(last['meta'].get('lastSeen'))):
            e.description = f"⚫ Visto por última vez <t:{ts}:R> en **{esc(last['attributes']['name'])}**"
        else:
            e.description = '⚪ Sin actividad registrada.'
        if attrs.get('private'):
            e.description += '\n🔒 El jugador marcó su perfil como privado en BattleMetrics.'
        seconds = sum((s.get('meta') or {}).get('timePlayed') or 0 for s in servers)
        firsts = [ts for s in servers if (ts := iso_ts((s.get('meta') or {}).get('firstSeen')))]
        e.add_field(name='⏱️ Tiempo jugado', value=f'**{num(round(seconds / 3600))} h**', inline=True)
        e.add_field(name='🖥️ Servidores', value=f'**{len(servers)}**', inline=True)
        if firsts:
            e.add_field(name='📅 Primer registro', value=f'<t:{min(firsts)}:D>', inline=True)
        top = sorted(servers, key=lambda s: (s.get('meta') or {}).get('timePlayed') or 0, reverse=True)[:6]
        if top:
            lines = []
            for s in top:
                meta = s.get('meta') or {}
                seen = iso_ts(meta.get('lastSeen'))
                dot = '🟢' if meta.get('online') else '▫️'
                lines.append(f"{dot} [{esc(s['attributes']['name'][:48])}](https://www.battlemetrics.com/servers/rust/{s['id']}) — **{num(round((meta.get('timePlayed') or 0) / 3600, 1))} h**" + (f' · <t:{seen}:R>' if seen else ''))
            e.add_field(name='🏆 Servidores más jugados', value=clip('\n'.join(lines)), inline=False)
        e.set_footer(text='BattleMetrics · tiempos aproximados por servidor')
        return e
    if not bm_configured:
        return None
    e = discord.Embed(title='📊 BattleMetrics', color=BM_ORANGE)
    candidates = report.get('bm_candidates') or []
    if candidates:
        lines = []
        for p in candidates:
            ts = iso_ts(p['attributes'].get('updatedAt'))
            lines.append(f"🔎 [{esc(p['attributes']['name'])}](https://www.battlemetrics.com/players/{p['id']})" + (f' · activo <t:{ts}:R>' if ts else ''))
        e.description = ('Perfiles con el **mismo nombre** (sin verificar que sea la misma cuenta):\n' + '\n'.join(lines))
    else:
        e.description = 'No encontré perfiles con ese nombre.'
    e.description += '\n\n💡 Añade `battlemetrics:` con el enlace del perfil para ver horas, servidores y nombres.'
    return e


def build_embeds(report: dict, bm_configured: bool = True) -> list[discord.Embed]:
    embeds = []
    if report.get('steamid'):
        embeds.append(steam_embed(report))
        if rust := rust_embed(report):
            embeds.append(rust)
    if bm := bm_embed(report, bm_configured):
        embeds.append(bm)
    if not report.get('steamid'):
        note = discord.Embed(description='ℹ️ Solo diste un enlace de BattleMetrics. Pasa también el SteamID64 o el enlace de Steam para ver baneos, nombres de Steam y estadísticas.', color=YELLOW)
        embeds.append(note)
    missing = [{'steam': 'Steam', 'page': 'Steam', 'aliases': 'Steam', 'games': 'Steam API', 'rustwho': 'RustWho', 'bm': 'BattleMetrics'}[k] for k in report.get('errors', [])]
    if missing and embeds:
        last = embeds[-1]
        footer = (last.footer.text + ' · ') if last.footer and last.footer.text else ''
        last.set_footer(text=footer + '⚠️ Sin respuesta de: ' + ', '.join(dict.fromkeys(missing)))
    # Discord limita a 6000 caracteres el total de embeds de un mensaje.
    while sum(len(e) for e in embeds) > 6000 and len(embeds) > 1:
        embeds.pop()
    return embeds


class LinksView(discord.ui.View):
    def __init__(self, steamid: str | None, bm_id: str | None):
        super().__init__(timeout=None)
        emoji = {'Steam': '🎮', 'SteamID I/O': '🆔', 'SteamDB': '💰', 'RustWho': '🦀', 'BattleMetrics': '📊'}
        for label, url in links(steamid, bm_id).items():
            self.add_item(discord.ui.Button(label=label, url=url, emoji=emoji[label]))


def register_who(bot, service: WhoService):
    cooldowns: dict[int, float] = {}

    @bot.tree.command(name='who', description='Perfil completo de un jugador: Steam, baneos, nombres, Rust y BattleMetrics')
    @app_commands.describe(jugador='SteamID64, STEAM_0, enlace de Steam, steamid.io, SteamDB, RustWho o BattleMetrics',
                           battlemetrics='Enlace del perfil BattleMetrics (opcional) para horas y servidores')
    async def who(interaction: discord.Interaction, jugador: str, battlemetrics: str | None = None):
        try:
            target = parse_target(jugador)
            bm_id = profile_id(battlemetrics) if battlemetrics else None
        except ValueError as exc:
            await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
            return
        now = time.monotonic()
        remaining = COOLDOWN_SECONDS - (now - cooldowns.get(interaction.user.id, 0))
        if remaining > 0:
            await interaction.response.send_message(f'⏳ Espera {int(remaining) + 1} s antes de otra consulta.', ephemeral=True)
            return
        cooldowns[interaction.user.id] = now
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            report = await service.lookup(target, bm_id)
        except ValueError as exc:
            await interaction.followup.send(f'❌ {exc}', ephemeral=True)
            return
        except Exception:
            logging.exception('who lookup failed')
            await interaction.followup.send('❌ No se pudo consultar el perfil ahora mismo. Inténtalo de nuevo en un momento.', ephemeral=True)
            return
        if report['steamid'] and 'steam' in report['errors'] and 'rustwho' in report['errors']:
            await interaction.followup.send('❌ Steam y RustWho no respondieron. Revisa el enlace o inténtalo más tarde.', view=LinksView(report['steamid'], report['bm_id']), ephemeral=True)
            return
        await interaction.followup.send(embeds=build_embeds(report, bool(service.bm.token)), view=LinksView(report['steamid'], report['bm_id']), ephemeral=True)

    return who
