"""RuxtBot entry point: the bot, the presence tracker and the core commands.

Larger command groups live in their own modules:
    raid.py              /raid, /raidcalc, /raidbudget, /raidcompare, /raidtools
    who.py               /who, /steamid
    activity.py          /presence, /sessions, /online, /findplayer, /playercompare
    alerts.py            /wipealert, /serverwatch, /team (+ their background loop)
    base.py              /upkeep, /decay
    profiles.py          /me (per-member settings)
    serverinfo.py        /server, /sv, /ip, /setserver, /delserver, /serverstats, /leaderboard, /serversearch, /rust
    maintenance.py       /version, /update, /restart
    utility_commands.py  /ping, /status, /servers, /serversearch, /syncservers, /wipe, /forcewipe, alerts
    help.py              /help menu
    info_commands.py     /author, /examples
"""
from __future__ import annotations
import logging
import time
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
from .battlemetrics import BattleMetrics
from .catalog import Catalog
from .config import Settings
from .help import help_layout
from .i18n import CommandTranslator, lang_for, t
from .info_commands import register_info
from .activity import register_activity, presence_lines
from .alerts import register_alerts
from .base import register_base
from .maintenance import register_maintenance
from .profiles import register_profiles
from .serverinfo import register_serverinfo, spark
from .raid import register_raid_commands
from .raid_data import RaidData
from .players import choice_label, expand, player_autocomplete, player_error, remember, resolve_player, scope_of, steam_of
from .servers import ANY, ServerDirectory, server_autocomplete
from .tracking import Store, transition
from .track_ui import TrackingPanel
from .ui import GREEN, GREY, RED, brand_embed, error_embed, reply, success_embed
from .utility_commands import iso_to_ts, register_utilities
from .who import WhoService, register_who

# Crafting catalog item -> raid explosive key in data/raid.json (for "raid uses" on /item).
CATALOG_TO_RAID = {
    'rocket': 'rocket', 'c4': 'c4', 'satchel': 'satchel', 'explosive-ammo': 'explosive556', 'beancan': 'beancan', 'f1': 'f1',
    'hv-rocket': 'hv_rocket', 'molotov': 'molotov', 'mlrs': 'mlrs', 'hammerhead': 'hammerhead', 'ram': 'ram',
    'propane': 'propane_bomb', 'catapult-propane': 'catapult_propane', 'he-grenade': 'he_grenade', 'cannonball': 'cannonball',
    'mortar': 'mortar', 'incendiary-rocket': 'incendiary_rocket',
}


