"""RuxtBot entry point: the bot, the presence tracker and the core commands.

Larger command groups live in their own modules:
    raid.py              /raid, /raidcalc, /raidbudget, /raidcompare, /raidtools
    who.py               /who
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
from .raid import register_raid_commands
from .raid_data import RaidData
from .servers import ServerDirectory
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
        self.who = WhoService(self.bm, settings.steam_api_key)
        # Base directory (servers.json) + servers imported with /syncservers.
        self.directory = ServerDirectory(Path(settings.data_path).with_name('servers.json'))
        self.directory.merge(self.store.servers())
        self.last_poll = {}  # (steamid, server, channel) -> last check, to honour the interval
        self.poll.change_interval(seconds=10)

    async def setup_hook(self):
        await self.tree.set_translator(CommandTranslator())
        await self.tree.sync()
        self.poll.start()

    async def on_ready(self):
        logging.info('RuxtBot connected as %s', self.user)
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='raids · /help'))

    async def close(self):
        self.poll.cancel()
        await self.bm.client.aclose()
        await self.who.client.aclose()
        self.store.conn.close()
        await super().close()

    @tasks.loop(seconds=10)
    async def poll(self):
        """Check every watch and ping the @wipe role only when the state changes.

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
                    observations[observation_key] = await self.bm.player_online(w.server_id, w.steamid)
                online = observations[observation_key]
                if online is None:
                    continue
                event = transition(w.was_online, online)
                if event and (not saved or saved[2]):
                    roles = [role for role in ch.guild.roles if role.name.casefold() == 'wipe']
                    if len(roles) != 1:
                        logging.warning('Tracking alert waiting: guild %s needs exactly one wipe role', ch.guild.id)
                        continue
                    role = roles[0]
                    if not role.mentionable and not ch.permissions_for(ch.guild.me).mention_everyone:
                        logging.warning('Tracking alert waiting: wipe role is not mentionable in guild %s', ch.guild.id)
                        continue
                    lang = saved[1] if saved and saved[1] in ('en', 'es') else 'en'
                    # The label comes from player data: escape it so it can never mention anyone.
                    label = discord.utils.escape_markdown(discord.utils.escape_mentions(w.label or w.steamid))
                    name = discord.utils.escape_markdown(self.directory.name(w.server_id))
                    verb = t(lang, 'alert.connected' if online else 'alert.disconnected')
                    link = discord.ui.View()
                    link.add_item(discord.ui.Button(label=t(lang, 'alert.button'), emoji='📊', url=f'https://www.battlemetrics.com/servers/rust/{w.server_id}'))
                    await ch.send(f"{role.mention} {'🟢' if online else '🔴'} **{label}** {verb} **{name}** · <t:{int(time.time())}:R>",
                                  view=link, allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False))
                self.store.set_state(w, online)
            except Exception:
                logging.exception('tracker poll failed')

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


