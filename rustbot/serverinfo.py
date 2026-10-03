"""Servers: /server, /sv and /ip, /setserver, /delserver, /serverstats, /leaderboard, /serversearch and /rust.

Server cards use everything BattleMetrics publishes for Rust: population and queue, map with its RustMaps
page, rates (gather/craft/scrap), group limit, upkeep and decay multipliers, wipe schedule, FPS and uptime.
Cards have buttons for the common next steps (copy the connect command, who is online, stats, top players),
so nobody has to remember another command or retype the server.
"""
from __future__ import annotations
import logging
import re
import time
import discord
from discord import app_commands
from .i18n import lang_for, t
from .profiles import default_server
from .ui import GREEN, ORANGE, RED, YELLOW, OwnedView, brand_embed, error_embed, fmt_num, success_embed
from .utility_commands import iso_to_ts

SPARK = '▁▂▃▄▅▆▇█'
ADDRESS = re.compile(r'^(?:client\.connect\s+)?([A-Za-z0-9.-]{3,253}:\d{2,5})$', re.I)
TYPE_ICONS = {'official': '🏛️', 'community': '🌐', 'modded': '🧩'}
LEADERBOARD_PAGE = 10


def esc(value) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


def spark(values: list[float], width: int = 24) -> str:
    """Unicode sparkline of `values`, squeezed to `width` buckets (each bucket keeps its maximum)."""
    if not values:
        return ''
    if len(values) > width:
        size = len(values) / width
        values = [max(values[int(i * size):max(int((i + 1) * size), int(i * size) + 1)]) for i in range(width)]
    low, high = min(values), max(values)
    span = (high - low) or 1
    return ''.join(SPARK[min(7, int((v - low) / span * 7.999))] for v in values)


def connect_line(address: str) -> str:
    return f'client.connect {address}'


class PresetStore:
    """Servers saved by a Discord server for /sv and /ip: name, address and (optionally) BattleMetrics ID."""

    def __init__(self, conn):
        self.conn = conn
        conn.execute('CREATE TABLE IF NOT EXISTS guild_servers(guild_id INTEGER,name TEXT COLLATE NOCASE,address TEXT,bm_id TEXT,is_default INTEGER,'
                     'added_by INTEGER,PRIMARY KEY(guild_id,name))')
        conn.commit()

    def save(self, guild_id, name, address, bm_id, make_default, added_by):
        if make_default or not self.all(guild_id):
            self.conn.execute('UPDATE guild_servers SET is_default=0 WHERE guild_id=?', (guild_id,))
            make_default = True
        self.conn.execute('INSERT OR REPLACE INTO guild_servers VALUES(?,?,?,?,?,?)', (guild_id, name, address, bm_id, int(bool(make_default)), added_by))
        self.conn.commit()

    def all(self, guild_id) -> list[tuple]:
        """(name, address, bm_id, is_default), default first."""
        return self.conn.execute('SELECT name,address,bm_id,is_default FROM guild_servers WHERE guild_id=? ORDER BY is_default DESC,name', (guild_id,)).fetchall()

    def get(self, guild_id, name):
        return self.conn.execute('SELECT name,address,bm_id,is_default FROM guild_servers WHERE guild_id=? AND name=?', (guild_id, name)).fetchone()

    def default(self, guild_id):
        rows = self.all(guild_id)
        return rows[0] if rows else None

    def delete(self, guild_id, name) -> bool:
        cur = self.conn.execute('DELETE FROM guild_servers WHERE guild_id=? AND name=?', (guild_id, name))
        self.conn.commit()
        return cur.rowcount > 0