class RustBot(commands.Bot):
    """Bot with shared state: database, HTTP clients, raid data and server directory."""

    def __init__(self, settings, catalog, raid_data=None):
        super().__init__(command_prefix='!', intents=discord.Intents.default())
        self.settings, self.catalog = settings, catalog
        self.raid_data = raid_data or RaidData.load(Path(settings.data_path).with_name('raid.json'))
        self.store = Store(settings.state_path)
        self.bm = BattleMetrics(settings.battlemetrics_token)
        self.bm.identities = self.store
        self.who = WhoService(self.bm, settings.steam_api_key)
        # Base directory (servers.json) + servers imported with /syncservers.
        self.directory = ServerDirectory(Path(settings.data_path).with_name('servers.json'))
        self.directory.merge(self.store.servers())
        self.server_choices = server_autocomplete(self)
        self.last_poll = {}  # (steamid, server, channel) -> last check, to honour the interval
        self.extra_loops = []  # background loops registered by command modules (alerts)
        self.poll.change_interval(seconds=10)

    async def setup_hook(self):
        await self.tree.set_translator(CommandTranslator())
        await self.tree.sync()
        self.poll.start()
        for loop in self.extra_loops:
            loop.start()

    async def on_ready(self):
        logging.info('RuxtBot connected as %s', self.user)
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='raids · /help'))

    async def close(self):
        self.poll.cancel()
        for loop in self.extra_loops:
            loop.cancel()
        await self.bm.client.aclose()
        await self.who.client.aclose()
        self.store.conn.close()
        await super().close()

    @tasks.loop(seconds=10)
    async def poll(self):
        """Check every watch and ping the alert role and the watch's creator only when the state changes.

        Safety rules:
        - Unknown data (None) never counts as a disconnect.
        - The first reading is silent (it only sets the baseline).
        - If Discord fails to deliver, the state is not saved, so the alert is retried next loop.
        """
        watches = self.store.watches()
        active = {(w.steamid, w.server_id, w.channel_id) for w in watches}
        self.last_poll = {k: v for k, v in self.last_poll.items() if k in active}
        observations = {}
        for w in watches:
            if w.expires_at and w.expires_at <= time.time():
                continue
            try:
                ch = self.get_channel(w.channel_id)
                if not ch or not ch.guild:
                    continue
                saved = self.store.settings(ch.guild.id)
                interval = saved[3] if saved else self.settings.poll_interval
                key = (w.steamid, w.server_id, w.channel_id)
                if time.monotonic() - self.last_poll.get(key, 0) < interval:
                    continue
                self.last_poll[key] = time.monotonic()
                observation_key = (w.steamid, w.server_id)
                if observation_key not in observations:
                    if w.server_id == ANY:
                        # "Any server" watch: where they are (or were last) decides the server shown in the alert.
                        observations[observation_key] = (await self.bm.presence_any(w.steamid[3:]) if w.steamid.startswith('bm:') else (None, None, None))
                    else:
                        observations[observation_key] = (await self.bm.player_online(w.server_id, w.steamid), w.server_id, None)
                online, where_id, where_name = observations[observation_key]
                if online is None:
                    continue
                event = transition(w.was_online, online)
                if event and (not saved or saved[2]):
                    role = alert_role(self.store, ch)
                    pings = ' '.join(x for x in (role.mention if role else '', f'<@{w.owner_id}>' if w.owner_id else '') if x)
                    lang = saved[1] if saved and saved[1] in ('en', 'es') else 'en'
                    # The label comes from player data: escape it so it can never mention anyone.
                    label = discord.utils.escape_markdown(discord.utils.escape_mentions(w.label or w.steamid))
                    name = discord.utils.escape_markdown(where_name or self.directory.name(where_id or w.server_id))
                    verb = t(lang, 'alert.connected' if online else 'alert.disconnected')
                    link = discord.ui.View()
                    link.add_item(discord.ui.Button(label=t(lang, 'alert.button'), emoji='📊', url=f'https://www.battlemetrics.com/servers/rust/{where_id or w.server_id}'))
                    await ch.send(f"{pings} {'🟢' if online else '🔴'} **{label}** {verb} **{name}** · <t:{int(time.time())}:R>".strip(), view=link,
                                  allowed_mentions=discord.AllowedMentions(roles=[role] if role else False,
                                                                           users=[discord.Object(w.owner_id)] if w.owner_id else False, everyone=False))
                self.store.set_state(w, online)
            except Exception:
                logging.exception('tracker poll failed')

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


def alert_role(store, channel):
    """Role to ping in alerts: the one chosen with /settings, else the only role named "wipe"; None if neither can be mentioned."""
    guild = channel.guild
    chosen = store.alert_role(guild.id)
    if chosen:
        roles = [guild.get_role(chosen)] if hasattr(guild, 'get_role') else [r for r in guild.roles if getattr(r, 'id', None) == chosen]
    else:
        roles = [r for r in guild.roles if r.name.casefold() == 'wipe']
    roles = [r for r in roles if r]
    if len(roles) != 1:
        return None
    role = roles[0]
    if not role.mentionable and not channel.permissions_for(guild.me).mention_everyone:
        logging.info('alert role %s is not mentionable in guild %s: alerts ping only the watch owner', role.name, guild.id)
        return None
    return role


async def can_manage(interaction) -> bool:
    """Server administrators, members with Manage Server, and the bot's owner."""
    if not interaction.guild:
        return False
    perms = interaction.user.guild_permissions
    if getattr(perms, 'administrator', False) or getattr(perms, 'manage_guild', False):
        return True
    try:
        return await interaction.client.is_owner(interaction.user)
    except Exception:
        return False


async def require_admin(interaction) -> bool:
    """Stop the interaction with a notice unless the user can manage the bot in this server."""
    if not await can_manage(interaction):
        lang = lang_for(interaction)
        await interaction.response.send_message(embed=error_embed(t(lang, 'err.admin'), t(lang, 'err.admin.hint'), lang), ephemeral=True)
        return False
    return True


def recent_rust_servers(profile: dict, days: int = 14, limit: int = 5) -> list[dict]:
    """Rust servers the player was seen on in the last `days` days (at least the latest one), newest first."""
    servers = [s for s in profile.get('included', []) if s.get('type') == 'server'
               and (s.get('relationships') or {}).get('game', {}).get('data', {}).get('id', 'rust') == 'rust']
    servers.sort(key=lambda s: (s.get('meta') or {}).get('lastSeen') or '', reverse=True)
    cutoff = time.time() - days * 86400
    recent = [s for s in servers if (iso_to_ts((s.get('meta') or {}).get('lastSeen')) or 0) >= cutoff][:limit] or servers[:1]
    return [{'id': s['id'], 'name': (s.get('attributes') or {}).get('name', s['id']).strip()} for s in recent]


