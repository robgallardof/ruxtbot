"""Read-only activity tools using exact player identifiers."""
from __future__ import annotations
import discord
from discord import app_commands
from .i18n import lang_for, t
from .ui import brand_embed, error_embed
from .utility_commands import iso_to_ts


def safe(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))[:80]


async def presence_lines(bot, pid, data):
    known = {r['id'] for r in bot.directory.rows}
    rows = [r for r in data.get('included', []) if r.get('type') == 'server' and r['id'] in known]
    rows.sort(key=lambda r: (r.get('meta') or {}).get('lastSeen') or '', reverse=True)
    lines = []
    for row in rows:
        state = await bot.bm.player_online(row['id'], 'bm:' + pid)
        meta = row.get('meta') or {}
        stamp = iso_to_ts(meta.get('lastSeen'))
        hours = meta.get('timePlayed')
        detail = f" · {hours / 3600:,.1f} h" if isinstance(hours, (int, float)) else ''
        if stamp:
            detail += f' · <t:{stamp}:R>'
        lines.append(f"{ {True: '🟢', False: '🔴', None: '⚪'}[state]} **{safe(row['attributes'].get('name', row['id']))}**{detail}")
    return lines


def register_activity(bot):
    async def servers(interaction, current: str):
        return [app_commands.Choice(name=r['name'][:100], value=r['id']) for r in bot.directory.search(current)]

    @bot.tree.command(description='Presence on synchronized servers from a SteamID')
    @app_commands.describe(player='SteamID64 or BattleMetrics player ID', page='Page of 10 servers', share='Publish the result in this channel')
    async def presence(interaction: discord.Interaction, player: str, page: app_commands.Range[int, 1, 1000] = 1, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            pid = await bot.bm.resolve_player(player)
            data = await bot.bm.profile(pid)
            lines = await presence_lines(bot, pid, data)
            pages = max(1, (len(lines) + 9) // 10)
            page = min(page, pages)
            e = brand_embed(t(lang, 'activity.title') + f' · {page}/{pages}', '\n'.join(lines[(page-1)*10:page*10]) or t(lang, 'activity.empty'))
            e.set_footer(text=t(lang, 'activity.footer'))
            await interaction.followup.send(embed=e, ephemeral=not share)
        except Exception as exc:
            key = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('identity.') else 'identity.unavailable'
            await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=not share)

    @bot.tree.command(description='Recent player sessions, timestamps and duration')
    @app_commands.describe(player='SteamID64 or BattleMetrics player ID', server='Optional server name', share='Publish the result in this channel')
    @app_commands.autocomplete(server=servers)
    async def sessions(interaction: discord.Interaction, player: str, server: str | None = None, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            pid = await bot.bm.resolve_player(player)
            sid = bot.directory.resolve(server) if server else None
            data = await bot.bm.sessions(pid, sid)
            names = {r['id']: r['attributes'].get('name', r['id']) for r in data.get('included', []) if r.get('type') == 'server'}
            lines = []
            for row in data.get('data', [])[:10]:
                a = row.get('attributes') or {}
                start, stop = iso_to_ts(a.get('start')), iso_to_ts(a.get('stop'))
                if not start:
                    continue
                server_id = row.get('relationships', {}).get('server', {}).get('data', {}).get('id', '')
                end = f'<t:{stop}:f>' if stop else t(lang, 'sessions.open')
                duration = f' · {max(0, stop-start)/3600:.1f} h' if stop else ''
                lines.append(f"**{safe(names.get(server_id, bot.directory.name(server_id)))}**\n<t:{start}:f> → {end}{duration}")
            e = brand_embed(t(lang, 'sessions.title'), '\n'.join(lines) or t(lang, 'sessions.empty'))
            e.set_footer(text=t(lang, 'sessions.footer'))
            await interaction.followup.send(embed=e, ephemeral=not share)
        except Exception as exc:
            key = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('identity.') else 'identity.unavailable'
            await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=not share)