def settings_line(lang: str, details: dict) -> str:
    """Rates, group limit, upkeep/decay multipliers and blueprint wipes in one line."""
    cfg = details.get('rust_settings') if isinstance(details.get('rust_settings'), dict) else {}
    parts = []
    rates = cfg.get('rates') or {}
    if rates.get('gather'):
        parts.append(t(lang, 'server.gather', n=fmt_num(rates['gather'])))
    if rates.get('craft') and rates.get('craft') != 1:
        parts.append(t(lang, 'server.craft', n=fmt_num(rates['craft'])))
    if rates.get('scrap') and rates.get('scrap') != 1:
        parts.append(t(lang, 'server.scrap', n=fmt_num(rates['scrap'])))
    group = cfg.get('groupLimit')
    team = cfg.get('teamUILimit')
    if isinstance(group, int) and group < 1000:
        parts.append(t(lang, 'server.group', n=group))
    elif isinstance(team, int) and team < 1000:
        parts.append(t(lang, 'server.team', n=team))
    if cfg.get('upkeep') not in (None, 1):
        parts.append(t(lang, 'server.upkeep', n=fmt_num(cfg['upkeep'])))
    if cfg.get('decay') not in (None, 1):
        parts.append(t(lang, 'server.decay', n=fmt_num(cfg['decay'])))
    if cfg.get('blueprints') is not None:
        parts.append(t(lang, 'server.bp_on' if cfg['blueprints'] else 'server.bp_off'))
    if cfg.get('kits'):
        parts.append(t(lang, 'server.kits'))
    if details.get('pve'):
        parts.append('🕊️ PvE')
    return ' · '.join(parts)


def server_embed(lang: str, sid: str, a: dict, preset: tuple | None = None) -> discord.Embed:
    d = a.get('details') or {}
    online = a.get('status') == 'online'
    players, cap = a.get('players') or 0, a.get('maxPlayers') or 0
    pct = round(100 * players / cap) if cap else 0
    title = f"🖥️ {a.get('name', preset[0] if preset else 'Server')}"
    e = brand_embed(title[:256], color=GREEN if online else RED)
    e.url = f'https://www.battlemetrics.com/servers/rust/{sid}'
    parts = [t(lang, 'server.online') if online else '🔴 ' + str(a.get('status', '?')).capitalize(), t(lang, 'server.players', p=players, m=cap, pct=pct)]
    if d.get('rust_queued_players'):
        parts.append(t(lang, 'server.queue', n=d['rust_queued_players']))
    kind = d.get('rust_type') or ('official' if d.get('official') else 'modded' if d.get('rust_modded') else None)
    badge = f"{TYPE_ICONS.get(kind, '')} {t(lang, 'server.type.' + kind)}" if kind in TYPE_ICONS else ''
    e.description = ' · '.join(parts) + f"\n`{'█' * round(pct / 10)}{'░' * (10 - round(pct / 10))}`" + (f'\n{badge}' if badge else '')
    if line := settings_line(lang, d):
        e.description += ('  ·  ' if badge else '\n') + line
    maps = d.get('rust_maps') if isinstance(d.get('rust_maps'), dict) else {}
    if d.get('map'):
        size = d.get('rust_world_size')
        value = esc(d['map']) + (f' · {size:,} m' if isinstance(size, int) else '')
        if maps.get('url'):
            value += f" · [RustMaps]({maps['url']})"
        e.add_field(name=t(lang, 'server.map'), value=value)
    if a.get('rank'):
        e.add_field(name=t(lang, 'server.rank'), value=f"#{a['rank']:,}")
    if a.get('country'):
        e.add_field(name=t(lang, 'server.country'), value=a['country'])
    if stamp := iso_to_ts(d.get('rust_last_wipe')):
        e.add_field(name=t(lang, 'server.last_wipe'), value=f'<t:{stamp}:R>')
    upcoming = [ts for w in (d.get('rust_wipes') or []) if isinstance(w, dict) and (ts := iso_to_ts(w.get('timestamp')))]
    if stamp := iso_to_ts(d.get('rust_next_wipe')) or (upcoming[0] if upcoming else None):
        value = f'<t:{stamp}:F> · <t:{stamp}:R>'
        later = [ts for ts in upcoming if ts > stamp][:2]
        if later:
            value += '\n-# ' + t(lang, 'server.then') + ' ' + ' · '.join(f'<t:{ts}:d>' for ts in later)
        e.add_field(name=t(lang, 'server.next_wipe'), value=value, inline=False)
    health = []
    if isinstance(d.get('rust_fps_avg'), (int, float)):
        health.append(f"📶 {d['rust_fps_avg']:.0f} FPS")
    if isinstance(d.get('rust_uptime'), (int, float)):
        health.append(t(lang, 'server.uptime', h=fmt_num(round(d['rust_uptime'] / 3600, 1))))
    if health:
        e.add_field(name=t(lang, 'server.health'), value=' · '.join(health))
    address = preset[1] if preset and preset[1] else (f"{a['ip']}:{a['port']}" if a.get('ip') and a.get('port') else None)
    if address:
        e.add_field(name=t(lang, 'server.connect'), value=f'```\n{connect_line(address)}\n```', inline=False)
    if d.get('rust_headerimage'):
        e.set_image(url=d['rust_headerimage'])
    if maps.get('thumbnailUrl'):
        e.set_thumbnail(url=maps['thumbnailUrl'])
    e.set_footer(text=t(lang, 'server.footer', id=sid))
    return e


