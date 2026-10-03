"""Server and admin commands: /ping, /status, /servers, /serversearch, /syncservers, /wipe, /forcewipe, alerts."""
from __future__ import annotations
import math
from datetime import date, datetime, timedelta, timezone
import discord
from discord import app_commands
from .i18n import lang_for, t
from .ui import GREEN, ORANGE, OwnedView, brand_embed, error_embed, success_embed

PAGE_SIZE = 10


def iso_to_ts(value) -> int | None:
    """BattleMetrics ISO date -> Unix timestamp (None when missing or invalid)."""
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except (AttributeError, ValueError, TypeError):
        return None


# ── Forced wipe schedule ──

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th given weekday (Mon=0) of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _us_eastern_offset(day: date) -> int:
    """UTC offset in hours for US Eastern on `day` (DST: 2nd Sunday of March to 1st Sunday of November)."""
    dst_start = _nth_weekday(day.year, 3, 6, 2)
    dst_end = _nth_weekday(day.year, 11, 6, 1)
    return -4 if dst_start <= day < dst_end else -5


def forced_wipes(now: datetime | None = None, count: int = 4) -> list[datetime]:
    """Next forced wipes: first Thursday of each month at 2 PM US Eastern, as UTC datetimes."""
    now = now or datetime.now(timezone.utc)
    out, year, month = [], now.year, now.month
    while len(out) < count:
        day = _nth_weekday(year, month, 3, 1)
        moment = datetime(day.year, day.month, day.day, 14 - _us_eastern_offset(day), tzinfo=timezone.utc)
        if moment > now:
            out.append(moment)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def servers_page_embed(lang: str, rows: list[dict], query: str, page: int) -> tuple[discord.Embed, int]:
    """Page `page` (1-based) of the filtered directory."""
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = max(1, min(page, pages))
    lines = [f"• [{discord.utils.escape_markdown(r['name'])}](https://www.battlemetrics.com/servers/rust/{r['id']})"
             for r in rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]]
    title = t(lang, 'servers.title', page=page, pages=pages) + (f' · «{query}»' if query else '')
    e = brand_embed(title, '\n'.join(lines) or t(lang, 'servers.none'))
    e.set_footer(text=t(lang, 'servers.footer', n=len(rows)))
    return e, pages


class ServerPagesView(OwnedView):
    """◀️ ▶️ buttons to browse the directory without retyping the command."""

    def __init__(self, lang, rows, query, page, owner_id=None):
        super().__init__(owner_id)
        self.lang, self.rows, self.query, self.page = lang, rows, query, page
        _, pages = servers_page_embed(lang, rows, query, page)
        self.prev.disabled = page <= 1
        self.next.disabled = page >= pages
        self.counter.label = f'{page}/{pages}'

    async def _go(self, interaction, page):
        e, _ = servers_page_embed(self.lang, self.rows, self.query, page)
        view = ServerPagesView(self.lang, self.rows, self.query, page, self.owner_id)
        view.message = interaction.message
        await interaction.response.edit_message(embed=e, view=view)

    @discord.ui.button(emoji='◀️', style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, _):
        await self._go(interaction, self.page - 1)

    @discord.ui.button(label='1/1', style=discord.ButtonStyle.secondary, disabled=True)
    async def counter(self, interaction, _):
        pass

    @discord.ui.button(emoji='▶️', style=discord.ButtonStyle.secondary)
    async def next(self, interaction, _):
        await self._go(interaction, self.page + 1)


