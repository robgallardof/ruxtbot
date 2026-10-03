"""Player activity from BattleMetrics: /presence, /sessions, /online, /findplayer and /playercompare.

Every player option accepts a name from the guild's player book (autocomplete), a SteamID64 or a
BattleMetrics player ID. Results that list players have a picker that opens the full /who profile.
"""
from __future__ import annotations
import logging
import discord
from discord import app_commands
from .i18n import lang_for, t
from .players import player_autocomplete, remember, scope_of, steam_of
from .ui import GREEN, OwnedView, brand_embed, error_embed
from .utility_commands import iso_to_ts

ONLINE_PAGE = 20


def safe(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))[:80]


def identity_error(exc: Exception) -> str:
    """Translation key for a failed player/server resolution."""
    if isinstance(exc, ValueError) and str(exc).startswith('identity.'):
        return str(exc)
    if isinstance(exc, ValueError):
        return 'identity.input'
    return 'identity.unavailable'


def hours(seconds) -> str:
    return f'{seconds / 3600:,.1f} h' if isinstance(seconds, (int, float)) else '—'


async def presence_lines(bot, pid, data):
    known = {r['id'] for r in bot.directory.rows}
    rows = [r for r in data.get('included', []) if r.get('type') == 'server' and r['id'] in known]
    rows.sort(key=lambda r: (r.get('meta') or {}).get('lastSeen') or '', reverse=True)
    lines = []
    for row in rows:
        state = await bot.bm.player_online(row['id'], 'bm:' + pid)
        meta = row.get('meta') or {}
        stamp = iso_to_ts(meta.get('lastSeen'))
        detail = f" · {hours(meta['timePlayed'])}" if isinstance(meta.get('timePlayed'), (int, float)) else ''
        if stamp:
            detail += f' · <t:{stamp}:R>'
        lines.append(f"{ {True: '🟢', False: '🔴', None: '⚪'}[state]} **{safe(row['attributes'].get('name', row['id']))}**{detail}")
    return lines


async def open_profile(bot, interaction, bm_id: str):
    """Run /who for a BattleMetrics ID picked from a list."""
    await bot.tree.get_command('who').callback(interaction, player=bm_id)


def profile_picker(bot, lang: str, players: list[dict]) -> discord.ui.Select:
    """Select with up to 25 players ({'id', 'name'}); choosing one opens its profile."""
    select = discord.ui.Select(placeholder=t(lang, 'online.pick'), options=[
        discord.SelectOption(label=(p['name'].strip() or p['id'])[:100], value=p['id'], description=f"BattleMetrics ID {p['id']}") for p in players[:25]])

    async def chosen(interaction):
        await open_profile(bot, interaction, interaction.data['values'][0])
    select.callback = chosen
    return select