class ServerView(discord.ui.View):
    """Buttons under a server card. Anyone can use them; replies only go to whoever clicked."""

    def __init__(self, bot, lang: str, sid: str | None, a: dict | None, address: str | None):
        super().__init__(timeout=900)
        self.message = None
        d = (a or {}).get('details') or {}
        maps = d.get('rust_maps') if isinstance(d.get('rust_maps'), dict) else {}
        if address:
            copy = discord.ui.Button(label=t(lang, 'server.button.copy'), emoji='📋', style=discord.ButtonStyle.success)

            async def copy_cb(i):
                # Plain text only, so a long press (mobile) or triple click (desktop) copies it exactly.
                await i.response.send_message(connect_line(address), ephemeral=True)
            copy.callback = copy_cb
            self.add_item(copy)
        if sid:
            for label, emoji, command in ((t(lang, 'server.button.online'), '👥', 'online'), (t(lang, 'server.button.stats'), '📈', 'serverstats'),
                                          (t(lang, 'server.button.top'), '🏆', 'leaderboard')):
                button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)

                async def run(i, command=command):
                    await bot.tree.get_command(command).callback(i, server=sid)
                button.callback = run
                self.add_item(button)
            self.add_item(discord.ui.Button(label='BattleMetrics', emoji='📊', url=f'https://www.battlemetrics.com/servers/rust/{sid}', row=1))
        if maps.get('url'):
            self.add_item(discord.ui.Button(label='RustMaps', emoji='🗺️', url=maps['url'], row=1))
        site = d.get('rust_url')
        if isinstance(site, str) and site.startswith(('http://', 'https://')):
            self.add_item(discord.ui.Button(label=t(lang, 'server.button.site'), emoji='🌐', url=site[:512], row=1))

    async def on_timeout(self):
        # Link buttons keep working; the others are disabled so nobody gets "This interaction failed".
        for item in self.children:
            if not getattr(item, 'url', None):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def server_matches(a: dict, gather: str | None, group: str | None, kind: str | None, wiped_days: int | None, pve: bool | None) -> bool:
    """Filters BattleMetrics cannot apply itself, checked on each server's details."""
    d = a.get('details') or {}
    cfg = d.get('rust_settings') if isinstance(d.get('rust_settings'), dict) else {}
    rate = (cfg.get('rates') or {}).get('gather')
    if gather == '1' and rate not in (1, 1.0):
        return False
    if gather == '2' and not (isinstance(rate, (int, float)) and 1.5 <= rate <= 2.5):
        return False
    if gather == '3' and not (isinstance(rate, (int, float)) and rate > 2.5):
        return False
    if group:
        limit = cfg.get('groupLimit') if isinstance(cfg.get('groupLimit'), int) and cfg.get('groupLimit') < 1000 else cfg.get('teamUILimit')
        if not isinstance(limit, int) or limit >= 1000 or limit > int(group):
            return False
    if kind and (d.get('rust_type') or '') != kind:
        return False
    if wiped_days is not None:
        wiped = iso_to_ts(d.get('rust_last_wipe'))
        if not wiped or time.time() - wiped > wiped_days * 86400:
            return False
    if pve is not None and bool(d.get('pve')) != pve:
        return False
    return True