def clip_lines(lines: list[str], limit: int) -> str:
    """Join whole lines up to `limit` characters (never cuts a line, so mentions and links stay intact)."""
    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > limit:
            break
        out.append(line)
        size += len(line) + 1
    return '\n'.join(out)


def main():
    s = Settings.from_env()
    logging.basicConfig(level=s.log_level)
    cat = Catalog.load(s.data_path)
    bot = RustBot(s, cat)
    raid = bot.raid_data

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Last resort: any unhandled error is shown politely and logged."""
        lang = lang_for(interaction)
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = error_embed(t(lang, 'err.cooldown', s=f'{error.retry_after:.0f}'), lang=lang)
        elif isinstance(error, app_commands.CheckFailure):
            msg = error_embed(t(lang, 'err.forbidden'), lang=lang)
        else:
            logging.exception('Unhandled command error', exc_info=error)
            msg = error_embed(t(lang, 'err.generic'), t(lang, 'err.generic.hint'), lang)
        try:
            await reply(interaction, embed=msg)
        except discord.HTTPException:
            pass

    # ── Help ──
    @bot.tree.command(description='📚 Main menu: every RuxtBot tool')
    async def help(interaction: discord.Interaction):
        async def open_players(i):
            await bot.tree.get_command('who').callback(i)
        async def open_sv(i):
            await bot.tree.get_command('sv').callback(i)

        async def open_track(i):
            await bot.tree.get_command('track').callback(i)

        async def open_me(i):
            await bot.tree.get_command('me').callback(i)
        layout = help_layout(raid, lang_for(interaction), interaction.user.id, open_players, {'sv': open_sv, 'track': open_track, 'me': open_me})
        await interaction.response.send_message(view=layout, ephemeral=True)
        layout.message = await interaction.original_response()

    # ── Items and crafting ──
    async def item_choices(interaction, current: str):
        return [app_commands.Choice(name=i['name'][:100], value=i['id']) for i in cat.matches(current)][:25]

    async def craftable_choices(interaction, current: str):
        return [app_commands.Choice(name=i['name'][:100], value=i['id']) for i in cat.matches(current) if i.get('recipe')][:25]

    def item_name(key: str) -> str:
        return cat.raw['items'].get(key, {}).get('name', key)

    @bot.tree.command(description='🔎 Item card: picture, recipe, aliases and raid uses')
    @app_commands.describe(query='Item name or alias')
    @app_commands.autocomplete(query=item_choices)
    async def item(interaction: discord.Interaction, query: str):
        lang = lang_for(interaction)
        found = cat.item(query) or cat.raw['items'].get(query)
        if not found:
            options = cat.matches(query)
            hint = t(lang, 'item.suggest', list=', '.join(f"`{x['id']}`" for x in options[:10])) if options else t(lang, 'item.pick')
            await interaction.response.send_message(embed=error_embed(t(lang, 'item.unknown'), hint, lang), ephemeral=True)
            return
        e = brand_embed(f"🔎 {found['name']}", f"`{found['id']}`")
        if icon := cat.icon(found['id']):
            e.set_thumbnail(url=icon)
        if found.get('aliases'):
            e.add_field(name=t(lang, 'item.aliases'), value=', '.join(found['aliases'])[:1024], inline=False)
        if found.get('recipe'):
            batch = found.get('yield', 1)
            recipe = '\n'.join(f'• {n:,} {item_name(k)}' for k, n in found['recipe'].items())
            e.add_field(name=t(lang, 'item.recipe.batch', n=batch) if batch > 1 else t(lang, 'item.recipe'), value=recipe, inline=True)
            base = cat.materials(found['id'], batch)
            e.add_field(name=t(lang, 'item.base'), value='\n'.join(f'• {n:,} {item_name(k)}' for k, n in base.items()), inline=True)
        used_in = [i['name'] for i in cat.raw['items'].values() if found['id'] in i.get('recipe', {})]
        if used_in:
            e.add_field(name=t(lang, 'item.used_in'), value=', '.join(used_in)[:1024], inline=False)
        if method := CATALOG_TO_RAID.get(found['id']):
            uses = [(raid.targets[k]['name'], raid.amount(k, method)) for k in raid.targets if raid.amount(k, method)]
            if uses:
                e.add_field(name=t(lang, 'item.raids'), value=' · '.join(f'{n} ×{a:,}' for n, a in uses[:14])[:1024], inline=False)
        if found.get('source'):
            e.url = found['source']
        e.set_footer(text=f"{t(lang, 'common.data')}: {cat.version}")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(description='🛠️ Crafting calculator: raw resources and intermediates')
    @app_commands.describe(item='Item to craft', quantity='Amount')
    @app_commands.autocomplete(item=craftable_choices)
    async def craft(interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100000]):
        lang = lang_for(interaction)
        found = cat.item(item) or cat.raw['items'].get(item)
        if not found or not found.get('recipe'):
            await interaction.response.send_message(embed=error_embed(t(lang, 'craft.unknown'), t(lang, 'craft.pick'), lang), ephemeral=True)
            return
        mats = cat.materials(found['id'], quantity)
        inter = cat.intermediates(found['id'], quantity)
        e = brand_embed(f"🛠️ {quantity:,} × {found['name']}")
        if icon := cat.icon(found['id']):
            e.set_thumbnail(url=icon)
        if 'sulfur' in mats:
            e.description = t(lang, 'craft.sulfur', n=mats['sulfur'])
        e.add_field(name=t(lang, 'craft.inter'), value='\n'.join(f'• {n:,} {item_name(k)}' for k, n in inter.items()) or '—', inline=True)
        e.add_field(name=t(lang, 'craft.base'), value='\n'.join(f'• {n:,} {item_name(k)}' for k, n in mats.items()), inline=True)
        e.set_footer(text=t(lang, 'craft.footer', version=cat.version))
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Settings ──
    @bot.tree.command(description='⚙️ Alert channel, role, language and interval (server managers)')
    @app_commands.describe(language='Language for alerts', alerts='Send alerts', interval_seconds='Seconds between checks', channel='Channel for alerts',
                           role='Role to ping in alerts (empty = a role named wipe, if any)')
    @app_commands.choices(language=[app_commands.Choice(name='English', value='en'), app_commands.Choice(name='Spanish', value='es')])
    async def settings(interaction: discord.Interaction, language: str = 'en', alerts: bool = True,
                       interval_seconds: app_commands.Range[int, 10, 3600] = 10, channel: discord.TextChannel | None = None, role: discord.Role | None = None):
        if not await require_admin(interaction):
            return
        lang = lang_for(interaction)
        language = language if language in ('en', 'es') else 'en'
        target_channel = channel or interaction.channel
        bot.store.set_settings(interaction.guild_id, target_channel.id, language, alerts, interval_seconds)
        bot.store.set_alert_role(interaction.guild_id, role.id if role else None)
        e = success_embed(t(lang, 'settings.saved'))
        e.add_field(name=t(lang, 'settings.role'), value=role.mention if role else t(lang, 'settings.role.default'))
        e.add_field(name=t(lang, 'settings.channel'), value=f'<#{target_channel.id}>')
        e.add_field(name=t(lang, 'settings.language'), value={'en': 'English', 'es': 'Español'}[language])
        e.add_field(name=t(lang, 'settings.alerts'), value=t(lang, 'settings.on' if alerts else 'settings.off'))
        e.add_field(name=t(lang, 'settings.interval'), value=f'{interval_seconds} s')
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Servers and presence ──
    server_choices = bot.server_choices
    player_choices = player_autocomplete(bot)

    @bot.tree.command(description='🟢 Is a player online right now?')
    @app_commands.describe(player='Name you looked up before, SteamID64 or BattleMetrics player ID', server='Server (empty = every synchronized server)', share='Publish the result in this channel')
    @app_commands.autocomplete(player=player_choices, server=server_choices)
    async def player(interaction: discord.Interaction, player: str, server: str | None = None, share: bool = False):
        if not server:
            # Without a server the useful answer is "where is this player": the presence overview.
            await bot.tree.get_command('presence').callback(interaction, player=player, share=share)
            return
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        player = expand(bot, interaction, player)
        try:
            sid = bot.directory.resolve(server)
        except ValueError:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=not share)
            return
        try:
            pid = await resolve_player(bot, interaction, player)
        except Exception as exc:
            await player_error(bot, interaction, lang, exc, player, share)
            return
        try:
            online = await bot.bm.player_online(sid, 'bm:' + pid)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'bm.fail'), lang=lang), ephemeral=not share)
            return
        await remember(bot, interaction, bm_id=pid, steamid=steam_of(player))
        key, color = {True: ('player.online', GREEN), False: ('player.offline', RED), None: ('player.unknown', GREY)}[online]
        e = brand_embed(description=f"{t(lang, key)}\n🖥️ {discord.utils.escape_markdown(bot.directory.name(sid))}", color=color)
        try:
            info = await bot.bm.player_server(pid, sid)
            daily = await bot.bm.player_history(pid, sid, 30)
        except Exception:
            info, daily = {}, []
        if info.get('timePlayed') is not None:
            e.add_field(name=t(lang, 'who.bm.played'), value=f"**{info['timePlayed'] / 3600:,.1f} h**")
        if first := iso_to_ts(info.get('firstSeen')):
            e.add_field(name=t(lang, 'who.bm.first'), value=f'<t:{first}:D>')
        if last := iso_to_ts(info.get('lastSeen')):
            e.add_field(name=t(lang, 'player.last'), value=f'<t:{last}:R>')
        if any(v for _, v in daily):
            hours = [v / 3600 for _, v in daily]
            e.add_field(name=t(lang, 'player.daily'), value=f'```\n{spark(hours, 30)}\n```' + t(lang, 'player.daily.value', total=f'{sum(hours):,.1f}', best=f'{max(hours):,.1f}'), inline=False)
        e.set_footer(text=t(lang, 'player.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)

    # ── Watches ──
    @bot.tree.command(description='👀 Manage your temporary connection alerts')
    @app_commands.describe(action='What to do', player='Name you looked up before, SteamID64 or BattleMetrics player ID', server='Server, 🌍 any server, or empty for their usual servers', label='Name shown in alerts', days='Duration in days (maximum 15)', share='Publish the result in this channel')
    @app_commands.choices(action=[app_commands.Choice(name='Add', value='add'), app_commands.Choice(name='Remove', value='remove'),
                                  app_commands.Choice(name='List', value='list')])
    @app_commands.autocomplete(player=player_choices, server=server_autocomplete(bot, include_any=True))
    async def track(interaction: discord.Interaction, action: str = 'list', player: str | None = None, server: str | None = None, label: str | None = None, days: app_commands.Range[int, 1, 15] = 7, share: bool = False):
        lang = lang_for(interaction)
        if not interaction.guild:
            await interaction.response.send_message(embed=error_embed(t(lang, 'track.guild'), lang=lang), ephemeral=not share)
            return
        manager = await can_manage(interaction)
        if action == 'list':
            # Everyone in the server sees every watch: friends share one list and one set of alerts.
            shared = [w for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and getattr(ch, 'guild', None) and ch.guild.id == interaction.guild_id]
            shared.sort(key=lambda w: (w.owner_id != interaction.user.id, w.was_online != 1, (w.label or '').casefold()))
            dot = {1: '🟢', 0: '🔴'}
            rows = [f"{dot.get(w.was_online, '⚪')} **{discord.utils.escape_markdown(w.label or w.steamid)}** · "
                    f"{discord.utils.escape_markdown(bot.directory.name(w.server_id))} · <t:{int(w.expires_at)}:R>"
                    + (f' · <@{w.owner_id}>' if w.owner_id else '') for w in shared]
            e = brand_embed(t(lang, 'track.title', n=len(rows)), clip_lines(rows, 4000) or t(lang, 'track.none'))
            e.add_field(name=t(lang, 'track.panel.title'), value=t(lang, 'track.panel.help'), inline=False)
            recent = [(choice_label(name, steamid, bm_id), steamid or bm_id) for name, steamid, bm_id in bot.store.known_players(scope_of(interaction), limit=25)]
            panel = TrackingPanel(track.callback, lang, interaction.user.id, recent)
            await interaction.response.send_message(embed=e, view=panel, ephemeral=not share, allowed_mentions=discord.AllowedMentions.none())
            panel.message = await interaction.original_response()
            return
        if not player:
            await interaction.response.send_message(embed=error_embed(t(lang, 'track.need_profile'), t(lang, 'track.need_profile.hint'), lang), ephemeral=not share)
            return
        await interaction.response.defer(ephemeral=not share)
        player = expand(bot, interaction, player)
        try:
            pid = await resolve_player(bot, interaction, player)
        except Exception as exc:
            await player_error(bot, interaction, lang, exc, player, share)
            return
        try:
            saved = bot.store.settings(interaction.guild_id)
            channel_id = saved[0] if saved else interaction.channel_id
            data = await bot.bm.profile(pid) if action == 'add' else None
            # Servers: the chosen one; otherwise the profile's servers that are in the directory (add)
            # or the ones already watched (remove).
            if server:
                ids = [bot.directory.resolve(server)]
            elif data:
                known = {r['id'] for r in bot.directory.rows}
                ids = [s['id'] for s in data.get('included', []) if s.get('type') == 'server' and s['id'] in known]
                if not ids:
                    # None of their servers is in the directory: watch where they actually played lately.
                    recent_servers = recent_rust_servers(data)
                    bot.store.save_servers(recent_servers)
                    bot.directory.merge(recent_servers)
                    ids = [r['id'] for r in recent_servers]
            else:
                ids = [w.server_id for w in bot.store.watches() if w.steamid == 'bm:' + pid and w.channel_id == channel_id]
            if not ids:
                await interaction.followup.send(embed=error_embed(t(lang, 'track.no_servers'), lang=lang), ephemeral=not share)
                return
            existing = [w for w in bot.store.watches() if w.steamid == 'bm:' + pid and w.channel_id == channel_id and w.server_id in ids]
            # Anyone can add or renew; stopping someone else's watch needs its creator or a server manager.
            if action == 'remove' and any(w.owner_id not in (0, interaction.user.id) for w in existing) and not manager:
                await interaction.followup.send(embed=error_embed(t(lang, 'track.owner'), lang=lang), ephemeral=not share)
                return
            if action == 'add':
                lines = await presence_lines(bot, pid, data)
                await remember(bot, interaction, bm_id=pid, steamid=steam_of(player), profile=data)
                name = label or data['data']['attributes'].get('name', pid)
                for sid in ids:
                    bot.store.add('bm:' + pid, sid, channel_id, name, owner_id=interaction.user.id, days=days)
                e = success_embed(t(lang, 'track.added', n=len(ids)))
                if lines:
                    e.add_field(name=t(lang, 'activity.title'), value='\n'.join(lines[:6])[:1024], inline=False)
                role = alert_role(bot.store, interaction.guild.get_channel(channel_id) or interaction.channel) if hasattr(interaction.guild, 'get_channel') else None
                e.add_field(name=t(lang, 'track.summary.channel'), value=f'<#{channel_id}> · ' + (f'{role.mention} + ' if role else '') + f'<@{interaction.user.id}>', inline=True)
                e.add_field(name=t(lang, 'track.summary.expires'), value=f'<t:{int(time.time()+days*86400)}:F> · <t:{int(time.time()+days*86400)}:R>', inline=True)
                e.add_field(name=t(lang, 'track.summary.manage'), value=t(lang, 'track.summary.help'), inline=False)
                e.set_footer(text=t(lang, 'track.added.footer'))
            else:
                for sid in ids:
                    bot.store.remove('bm:' + pid, sid, channel_id)
                e = success_embed(t(lang, 'track.removed', n=len(ids)))
            await interaction.followup.send(embed=e, ephemeral=not share, allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:
            # The player is already resolved here, so a ValueError means the server option.
            key = str(exc) if str(exc).startswith('identity.') else 'server.pick'
            await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=not share)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'track.fail'), lang=lang), ephemeral=not share)

    # ── Sources ──
    @bot.tree.command(description='📚 Data sources and catalog version')
    async def sources(interaction: discord.Interaction):
        lang = lang_for(interaction)
        meta = raid.raw['meta']
        e = brand_embed(t(lang, 'sources.title'))
        e.add_field(name=t(lang, 'sources.raid'), value=t(lang, 'sources.raid.value', rustly=meta['rustly']['url'], game=meta['rustly']['gameVersion'],
                                                         rustclash=meta['rustclash']['url'], n=len(raid.targets)), inline=False)
        e.add_field(name=t(lang, 'sources.catalog'), value=f"{cat.raw['meta']['version']} · {cat.raw['meta']['source']}", inline=False)
        e.add_field(name=t(lang, 'sources.icons'), value=meta['icons'], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    register_raid_commands(bot, raid)
    register_utilities(bot, cat, require_admin)
    register_who(bot, bot.who)
    register_info(bot)
    register_activity(bot)
    register_alerts(bot, can_manage)
    register_base(bot)
    register_profiles(bot)
    register_serverinfo(bot, can_manage)
    register_maintenance(bot)
    bot.run(s.discord_token)


if __name__ == '__main__':
    main()
