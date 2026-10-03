"""Per-user settings keyed by Discord ID: /me.

A member saves their own BattleMetrics profile (ID or profile URL) and, optionally, a default server.
Commands with an optional server then use, in order: the server that member is playing on right now,
their default server, and finally the Discord server's default /sv entry. That makes things like
"who is on my server" or "find this name on my server" a single command with no IDs to type.
"""
from __future__ import annotations
import logging
import time
import discord
from discord import app_commands
from .i18n import lang_for, t
from .players import AskModal, remember
from .servers import profile_id
from .ui import GREEN, OwnedView, YELLOW, error_embed, success_embed


class UserStore:
    def __init__(self, conn):
        self.conn = conn
        conn.execute('CREATE TABLE IF NOT EXISTS user_config(user_id INTEGER PRIMARY KEY,bm_id TEXT,server_id TEXT,updated_at REAL)')
        conn.commit()

    def get(self, user_id: int) -> tuple[str | None, str | None]:
        row = self.conn.execute('SELECT bm_id,server_id FROM user_config WHERE user_id=?', (user_id,)).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def set(self, user_id: int, bm_id: str | None = None, server_id: str | None = None):
        old_bm, old_server = self.get(user_id)
        self.conn.execute('INSERT OR REPLACE INTO user_config VALUES(?,?,?,?)', (user_id, bm_id or old_bm, server_id or old_server, time.time()))
        self.conn.commit()

    def clear(self, user_id: int):
        self.conn.execute('DELETE FROM user_config WHERE user_id=?', (user_id,))
        self.conn.commit()


async def current_server(bot, user_id: int) -> tuple[str | None, str | None]:
    """(server ID, server name) where this member is playing right now, from their saved BattleMetrics profile."""
    bm_id, _ = bot.users_cfg.get(user_id)
    if not bm_id or not bot.bm.token:
        return None, None
    try:
        online, sid, name = await bot.bm.presence_any(bm_id)
    except Exception as exc:
        logging.info('me: presence failed for %s: %r', bm_id, exc)
        return None, None
    return (sid, name) if online else (None, None)


async def default_server(bot, interaction) -> tuple[str | None, str]:
    """(server ID, source) for commands whose server is optional. Source: 'live', 'me', 'guild' or 'none'."""
    sid, _ = await current_server(bot, interaction.user.id)
    if sid:
        return sid, 'live'
    _, saved = bot.users_cfg.get(interaction.user.id)
    if saved:
        return saved, 'me'
    if interaction.guild_id and (preset := bot.presets.default(interaction.guild_id)) and preset[2]:
        return preset[2], 'guild'
    return None, 'none'


def register_profiles(bot):
    bot.users_cfg = UserStore(bot.store.conn)

    async def card(interaction, lang) -> tuple[discord.Embed, OwnedView]:
        bm_id, saved = bot.users_cfg.get(interaction.user.id)
        e = discord.Embed(title=t(lang, 'me.title', name=interaction.user.display_name), color=GREEN if bm_id else YELLOW)
        if bm_id:
            name = bot.store.player_name(-interaction.user.id, bm_id) or bm_id
            e.add_field(name=t(lang, 'me.bm'), value=f'[{discord.utils.escape_markdown(name)}](https://www.battlemetrics.com/players/{bm_id}) · `{bm_id}`', inline=False)
            sid, sname = await current_server(bot, interaction.user.id)
            e.add_field(name=t(lang, 'me.now'), value=f'🟢 **{discord.utils.escape_markdown(sname)}**' if sid else t(lang, 'me.not_playing'), inline=False)
        else:
            e.description = t(lang, 'me.empty')
        e.add_field(name=t(lang, 'me.server'), value=f'🖥️ {discord.utils.escape_markdown(bot.directory.name(saved))}' if saved else t(lang, 'me.server.none'), inline=False)
        e.set_footer(text=t(lang, 'me.footer'))
        view = OwnedView(interaction.user.id)

        async def set_bm(i, value):
            await me.callback(i, battlemetrics=value)
        link = discord.ui.Button(label=t(lang, 'me.button.bm'), emoji='🔗', style=discord.ButtonStyle.primary)

        async def ask_bm(i):
            await i.response.send_modal(AskModal(t(lang, 'me.button.bm'), t(lang, 'me.ask_bm'), 'https://www.battlemetrics.com/players/1128280744', set_bm))
        link.callback = ask_bm
        view.add_item(link)
        if bm_id or saved:
            mine = discord.ui.Button(label=t(lang, 'me.button.online'), emoji='👥', style=discord.ButtonStyle.secondary)

            async def online(i):
                await bot.tree.get_command('online').callback(i)
            mine.callback = online
            view.add_item(mine)
            find = discord.ui.Button(label=t(lang, 'me.button.find'), emoji='🔎', style=discord.ButtonStyle.secondary)

            async def find_here(i, name):
                await bot.tree.get_command('findplayer').callback(i, name=name[:64])

            async def ask_find(i):
                await i.response.send_modal(AskModal(t(lang, 'me.button.find'), t(lang, 'player.ask_name'), 'KingGallardo', find_here))
            find.callback = ask_find
            view.add_item(find)
            forget = discord.ui.Button(label=t(lang, 'me.button.forget'), emoji='🗑️', style=discord.ButtonStyle.danger)

            async def clear(i):
                await me.callback(i, forget=True)
            forget.callback = clear
            view.add_item(forget)
        return e, view

    @bot.tree.command(name='me', description='👤 Your settings: your BattleMetrics profile and default server')
    @app_commands.describe(battlemetrics='Your BattleMetrics player ID or profile URL', server='Your default server (used when you are not playing)',
                           forget='Delete your saved settings')
    @app_commands.autocomplete(server=bot.server_choices)
    async def me(interaction: discord.Interaction, battlemetrics: str | None = None, server: str | None = None, forget: bool = False):
        lang = lang_for(interaction)
        if forget:
            bot.users_cfg.clear(interaction.user.id)
            await interaction.response.send_message(embed=success_embed(t(lang, 'me.forgotten')), ephemeral=True)
            return
        if battlemetrics or server:
            await interaction.response.defer(ephemeral=True)
            bm_id = sid = None
            try:
                if battlemetrics:
                    bm_id = profile_id(battlemetrics)
                if server:
                    sid = bot.directory.resolve(server)
            except ValueError:
                key = 'bm.profile_link' if battlemetrics and not bm_id else 'server.pick'
                await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=True)
                return
            if bm_id:
                try:
                    profile = await bot.bm.profile(bm_id)
                except Exception:
                    await interaction.followup.send(embed=error_embed(t(lang, 'me.bm_fail'), lang=lang), ephemeral=True)
                    return
                name = ((profile.get('data') or {}).get('attributes') or {}).get('name') or bm_id
                # Saved in the member's private book too, so the card can show the name without a request.
                bot.store.remember_player(-interaction.user.id, name, None, bm_id)
                await remember(bot, interaction, bm_id=bm_id, name=name)
            bot.users_cfg.set(interaction.user.id, bm_id, sid)
            embed, view = await card(interaction, lang)
            embed.description = '✅ ' + t(lang, 'me.saved')
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return
        await interaction.response.defer(ephemeral=True)
        embed, view = await card(interaction, lang)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    return me