def register_serverinfo(bot, can_manage):
    bot.presets = PresetStore(bot.store.conn)
    servers = bot.server_choices

    async def pick_server(interaction, lang, server: str | None) -> str | None:
        """Explicit server, else the member's current/default server, else the Discord's default /sv; answers the error itself."""
        if server:
            try:
                return bot.directory.resolve(server)
            except ValueError:
                pass
            preset = bot.presets.get(interaction.guild_id, server) if interaction.guild_id else None
            if preset and preset[2]:
                return preset[2]
            await reply(interaction, embed=error_embed(t(lang, 'server.pick'), lang=lang))
            return None
        sid, _ = await default_server(bot, interaction)
        if not sid:
            await reply(interaction, embed=error_embed(t(lang, 'server.none_default'), t(lang, 'server.none_default.hint'), lang))
        return sid

    async def reply(interaction, ephemeral=True, **kwargs):
        if interaction.response.is_done():
            await interaction.followup.send(ephemeral=ephemeral, **kwargs)
        else:
            await interaction.response.send_message(ephemeral=ephemeral, **kwargs)

    async def send_card(interaction, lang, sid, preset=None, public=False):
        try:
            a = (await bot.bm.server(sid))['attributes']
        except Exception:
            a = None
        if a is None and not preset:
            await reply(interaction, ephemeral=not public, embed=error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang))
            return
        if a is not None:
            bot.directory.merge([{'id': sid, 'name': a.get('name', sid)}])
            embed = server_embed(lang, sid, a, preset)
        else:
            embed = preset_embed(lang, preset)
        address = preset[1] if preset and preset[1] else (f"{a['ip']}:{a['port']}" if a and a.get('ip') and a.get('port') else None)
        view = ServerView(bot, lang, sid, a, address)
        await reply(interaction, ephemeral=not public, embed=embed, view=view)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    def preset_embed(lang, preset):
        e = brand_embed(f'🖥️ {preset[0]}', color=YELLOW)
        e.add_field(name=t(lang, 'server.connect'), value=f'```\n{connect_line(preset[1])}\n```', inline=False)
        e.set_footer(text=t(lang, 'sv.footer'))
        return e

    # ── /server ──
    @bot.tree.command(description='🖥️ Live server card: players, map, rates, wipes and connect')
    @app_commands.describe(server='Server name or BattleMetrics server ID (empty = yours)', share='Publish the result in this channel')
    @app_commands.autocomplete(server=servers)
    async def server(interaction: discord.Interaction, server: str | None = None, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        sid = await pick_server(interaction, lang, server)
        if sid:
            await send_card(interaction, lang, sid, public=share)

    # ── /sv and /ip: the Discord's own servers ──
    async def preset_choices(interaction, current: str):
        if not interaction.guild_id:
            return []
        return [app_commands.Choice(name=f"{'⭐ ' if d else ''}{n} · {addr}"[:100], value=n) for n, addr, _, d in bot.presets.all(interaction.guild_id)
                if current.casefold() in n.casefold()][:25]

    async def show_preset(interaction: discord.Interaction, name: str | None):
        lang = lang_for(interaction)
        if not interaction.guild:
            await interaction.response.send_message(embed=error_embed(t(lang, 'track.guild'), lang=lang), ephemeral=True)
            return
        rows = bot.presets.all(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(embed=error_embed(t(lang, 'sv.none'), t(lang, 'sv.none.hint'), lang), ephemeral=True)
            return
        preset = bot.presets.get(interaction.guild_id, name) if name else rows[0]
        if not preset:
            await interaction.response.send_message(embed=error_embed(t(lang, 'sv.unknown', name=esc(name)), lang=lang), ephemeral=True)
            return
        await interaction.response.defer()
        if preset[2]:
            await send_card(interaction, lang, preset[2], preset, public=True)
        else:
            await interaction.followup.send(embed=preset_embed(lang, preset), view=ServerView(bot, lang, None, None, preset[1]))

    @bot.tree.command(name='sv', description="🎮 Our server: name, live status and the client.connect line to copy")
    @app_commands.describe(name='Saved server (empty = the default one)')
    @app_commands.autocomplete(name=preset_choices)
    async def sv(interaction: discord.Interaction, name: str | None = None):
        await show_preset(interaction, name)

    @bot.tree.command(name='ip', description='🔌 Same as /sv: the client.connect line of our server')
    @app_commands.describe(name='Saved server (empty = the default one)')
    @app_commands.autocomplete(name=preset_choices)
    async def ip(interaction: discord.Interaction, name: str | None = None):
        await show_preset(interaction, name)

    @bot.tree.command(name='setserver', description='📌 Save a server for /sv and /ip (server managers)')
    @app_commands.describe(name='Name to show, e.g. Main', address='IP:port (or the whole client.connect line)', battlemetrics='BattleMetrics server for live status (optional)',
                           default='Show this one when /sv is used without a name')
    @app_commands.autocomplete(battlemetrics=servers)
    async def setserver(interaction: discord.Interaction, name: app_commands.Range[str, 1, 40], address: str | None = None, battlemetrics: str | None = None, default: bool = False):
        lang = lang_for(interaction)
        if not await can_manage(interaction):
            await interaction.response.send_message(embed=error_embed(t(lang, 'err.admin'), t(lang, 'err.admin.hint'), lang), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        sid = None
        if battlemetrics:
            try:
                sid = bot.directory.resolve(battlemetrics)
            except ValueError:
                await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
                return
        if address:
            match = ADDRESS.match(address.strip().strip('`'))
            if not match:
                await interaction.followup.send(embed=error_embed(t(lang, 'sv.bad_address'), t(lang, 'sv.bad_address.hint'), lang), ephemeral=True)
                return
            address = match[1]
        elif sid:
            try:
                a = (await bot.bm.server(sid))['attributes']
                address = f"{a['ip']}:{a['port']}" if a.get('ip') and a.get('port') else None
            except Exception:
                address = None
        if not address:
            await interaction.followup.send(embed=error_embed(t(lang, 'sv.need_address'), t(lang, 'sv.bad_address.hint'), lang), ephemeral=True)
            return
        bot.presets.save(interaction.guild_id, name.strip(), address, sid, default, interaction.user.id)
        e = success_embed(t(lang, 'sv.saved', name=esc(name.strip())))
        e.add_field(name=t(lang, 'server.connect'), value=f'```\n{connect_line(address)}\n```', inline=False)
        e.set_footer(text=t(lang, 'sv.saved.footer'))
        await interaction.followup.send(embed=e, ephemeral=True)

    @bot.tree.command(name='delserver', description='🗑️ Remove a saved /sv server (server managers)')
    @app_commands.describe(name='Saved server')
    @app_commands.autocomplete(name=preset_choices)
    async def delserver(interaction: discord.Interaction, name: str):
        lang = lang_for(interaction)
        if not await can_manage(interaction):
            await interaction.response.send_message(embed=error_embed(t(lang, 'err.admin'), t(lang, 'err.admin.hint'), lang), ephemeral=True)
            return
        if bot.presets.delete(interaction.guild_id, name):
            await interaction.response.send_message(embed=success_embed(t(lang, 'sv.deleted', name=esc(name))), ephemeral=True)
        else:
            await interaction.response.send_message(embed=error_embed(t(lang, 'sv.unknown', name=esc(name)), lang=lang), ephemeral=True)

    # ── /serverstats ──
    PERIODS = [app_commands.Choice(name='24 h', value=1), app_commands.Choice(name='7 days', value=7), app_commands.Choice(name='30 days', value=30)]

    @bot.tree.command(name='serverstats', description='📈 Server history: players, rank, new players and outages')
    @app_commands.describe(server='Server name or BattleMetrics server ID (empty = yours)', period='Time range', share='Publish the result in this channel')
    @app_commands.choices(period=PERIODS)
    @app_commands.autocomplete(server=servers)
    async def serverstats(interaction: discord.Interaction, server: str | None = None, period: int = 7, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        sid = await pick_server(interaction, lang, server)
        if not sid:
            return
        try:
            a = (await bot.bm.server(sid))['attributes']
            counts = await bot.bm.history(sid, 'player-count', period, '60' if period <= 7 else '1440')
            ranks = await bot.bm.history(sid, 'rank', period)
            unique = await bot.bm.history(sid, 'unique-player', period)
            new = await bot.bm.history(sid, 'first-time', period)
            outages = await bot.bm.outages(sid, period)
        except Exception:
            logging.info('serverstats failed for %s', sid, exc_info=True)
            await interaction.followup.send(embed=error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang), ephemeral=not share)
            return
        values = [v for _, v in counts]
        e = brand_embed(t(lang, 'stats.title', server=a.get('name', sid), period=t(lang, f'stats.period.{period}'))[:256], color=YELLOW)
        e.url = f'https://www.battlemetrics.com/servers/rust/{sid}'
        if values:
            e.description = f"```\n{spark(values, 30)}\n```" + t(lang, 'stats.players', peak=int(max(values)), avg=round(sum(values) / len(values)), low=int(min(values)),
                                                                 now=a.get('players', 0), m=a.get('maxPlayers', 0))
        if ranks:
            best = min(v for _, v in ranks)
            e.add_field(name=t(lang, 'server.rank'), value=t(lang, 'stats.rank', now=f"#{int(ranks[-1][1]):,}", best=f'#{int(best):,}'))
        if unique:
            e.add_field(name=t(lang, 'stats.unique'), value=f"**{int(max(v for _, v in unique)):,}**")
        if new:
            e.add_field(name=t(lang, 'stats.new'), value=f"**{int(sum(v for _, v in new)):,}**")
        down = sum(((stop or int(time.time())) - start) for start, stop in outages)
        e.add_field(name=t(lang, 'stats.outages'), value=t(lang, 'stats.outages.value', n=len(outages), m=round(down / 60)) if outages else t(lang, 'stats.outages.none'), inline=False)
        e.set_footer(text=t(lang, 'stats.footer'))
        await interaction.followup.send(embed=e, view=ServerView(bot, lang, sid, a, None), ephemeral=not share)

    # ── /leaderboard ──
    LB_PERIODS = [app_commands.Choice(name='All time', value=0), app_commands.Choice(name='30 days', value=30), app_commands.Choice(name='7 days', value=7),
                  app_commands.Choice(name='24 h', value=1)]

    async def leaderboard_page(interaction, lang, sid, name, days, page, share):
        try:
            rows, more = await bot.bm.leaderboard(sid, days or None, (page - 1) * LEADERBOARD_PAGE, LEADERBOARD_PAGE)
        except Exception:
            return error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang), None
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}
        lines = []
        for r in rows:
            place = medals.get(r['rank']) or '`{:>3}`'.format(r['rank'] or '?')
            lines.append(f"{place} **{esc(r['name'])[:40]}** · {fmt_num(round(r['seconds'] / 3600, 1))} h")
        e = brand_embed(t(lang, 'top.title', server=name, period=t(lang, f'top.period.{days}'))[:256], '\n'.join(lines) or t(lang, 'top.none'), color=YELLOW)
        e.url = f'https://www.battlemetrics.com/servers/rust/{sid}/leaderboard'
        e.set_footer(text=t(lang, 'top.footer', page=page))
        view = OwnedView(interaction.user.id)
        if rows:
            from .activity import copy_ids_button, profile_picker
            view.add_item(profile_picker(bot, lang, rows))
            copy = copy_ids_button(lang, rows)
            copy.row = 1
            view.add_item(copy)
        for emoji, delta, disabled in (('◀️', -1, page <= 1), ('▶️', 1, not more)):
            button = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary, disabled=disabled, row=1)

            async def go(i, delta=delta):
                embed, new_view = await leaderboard_page(i, lang, sid, name, days, page + delta, share)
                new_view.message = i.message
                await i.response.edit_message(embed=embed, view=new_view)
            button.callback = go
            view.add_item(button)
        return e, view

    @bot.tree.command(name='leaderboard', description='🏆 Players with the most hours on a server')
    @app_commands.describe(server='Server name or BattleMetrics server ID (empty = yours)', period='Time range', share='Publish the result in this channel')
    @app_commands.choices(period=LB_PERIODS)
    @app_commands.autocomplete(server=servers)
    async def leaderboard(interaction: discord.Interaction, server: str | None = None, period: int = 7, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        sid = await pick_server(interaction, lang, server)
        if not sid:
            return
        embed, view = await leaderboard_page(interaction, lang, sid, bot.directory.name(sid), period, 1, share)
        kwargs = {'embed': embed, 'ephemeral': not share}
        if view:
            kwargs['view'] = view
        await interaction.followup.send(**kwargs)
        if view:
            view.message = await interaction.original_response()

    # ── /serversearch ──
    @bot.tree.command(name='serversearch', description='🔎 Find Rust servers: name, country, rates, group size, wipe')
    @app_commands.describe(query='Name to search (optional)', country='Two-letter country code, e.g. US, MX, DE', min_players='Minimum players online',
                           gather='Gather rate', group='Maximum group size', kind='Server type', wiped='Wiped in the last N days', pve='PvE only (true) or PvP only (false)')
    @app_commands.choices(gather=[app_commands.Choice(name='1x (vanilla)', value='1'), app_commands.Choice(name='2x', value='2'), app_commands.Choice(name='3x+', value='3')],
                          group=[app_commands.Choice(name=n, value=v) for n, v in (('Solo', '1'), ('Duo', '2'), ('Trio', '3'), ('Quad', '4'))],
                          kind=[app_commands.Choice(name='Official', value='official'), app_commands.Choice(name='Community', value='community'),
                                app_commands.Choice(name='Modded', value='modded')])
    async def serversearch(interaction: discord.Interaction, query: app_commands.Range[str, 0, 100] = '', country: app_commands.Range[str, 2, 2] | None = None,
                           min_players: app_commands.Range[int, 0, 1000] = 0, gather: str | None = None, group: str | None = None, kind: str | None = None,
                           wiped: app_commands.Range[int, 1, 60] | None = None, pve: bool | None = None):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await bot.bm.find_servers(query.strip(), country, min_players, size=100 if any(x is not None for x in (gather, group, kind, wiped, pve)) else 25)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'search.fail'), lang=lang), ephemeral=True)
            return
        found = [s for s in rows if server_matches(s.get('attributes') or {}, gather, group, kind, wiped, pve)][:10]
        lines = []
        for s in found:
            a = s['attributes']
            d = a.get('details') or {}
            queue = d.get('rust_queued_players')
            extra = ' · '.join(x for x in (
                f"👥 {a.get('players', 0)}/{a.get('maxPlayers', 0)}" + (f' · ⏳ {queue}' if queue else ''),
                f"🏆 #{a['rank']:,}" if a.get('rank') else '', a.get('country') or '',
                t(lang, 'search.wiped', ts=iso_to_ts(d.get('rust_last_wipe'))) if iso_to_ts(d.get('rust_last_wipe')) else '', f"🆔 `{s['id']}`") if x)
            info = settings_line(lang, d)
            lines.append(f"{'🟢' if a.get('status') == 'online' else '🔴'} [{esc(a['name'][:70])}](https://www.battlemetrics.com/servers/rust/{s['id']})\n-# {extra}" + (f'\n-# {info}' if info else ''))
        title = t(lang, 'search.title', q=query) if query else t(lang, 'search.title.any')
        e = brand_embed(title[:256], '\n'.join(lines)[:4000] or t(lang, 'search.none'))
        e.set_footer(text=t(lang, 'search.footer'))
        view = OwnedView(interaction.user.id)
        if found:
            select = discord.ui.Select(placeholder=t(lang, 'search.pick'), options=[
                discord.SelectOption(label=s['attributes']['name'][:100], value=str(s['id']), description=f"👥 {s['attributes'].get('players', 0)}/{s['attributes'].get('maxPlayers', 0)}")
                for s in found])

            async def chosen(i):
                await bot.tree.get_command('server').callback(i, server=i.data['values'][0])
            select.callback = chosen
            view.add_item(select)
        await interaction.followup.send(embed=e, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    # ── /rust ──
    @bot.tree.command(name='rust', description='🦀 Rust right now: players and servers worldwide')
    async def rust(interaction: discord.Interaction):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            g = await bot.bm.game('rust')
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'bm.fail'), lang=lang), ephemeral=True)
            return
        e = brand_embed(t(lang, 'rust.title'), t(lang, 'rust.body', p=g.get('players') or 0, s=g.get('servers') or 0), color=ORANGE)
        if g.get('maxPlayers24H'):
            e.add_field(name=t(lang, 'rust.24h'), value=t(lang, 'rust.range', low=g.get('minPlayers24H') or 0, high=g['maxPlayers24H']))
        if g.get('maxPlayers7D'):
            e.add_field(name=t(lang, 'rust.7d'), value=t(lang, 'rust.peak', high=g['maxPlayers7D']))
        e.set_thumbnail(url='https://wiki.rustclash.com/img/items180/explosive.timed.png')
        e.set_footer(text='BattleMetrics')
        await interaction.followup.send(embed=e, ephemeral=True)

    return pick_server