async def require_admin(interaction) -> bool:
    """Stop the interaction with a notice unless the user is a server administrator."""
    if not interaction.guild or not interaction.user.guild_permissions.administrator:
        lang = lang_for(interaction)
        await interaction.response.send_message(embed=error_embed(t(lang, 'err.admin'), t(lang, 'err.admin.hint'), lang), ephemeral=True)
        return False
    return True


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
        layout = help_layout(raid, lang_for(interaction), interaction.user.id)
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
    @bot.tree.command(description='⚙️ Alert channel, language, alerts and interval (admins)')
    @app_commands.describe(language='Language for alerts', alerts='Send alerts', interval_seconds='Seconds between checks', channel='Channel for alerts')
    @app_commands.choices(language=[app_commands.Choice(name='English', value='en'), app_commands.Choice(name='Spanish', value='es')])
    async def settings(interaction: discord.Interaction, language: str = 'en', alerts: bool = True,
                       interval_seconds: app_commands.Range[int, 10, 3600] = 10, channel: discord.TextChannel | None = None):
        if not await require_admin(interaction):
            return
        lang = lang_for(interaction)
        language = language if language in ('en', 'es') else 'en'
        target_channel = channel or interaction.channel
        bot.store.set_settings(interaction.guild_id, target_channel.id, language, alerts, interval_seconds)
        e = success_embed(t(lang, 'settings.saved'))
        e.add_field(name=t(lang, 'settings.channel'), value=f'<#{target_channel.id}>')
        e.add_field(name=t(lang, 'settings.language'), value={'en': 'English', 'es': 'Español'}[language])
        e.add_field(name=t(lang, 'settings.alerts'), value=t(lang, 'settings.on' if alerts else 'settings.off'))
        e.add_field(name=t(lang, 'settings.interval'), value=f'{interval_seconds} s')
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Servers and presence ──
    async def server_choices(interaction, current: str):
        return [app_commands.Choice(name=row['name'][:100], value=row['id']) for row in bot.directory.search(current)]

    @bot.tree.command(description='🖥️ Live server status: players, queue, map and wipe')
    @app_commands.describe(server='Type part of the name and pick a suggestion')
    @app_commands.autocomplete(server=server_choices)
    async def server(interaction: discord.Interaction, server: str):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            sid = bot.directory.resolve(server)
        except ValueError:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
            return
        try:
            a = (await bot.bm.server(sid))['attributes']
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang), ephemeral=True)
            return
        d = a.get('details') or {}
        online = a.get('status') == 'online'
        players, cap = a.get('players') or 0, a.get('maxPlayers') or 0
        pct = round(100 * players / cap) if cap else 0
        e = brand_embed(f"🖥️ {a.get('name', 'Server')}", color=GREEN if online else RED)
        e.url = f'https://www.battlemetrics.com/servers/rust/{sid}'
        parts = [t(lang, 'server.online') if online else '🔴 ' + str(a.get('status', '?')).capitalize(), t(lang, 'server.players', p=players, m=cap, pct=pct)]
        if d.get('rust_queued_players'):
            parts.append(t(lang, 'server.queue', n=d['rust_queued_players']))
        e.description = ' · '.join(parts) + f"\n`{'█' * round(pct / 10)}{'░' * (10 - round(pct / 10))}`"
        if d.get('map'):
            size = d.get('rust_world_size')
            e.add_field(name=t(lang, 'server.map'), value=str(d['map']) + (f' · {size:,} m' if isinstance(size, int) else ''))
        if a.get('rank'):
            e.add_field(name=t(lang, 'server.rank'), value=f"#{a['rank']:,}")
        if a.get('country'):
            e.add_field(name=t(lang, 'server.country'), value=a['country'])
        if stamp := iso_to_ts(d.get('rust_last_wipe')):
            e.add_field(name=t(lang, 'server.last_wipe'), value=f'<t:{stamp}:R>')
        if stamp := iso_to_ts(d.get('rust_next_wipe')):
            e.add_field(name=t(lang, 'server.next_wipe'), value=f'<t:{stamp}:R>')
        if a.get('ip') and a.get('port'):
            e.add_field(name=t(lang, 'server.connect'), value=f"`client.connect {a['ip']}:{a['port']}`", inline=False)
        if d.get('rust_headerimage'):
            e.set_image(url=d['rust_headerimage'])
        e.set_footer(text='BattleMetrics')
        await interaction.followup.send(embed=e, ephemeral=True)

    @bot.tree.command(description='🟢 Is a BattleMetrics profile online on a server?')
    @app_commands.describe(profile='SteamID64 or BattleMetrics player ID', server='Server (pick from the list)', share='Publish the result in this channel')
    @app_commands.autocomplete(server=server_choices)
    async def player(interaction: discord.Interaction, profile: str, server: str, share: bool = False):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=not share)
        try:
            sid = bot.directory.resolve(server)
            pid = await bot.bm.resolve_player(profile)
        except ValueError as exc:
            key = str(exc) if str(exc).startswith('identity.') else 'identity.input'
            await interaction.followup.send(embed=error_embed(t(lang, key), lang=lang), ephemeral=not share)
            return
        try:
            online = await bot.bm.player_online(sid, 'bm:' + pid)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'bm.fail'), lang=lang), ephemeral=not share)
            return
        key, color = {True: ('player.online', GREEN), False: ('player.offline', RED), None: ('player.unknown', GREY)}[online]
        e = brand_embed(description=f"{t(lang, key)}\n🖥️ {discord.utils.escape_markdown(bot.directory.name(sid))}", color=color)
        e.set_footer(text=t(lang, 'player.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)

    # ── Watches ──
    @bot.tree.command(description='👀 Manage your temporary connection alerts')
    @app_commands.describe(action='What to do', profile='SteamID64 or BattleMetrics player ID', server='Server (empty = all known)', label='Name shown in alerts', days='Duration in days (maximum 15)', share='Publish the result in this channel')
    @app_commands.choices(action=[app_commands.Choice(name='Add', value='add'), app_commands.Choice(name='Remove', value='remove'),
                                  app_commands.Choice(name='List', value='list')])
    @app_commands.autocomplete(server=server_choices)
    async def track(interaction: discord.Interaction, action: str = 'list', profile: str | None = None, server: str | None = None, label: str | None = None, days: app_commands.Range[int, 1, 15] = 7, share: bool = False):
        lang = lang_for(interaction)
        if not interaction.guild:
            await interaction.response.send_message(embed=error_embed(t(lang, 'track.guild'), lang=lang), ephemeral=not share)
            return
        admin = interaction.user.guild_permissions.administrator
        if action == 'list':
            mine = [w for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and ch.guild.id == interaction.guild_id and (admin or w.owner_id == interaction.user.id)]
            dot = {1: '🟢', 0: '🔴'}
            rows = [f"{dot.get(w.was_online, '⚪')} **{discord.utils.escape_markdown(w.label or w.steamid)}** · "
                    f"{discord.utils.escape_markdown(bot.directory.name(w.server_id))} → <#{w.channel_id}> · <t:{int(w.expires_at)}:R>" for w in mine]
            e = brand_embed(t(lang, 'track.title', n=len(rows)), '\n'.join(rows)[:4000] or t(lang, 'track.none'))
            e.add_field(name=t(lang, 'track.panel.title'), value=t(lang, 'track.panel.help'), inline=False)
            panel = TrackingPanel(track.callback, lang, interaction.user.id)
            await interaction.response.send_message(embed=e, view=panel, ephemeral=not share)
            panel.message = await interaction.original_response()
            return
        if not profile:
            await interaction.response.send_message(embed=error_embed(t(lang, 'track.need_profile'), t(lang, 'track.need_profile.hint'), lang), ephemeral=not share)
            return
        await interaction.response.defer(ephemeral=not share)
        try:
            pid = await bot.bm.resolve_player(profile)
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
            else:
                ids = [w.server_id for w in bot.store.watches() if w.steamid == 'bm:' + pid and w.channel_id == channel_id]
            if not ids:
                await interaction.followup.send(embed=error_embed(t(lang, 'track.no_servers'), lang=lang), ephemeral=not share)
                return
            existing = [w for w in bot.store.watches() if w.steamid == 'bm:' + pid and w.channel_id == channel_id and w.server_id in ids]
            if any(w.owner_id != interaction.user.id for w in existing) and not admin:
                await interaction.followup.send(embed=error_embed(t(lang, 'track.owner'), lang=lang), ephemeral=not share)
                return
            if action == 'add':
                if len([r for r in interaction.guild.roles if r.name.casefold() == 'wipe']) != 1:
                    await interaction.followup.send(embed=error_embed(t(lang, 'track.need_role'), lang=lang), ephemeral=not share)
                    return
                lines = await presence_lines(bot, pid, data)
                name = label or data['data']['attributes'].get('name', pid)
                for sid in ids:
                    bot.store.add('bm:' + pid, sid, channel_id, name, owner_id=interaction.user.id, days=days)
                e = success_embed(t(lang, 'track.added', n=len(ids)))
                if lines:
                    e.add_field(name=t(lang, 'activity.title'), value='\n'.join(lines[:6])[:1024], inline=False)
                e.add_field(name=t(lang, 'track.summary.channel'), value=f'<#{channel_id}> · @wipe', inline=True)
                e.add_field(name=t(lang, 'track.summary.expires'), value=f'<t:{int(time.time()+days*86400)}:F> · <t:{int(time.time()+days*86400)}:R>', inline=True)
                e.add_field(name=t(lang, 'track.summary.manage'), value=t(lang, 'track.summary.help'), inline=False)
                e.set_footer(text=t(lang, 'track.added.footer'))
            else:
                for sid in ids:
                    bot.store.remove('bm:' + pid, sid, channel_id)
                e = success_embed(t(lang, 'track.removed', n=len(ids)))
            await interaction.followup.send(embed=e, ephemeral=not share, allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:
            key = str(exc) if str(exc).startswith('identity.') else 'identity.input'
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
    bot.run(s.discord_token)


if __name__ == '__main__':
    main()