def register_utilities(bot, catalog, require_admin):
    async def servers(interaction, current: str):
        return [app_commands.Choice(name=r['name'][:100], value=r['id']) for r in bot.directory.search(current)]

    def guild_watches(interaction):
        # Only watches whose channels belong to this Discord server.
        return [w for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and ch.guild and ch.guild.id == interaction.guild_id]

    @bot.tree.command(name='ping', description='🏓 Check the bot connection')
    async def ping(interaction):
        latency = bot.latency
        if not math.isfinite(latency):
            await interaction.response.send_message(t(lang_for(interaction), 'ping.connecting'), ephemeral=True)
            return
        ms = round(latency * 1000)
        dot = '🟢' if ms < 150 else '🟡' if ms < 400 else '🔴'
        await interaction.response.send_message(f'🏓 Pong · {dot} **{ms} ms**', ephemeral=True)

    @bot.tree.command(name='status', description='📡 Bot status, watches and settings for this server')
    async def status(interaction):
        if not await require_admin(interaction):
            return
        lang = lang_for(interaction)
        saved = bot.store.settings(interaction.guild_id)
        watches = guild_watches(interaction)
        online = sum(w.was_online == 1 for w in watches)
        unknown = sum(w.was_online is None or not w.steamid.startswith('bm:') for w in watches)
        running = bot.poll.is_running()
        alerts = not saved or saved[2]
        e = brand_embed(t(lang, 'status.title'), color=GREEN if running and alerts else ORANGE)
        e.add_field(name=t(lang, 'status.tracker'), value=t(lang, 'status.running' if running else 'status.stopped'))
        e.add_field(name=t(lang, 'settings.alerts'), value=('🟢 ' if alerts else '⏸️ ') + t(lang, 'settings.on' if alerts else 'settings.off'))
        e.add_field(name=t(lang, 'settings.interval'), value=f'{saved[3] if saved else bot.settings.poll_interval} s')
        e.add_field(name=t(lang, 'status.watches'), value=t(lang, 'status.watches.value', n=len(watches), on=online, unknown=unknown), inline=False)
        e.add_field(name=t(lang, 'settings.channel'), value=f'<#{saved[0]}>' if saved else t(lang, 'status.channel.default'))
        e.add_field(name=t(lang, 'status.directory'), value=t(lang, 'status.directory.value', n=len(bot.directory.rows)))
        e.set_footer(text=t(lang, 'status.footer'))
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name='servers', description='🖥️ Browse the server directory')
    @app_commands.describe(query='Filter by part of the name', page='Start page')
    async def list_servers(interaction, query: str = '', page: app_commands.Range[int, 1, 1000] = 1):
        lang = lang_for(interaction)
        rows = [r for r in bot.directory.rows if query.casefold() in r['name'].casefold()]
        e, pages = servers_page_embed(lang, rows, query, page)
        if page > pages:
            await interaction.response.send_message(embed=error_embed(t(lang, 'servers.pages', n=pages), lang=lang), ephemeral=True)
            return
        await interaction.response.send_message(embed=e, view=ServerPagesView(lang, rows, query, page, interaction.user.id), ephemeral=True)

    @bot.tree.command(name='serversearch', description='🔎 Search any Rust server on BattleMetrics')
    @app_commands.describe(query='Server name to search')
    async def server_search(interaction, query: app_commands.Range[str, 2, 100]):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await bot.bm.search_servers(query)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'search.fail'), lang=lang), ephemeral=True)
            return
        lines = []
        for s in rows[:10]:
            a = s['attributes']
            dot = '🟢' if a.get('status') == 'online' else '🔴'
            queue = (a.get('details') or {}).get('rust_queued_players')
            extra = f" · ⏳ {queue}" if queue else ''
            rank = f" · 🏆 #{a['rank']:,}" if a.get('rank') else ''
            flag = f" · {a['country']}" if a.get('country') else ''
            lines.append(f"{dot} [{discord.utils.escape_markdown(a['name'][:70])}](https://www.battlemetrics.com/servers/rust/{s['id']})\n"
                         f"-# 👥 {a.get('players', 0)}/{a.get('maxPlayers', 0)}{extra}{rank}{flag}")
        e = brand_embed(t(lang, 'search.title', q=query), '\n'.join(lines) or t(lang, 'search.none'))
        e.set_footer(text=t(lang, 'search.footer'))
        await interaction.followup.send(embed=e, ephemeral=True)

    @bot.tree.command(name='syncservers', description='📥 Import servers from a BattleMetrics profile')
    async def sync_servers(interaction, profile: str = '1128280744'):
        if not await require_admin(interaction):
            return
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            data = await bot.bm.profile(await bot.bm.resolve_player(profile))
            rows = [{'id': r['id'], 'name': r['attributes']['name'].strip()} for r in data.get('included', [])
                    if r.get('type') == 'server' and r.get('relationships', {}).get('game', {}).get('data', {}).get('id') == 'rust']
            if not rows:
                await interaction.followup.send(embed=error_embed(t(lang, 'sync.none'), lang=lang), ephemeral=True)
                return
            bot.store.save_servers(rows)
            bot.directory.merge(rows)
            await interaction.followup.send(embed=success_embed(t(lang, 'sync.done', n=len(rows))), ephemeral=True)
        except ValueError as exc:
            key = str(exc) if str(exc).startswith('identity.') else 'identity.input'
            await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'sync.fail'), t(lang, 'sync.fail.hint'), lang), ephemeral=True)

    async def toggle(interaction, enabled):
        if not await require_admin(interaction):
            return
        # Keep channel, language and interval; only flip the alerts switch.
        saved = bot.store.settings(interaction.guild_id) or (interaction.channel_id, 'en', 1, bot.settings.poll_interval)
        bot.store.set_settings(interaction.guild_id, saved[0], saved[1], enabled, saved[3])
        await interaction.response.send_message(t(lang_for(interaction), 'alerts.resumed' if enabled else 'alerts.paused'), ephemeral=True)

    @bot.tree.command(name='pausealerts', description='⏸️ Pause alerts without deleting watches')
    async def pause_alerts(interaction):
        await toggle(interaction, False)

    @bot.tree.command(name='resumealerts', description='🔔 Resume alerts for future changes')
    async def resume_alerts(interaction):
        await toggle(interaction, True)

    @bot.tree.command(name='wipe', description="🗓️ A server's last and next wipe")
    @app_commands.describe(server='Type part of the name and pick a suggestion')
    @app_commands.autocomplete(server=servers)
    async def wipe(interaction, server: str):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            a = (await bot.bm.server(bot.directory.resolve(server)))['attributes']
            details = a.get('details', {}) or {}
            lines = []
            for label, key in [('wipe.last', 'rust_last_wipe'), ('wipe.next', 'rust_next_wipe')]:
                stamp = iso_to_ts(details.get(key))
                lines.append(f'**{t(lang, label)}**: ' + (f'<t:{stamp}:F> · <t:{stamp}:R>' if stamp else t(lang, 'wipe.unpublished')))
            e = brand_embed(f"🗓️ {a.get('name', 'Server')}", '\n'.join(lines))
            e.set_footer(text=t(lang, 'wipe.footer'))
            await interaction.followup.send(embed=e, ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'wipe.fail'), t(lang, 'server.fail.hint'), lang), ephemeral=True)

    @bot.tree.command(name='forcewipe', description='🗓️ Next Facepunch forced wipe with countdown')
    async def forcewipe(interaction):
        lang = lang_for(interaction)
        upcoming = forced_wipes()
        ts = int(upcoming[0].timestamp())
        e = brand_embed(t(lang, 'forcewipe.title'), t(lang, 'forcewipe.body', ts=ts))
        e.add_field(name=t(lang, 'forcewipe.after'), value='\n'.join(f'• <t:{int(d.timestamp())}:D> · <t:{int(d.timestamp())}:R>' for d in upcoming[1:]), inline=False)
        e.set_thumbnail(url='https://wiki.rustclash.com/img/items180/map.png')
        e.set_footer(text=t(lang, 'forcewipe.footer'))
        await interaction.response.send_message(embed=e)