def online_embed(lang: str, sid: str, attrs: dict, players: list[dict], page: int, query: str, marks: dict[str, str]) -> tuple[discord.Embed, int]:
    pages = max(1, -(-len(players) // ONLINE_PAGE))
    page = max(1, min(page, pages))
    chunk = players[(page - 1) * ONLINE_PAGE:page * ONLINE_PAGE]
    lines = []
    for n, p in enumerate(chunk, start=(page - 1) * ONLINE_PAGE + 1):
        since = iso_to_ts(p.get('start'))
        lines.append(f"`{n:>3}` {marks.get(p['id'], '')}**{safe(p['name'])}**" + (f' · <t:{since}:R>' if since else ''))
    title = f"👥 {attrs.get('name', sid)}"[:250]
    e = brand_embed(title, '\n'.join(lines) or t(lang, 'online.none'), color=GREEN)
    e.url = f'https://www.battlemetrics.com/servers/rust/{sid}'
    head = t(lang, 'online.count', n=attrs.get('players', len(players)), m=attrs.get('maxPlayers') or '?')
    if query:
        head += ' · ' + t(lang, 'online.filter', q=safe(query), n=len(players))
    e.add_field(name=t(lang, 'online.summary'), value=head, inline=False)
    e.set_footer(text=t(lang, 'online.footer', page=page, pages=pages))
    return e, pages


class OnlineView(OwnedView):
    """◀️ ▶️ through the online list; the picker opens the chosen player's profile."""

    def __init__(self, bot, lang, sid, attrs, players, query, marks, page=1, owner_id=None):
        super().__init__(owner_id)
        self.bot, self.lang, self.sid, self.attrs, self.players, self.query, self.marks = bot, lang, sid, attrs, players, query, marks
        _, pages = online_embed(lang, sid, attrs, players, page, query, marks)
        self.page = max(1, min(page, pages))
        chunk = players[(self.page - 1) * ONLINE_PAGE:self.page * ONLINE_PAGE]
        if chunk:
            self.add_item(profile_picker(bot, lang, chunk))
        for emoji, delta, disabled in (('◀️', -1, self.page <= 1), ('▶️', 1, self.page >= pages)):
            button = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary, disabled=disabled, row=1)

            async def go(interaction, delta=delta):
                view = OnlineView(self.bot, self.lang, self.sid, self.attrs, self.players, self.query, self.marks, self.page + delta, self.owner_id)
                view.message = interaction.message
                e, _ = online_embed(self.lang, self.sid, self.attrs, self.players, view.page, self.query, self.marks)
                await interaction.response.edit_message(embed=e, view=view)
            button.callback = go
            self.add_item(button)


def register_activity(bot):
    players = player_autocomplete(bot)
    servers = bot.server_choices

    async def fail(interaction, lang, key, share):
        await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=not share)

    @bot.tree.command(description='📍 Presence on synchronized servers: online, hours and last seen')
    @app_commands.describe(player='Name you looked up before, SteamID64 or BattleMetrics player ID', page='Page of 10 servers', share='Publish the result in this channel')
    @app_commands.autocomplete(player=players)
    async def presence(interaction: discord.Interaction, player: str, page: app_commands.Range[int, 1, 1000] = 1, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            pid = await bot.bm.resolve_player(player)
            data = await bot.bm.profile(pid)
            lines = await presence_lines(bot, pid, data)
        except Exception as exc:
            await fail(interaction, lang, identity_error(exc), share)
            return
        await remember(bot, interaction, bm_id=pid, steamid=steam_of(player), profile=data)
        pages = max(1, (len(lines) + 9) // 10)
        page = min(page, pages)
        name = ((data.get('data') or {}).get('attributes') or {}).get('name') or pid
        e = brand_embed(f'📍 {safe(name)} · {page}/{pages}', '\n'.join(lines[(page-1)*10:page*10]) or t(lang, 'activity.empty'))
        e.url = f'https://www.battlemetrics.com/players/{pid}'
        e.set_footer(text=t(lang, 'activity.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)

    @bot.tree.command(description='🕒 Recent player sessions, timestamps and duration')
    @app_commands.describe(player='Name you looked up before, SteamID64 or BattleMetrics player ID', server='Optional server name', share='Publish the result in this channel')
    @app_commands.autocomplete(player=players, server=servers)
    async def sessions(interaction: discord.Interaction, player: str, server: str | None = None, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            pid = await bot.bm.resolve_player(player)
            sid = bot.directory.resolve(server) if server else None
            data = await bot.bm.sessions(pid, sid)
        except Exception as exc:
            await fail(interaction, lang, identity_error(exc), share)
            return
        await remember(bot, interaction, bm_id=pid, steamid=steam_of(player))
        names = {r['id']: r['attributes'].get('name', r['id']) for r in data.get('included', []) if r.get('type') == 'server'}
        lines, total = [], 0
        for row in data.get('data', [])[:10]:
            a = row.get('attributes') or {}
            start, stop = iso_to_ts(a.get('start')), iso_to_ts(a.get('stop'))
            if not start:
                continue
            server_id = row.get('relationships', {}).get('server', {}).get('data', {}).get('id', '')
            end = f'<t:{stop}:t>' if stop else t(lang, 'sessions.open')
            duration = f' · **{hours(max(0, stop - start))}**' if stop else ''
            total += max(0, stop - start) if stop else 0
            lines.append(f"🖥️ **{safe(names.get(server_id, bot.directory.name(server_id)))}**\n-# <t:{start}:f> → {end}{duration}")
        e = brand_embed(t(lang, 'sessions.title'), '\n'.join(lines) or t(lang, 'sessions.empty'))
        e.url = f'https://www.battlemetrics.com/players/{pid}'
        if total:
            e.add_field(name=t(lang, 'sessions.total'), value=f'**{hours(total)}**', inline=True)
        e.set_footer(text=t(lang, 'sessions.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)

    @bot.tree.command(description='👥 Who is online on a server right now')
    @app_commands.describe(server='Server name or BattleMetrics server ID', name='Only players whose name contains this', share='Publish the result in this channel')
    @app_commands.autocomplete(server=servers)
    async def online(interaction: discord.Interaction, server: str, name: str = '', share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            sid = bot.directory.resolve(server)
        except ValueError:
            await fail(interaction, lang, 'server.pick', share)
            return
        try:
            attrs, found = await bot.bm.server_players(sid)
            attrs = attrs.get('attributes') or {}
        except Exception:
            logging.info('online: server %s failed', sid, exc_info=True)
            await fail(interaction, lang, 'server.fail', share)
            return
        if name:
            found = [p for p in found if name.casefold() in p['name'].casefold()]
        # 👀 = watched in this guild, ⭐ = in the guild's player book.
        book = {bm for _, _, bm in bot.store.known_players(scope_of(interaction), limit=500) if bm}
        watched = {w.steamid[3:] for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and getattr(ch, 'guild', None) and ch.guild.id == interaction.guild_id}
        marks = {p['id']: '👀 ' if p['id'] in watched else '⭐ ' for p in found if p['id'] in watched or p['id'] in book}
        e, _ = online_embed(lang, sid, attrs, found, 1, name, marks)
        view = OnlineView(bot, lang, sid, attrs, found, name, marks, owner_id=interaction.user.id)
        await interaction.followup.send(embed=e, view=view, ephemeral=not share)
        view.message = await interaction.original_response()

    @bot.tree.command(description='🔎 Find a player by name and get their BattleMetrics ID')
    @app_commands.describe(name='In-game name (or part of it)', share='Publish the result in this channel')
    async def findplayer(interaction: discord.Interaction, name: app_commands.Range[str, 2, 64], share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            rows = await bot.bm.search_players(name)
        except Exception as exc:
            await fail(interaction, lang, identity_error(exc), share)
            return
        exact = name.casefold()
        rows.sort(key=lambda p: ((p.get('attributes') or {}).get('name', '').casefold() != exact, -(iso_to_ts((p.get('attributes') or {}).get('updatedAt')) or 0)))
        found = [{'id': str(p['id']), 'name': (p.get('attributes') or {}).get('name') or str(p['id']),
                  'seen': iso_to_ts((p.get('attributes') or {}).get('updatedAt'))} for p in rows[:15]]
        lines = [f"**{safe(p['name'])}** · `{p['id']}`" + (f" · {t(lang, 'who.bm.active', ts=p['seen'])}" if p['seen'] else '') for p in found]
        e = brand_embed(t(lang, 'find.title', q=safe(name)), '\n'.join(lines) or t(lang, 'find.none'))
        e.set_footer(text=t(lang, 'find.footer'))
        view = OwnedView(interaction.user.id)
        if found:
            view.add_item(profile_picker(bot, lang, found))
        await interaction.followup.send(embed=e, view=view, ephemeral=not share)
        view.message = await interaction.original_response()

    @bot.tree.command(description='🤝 Servers two players have in common (possible teammates)')
    @app_commands.describe(first='First player: name, SteamID64 or BattleMetrics ID', second='Second player: name, SteamID64 or BattleMetrics ID', share='Publish the result in this channel')
    @app_commands.autocomplete(first=players, second=players)
    async def playercompare(interaction: discord.Interaction, first: str, second: str, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            ids = [await bot.bm.resolve_player(first), await bot.bm.resolve_player(second)]
            profiles = [await bot.bm.profile(pid) for pid in ids]
        except Exception as exc:
            await fail(interaction, lang, identity_error(exc), share)
            return
        names, maps = [], []
        for pid, data, raw in zip(ids, profiles, (first, second)):
            names.append(((data.get('data') or {}).get('attributes') or {}).get('name') or pid)
            maps.append({s['id']: s for s in data.get('included', []) if s.get('type') == 'server'})
            await remember(bot, interaction, bm_id=pid, steamid=steam_of(raw), profile=data)
        if ids[0] == ids[1]:
            await fail(interaction, lang, 'compare.same', share)
            return
        shared = sorted(set(maps[0]) & set(maps[1]),
                        key=lambda k: min((maps[0][k].get('meta') or {}).get('timePlayed') or 0, (maps[1][k].get('meta') or {}).get('timePlayed') or 0), reverse=True)
        lines = []
        for key in shared[:10]:
            a, b = (maps[0][key].get('meta') or {}), (maps[1][key].get('meta') or {})
            together = ' 🟢🟢' if a.get('online') and b.get('online') else ''
            seen = [iso_to_ts(m.get('lastSeen')) for m in (a, b)]
            lines.append(f"🖥️ **{safe(maps[0][key]['attributes'].get('name', key))}**{together}\n"
                         f"-# {safe(names[0])}: {hours(a.get('timePlayed'))}" + (f' · <t:{seen[0]}:R>' if seen[0] else '') +
                         f" │ {safe(names[1])}: {hours(b.get('timePlayed'))}" + (f' · <t:{seen[1]}:R>' if seen[1] else ''))
        e = brand_embed(t(lang, 'compare.title', a=safe(names[0]), b=safe(names[1]))[:256], '\n'.join(lines) or t(lang, 'compare.none'))
        e.add_field(name=t(lang, 'compare.summary'), value=t(lang, 'compare.summary.value', n=len(shared), a=len(maps[0]), b=len(maps[1])), inline=False)
        e.set_footer(text=t(lang, 'compare.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)
