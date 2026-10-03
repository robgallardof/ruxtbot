"""Channel alerts anyone in the server can set up: /wipealert, /serverwatch and /team.

One background loop (every 2 minutes) checks them all, fetching each server and player once per round:
- wipe alerts: a server's last wipe date changed, or a forced wipe is one hour away / live;
- server watches: a server's population crossed a threshold;
- team watches: members of a group came online or went offline.
Every first reading is silent (it only sets the baseline), so creating an alert never pings anyone.
Alerts mention whoever created them; player and server names are escaped so they cannot mention anyone.
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import tasks
from .i18n import lang_for, t
from .players import player_autocomplete, player_error, resolve_player
from .ui import GREEN, ORANGE, RED, YELLOW, brand_embed, error_embed, success_embed
from .utility_commands import forced_wipes, iso_to_ts

FORCED = 'forced'          # pseudo server ID for forced-wipe reminders
MAX_TEAM = 20
MAX_TEAMS = 25


def esc(value) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))[:80]


class AlertStore:
    """SQLite tables for the alerts, on the bot's existing connection."""

    def __init__(self, conn):
        self.conn = conn
        conn.execute('CREATE TABLE IF NOT EXISTS wipe_alerts(channel_id INTEGER,server_id TEXT,guild_id INTEGER,owner_id INTEGER,last TEXT,PRIMARY KEY(channel_id,server_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS pop_alerts(channel_id INTEGER,server_id TEXT,guild_id INTEGER,owner_id INTEGER,above INTEGER,below INTEGER,'
                     'state TEXT,expires_at REAL,PRIMARY KEY(channel_id,server_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS teams(guild_id INTEGER,name TEXT COLLATE NOCASE,owner_id INTEGER,PRIMARY KEY(guild_id,name))')
        conn.execute('CREATE TABLE IF NOT EXISTS team_members(guild_id INTEGER,team TEXT COLLATE NOCASE,bm_id TEXT,label TEXT,PRIMARY KEY(guild_id,team,bm_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS team_watches(guild_id INTEGER,team TEXT COLLATE NOCASE,channel_id INTEGER,owner_id INTEGER,expires_at REAL,online TEXT,'
                     'PRIMARY KEY(guild_id,team,channel_id))')
        conn.commit()

    def _run(self, sql, args=()):
        self.conn.execute(sql, args)
        self.conn.commit()

    # Wipe alerts
    def add_wipe(self, channel_id, server_id, guild_id, owner_id, last=None):
        self._run('INSERT INTO wipe_alerts VALUES(?,?,?,?,?) ON CONFLICT(channel_id,server_id) DO NOTHING', (channel_id, server_id, guild_id, owner_id, last))

    def wipes(self, guild_id=None):
        sql, args = 'SELECT channel_id,server_id,guild_id,owner_id,last FROM wipe_alerts', ()
        if guild_id is not None:
            sql, args = sql + ' WHERE guild_id=?', (guild_id,)
        return self.conn.execute(sql, args).fetchall()

    def set_wipe_last(self, channel_id, server_id, last):
        self._run('UPDATE wipe_alerts SET last=? WHERE channel_id=? AND server_id=?', (last, channel_id, server_id))

    def remove_wipe(self, channel_id, server_id):
        self._run('DELETE FROM wipe_alerts WHERE channel_id=? AND server_id=?', (channel_id, server_id))

    # Population alerts
    def add_pop(self, channel_id, server_id, guild_id, owner_id, above, below, state, days):
        self._run('INSERT OR REPLACE INTO pop_alerts VALUES(?,?,?,?,?,?,?,?)', (channel_id, server_id, guild_id, owner_id, above, below, state, time.time() + days * 86400))

    def pops(self, guild_id=None):
        self._run('DELETE FROM pop_alerts WHERE expires_at<=?', (time.time(),))
        sql, args = 'SELECT channel_id,server_id,guild_id,owner_id,above,below,state,expires_at FROM pop_alerts', ()
        if guild_id is not None:
            sql, args = sql + ' WHERE guild_id=?', (guild_id,)
        return self.conn.execute(sql, args).fetchall()

    def set_pop_state(self, channel_id, server_id, state):
        self._run('UPDATE pop_alerts SET state=? WHERE channel_id=? AND server_id=?', (state, channel_id, server_id))

    def remove_pop(self, channel_id, server_id):
        self._run('DELETE FROM pop_alerts WHERE channel_id=? AND server_id=?', (channel_id, server_id))

    # Teams
    def create_team(self, guild_id, name, owner_id):
        self._run('INSERT INTO teams VALUES(?,?,?)', (guild_id, name, owner_id))

    def team(self, guild_id, name):
        return self.conn.execute('SELECT name,owner_id FROM teams WHERE guild_id=? AND name=?', (guild_id, name)).fetchone()

    def teams(self, guild_id, query=''):
        return self.conn.execute('SELECT t.name,t.owner_id,COUNT(m.bm_id) FROM teams t LEFT JOIN team_members m ON m.guild_id=t.guild_id AND m.team=t.name '
                                 'WHERE t.guild_id=? AND t.name LIKE ? GROUP BY t.name ORDER BY t.name', (guild_id, f'%{query}%')).fetchall()

    def delete_team(self, guild_id, name):
        for table in ('teams', 'team_members', 'team_watches'):
            self.conn.execute(f'DELETE FROM {table} WHERE guild_id=? AND {"name" if table == "teams" else "team"}=?', (guild_id, name))
        self.conn.commit()

    def add_member(self, guild_id, team, bm_id, label):
        self._run('INSERT OR REPLACE INTO team_members VALUES(?,?,?,?)', (guild_id, team, bm_id, label))

    def remove_member(self, guild_id, team, bm_id):
        self._run('DELETE FROM team_members WHERE guild_id=? AND team=? AND bm_id=?', (guild_id, team, bm_id))

    def members(self, guild_id, team):
        return self.conn.execute('SELECT bm_id,label FROM team_members WHERE guild_id=? AND team=? ORDER BY label COLLATE NOCASE', (guild_id, team)).fetchall()

    def watch_team(self, guild_id, team, channel_id, owner_id, days):
        self._run('INSERT INTO team_watches VALUES(?,?,?,?,?,NULL) ON CONFLICT(guild_id,team,channel_id) DO UPDATE SET expires_at=excluded.expires_at',
                  (guild_id, team, channel_id, owner_id, time.time() + days * 86400))

    def unwatch_team(self, guild_id, team):
        self._run('DELETE FROM team_watches WHERE guild_id=? AND team=?', (guild_id, team))

    def team_watches(self, guild_id=None):
        self._run('DELETE FROM team_watches WHERE expires_at<=?', (time.time(),))
        sql, args = 'SELECT guild_id,team,channel_id,owner_id,expires_at,online FROM team_watches', ()
        if guild_id is not None:
            sql, args = sql + ' WHERE guild_id=?', (guild_id,)
        return self.conn.execute(sql, args).fetchall()

    def set_team_online(self, guild_id, team, channel_id, online: set[str]):
        self._run('UPDATE team_watches SET online=? WHERE guild_id=? AND team=? AND channel_id=?', (json.dumps(sorted(online)), guild_id, team, channel_id))


def pop_state(players: int, above: int | None, below: int | None) -> str:
    if above is not None and players >= above:
        return 'above'
    if below is not None and players <= below:
        return 'below'
    return 'mid'


def forced_window(now: datetime) -> tuple[str, datetime] | None:
    """('soon', wipe) in the hour before a forced wipe, ('live', wipe) in the 3 hours after it, else None."""
    upcoming = forced_wipes(now - timedelta(hours=3), 2)
    for moment in upcoming:
        if moment - timedelta(hours=1) <= now < moment:
            return 'soon', moment
        if moment <= now < moment + timedelta(hours=3):
            return 'live', moment
    return None


async def team_presence(bot, members) -> dict[str, tuple[bool | None, str | None, str | None]]:
    """bm_id -> (online, server id, server name) for every member; failures count as unknown."""
    out = {}
    for bm_id, _ in members:
        try:
            out[bm_id] = await bot.bm.presence_any(bm_id)
        except Exception as exc:
            logging.info('team presence failed for %s: %r', bm_id, exc)
            out[bm_id] = (None, None, None)
    return out


def settings_lang(bot, guild_id) -> str:
    saved = bot.store.settings(guild_id)
    return saved[1] if saved and saved[1] in ('en', 'es') else 'en'


async def send_alert(channel, owner_id, embed, view=None):
    kwargs = {'embed': embed, 'allowed_mentions': discord.AllowedMentions(users=[discord.Object(owner_id)] if owner_id else False, roles=False, everyone=False)}
    if view:
        kwargs['view'] = view
    await channel.send(f'<@{owner_id}>' if owner_id else None, **kwargs)


def server_button(lang, sid):
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=t(lang, 'alert.button'), emoji='📊', url=f'https://www.battlemetrics.com/servers/rust/{sid}'))
    return view


async def check_alerts(bot):
    """One round of every alert. Discord delivery failures leave the stored state as it was, so the alert is retried."""
    alerts: AlertStore = bot.alerts
    wipes, pops, team_rows = alerts.wipes(), alerts.pops(), alerts.team_watches()
    servers: dict[str, dict | None] = {}
    for sid in {r[1] for r in wipes if r[1] != FORCED} | {r[1] for r in pops}:
        try:
            servers[sid] = (await bot.bm.server(sid)).get('attributes') or {}
        except Exception as exc:
            logging.info('alerts: server %s failed: %r', sid, exc)
            servers[sid] = None

    now = datetime.now(timezone.utc)
    window = forced_window(now)
    for channel_id, sid, guild_id, owner_id, last in wipes:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        lang = settings_lang(bot, guild_id)
        try:
            if sid == FORCED:
                if not window:
                    continue
                tag = f'{window[1].isoformat()}|{window[0]}'
                if last == tag:
                    continue
                ts = int(window[1].timestamp())
                e = brand_embed(t(lang, 'wipealert.forced.' + window[0]), t(lang, 'wipealert.forced.body', ts=ts), color=ORANGE if window[0] == 'soon' else RED)
                await send_alert(channel, owner_id, e)
                alerts.set_wipe_last(channel_id, sid, tag)
                continue
            attrs = servers.get(sid)
            if not attrs:
                continue
            details = attrs.get('details') or {}
            wiped = details.get('rust_last_wipe')
            if not wiped or wiped == last:
                continue
            if last and (iso_to_ts(wiped) or 0) > (iso_to_ts(last) or 0):
                e = brand_embed(t(lang, 'wipealert.wiped', server=str(attrs.get('name', sid))[:200]), color=GREEN)
                e.description = t(lang, 'wipealert.wiped.body', ts=iso_to_ts(wiped), p=attrs.get('players', 0), m=attrs.get('maxPlayers', 0))
                if nxt := iso_to_ts(details.get('rust_next_wipe')):
                    e.add_field(name=t(lang, 'server.next_wipe'), value=f'<t:{nxt}:F> · <t:{nxt}:R>')
                if attrs.get('ip') and attrs.get('port'):
                    e.add_field(name=t(lang, 'server.connect'), value=f"`client.connect {attrs['ip']}:{attrs['port']}`", inline=False)
                await send_alert(channel, owner_id, e, server_button(lang, sid))
            alerts.set_wipe_last(channel_id, sid, wiped)
        except Exception:
            logging.exception('wipe alert failed')

    for channel_id, sid, guild_id, owner_id, above, below, state, _ in pops:
        attrs, channel = servers.get(sid), bot.get_channel(channel_id)
        if not attrs or not channel:
            continue
        lang = settings_lang(bot, guild_id)
        try:
            players = attrs.get('players') or 0
            current = pop_state(players, above, below)
            if current == state:
                continue
            if state is not None and current in ('above', 'below'):
                queue = (attrs.get('details') or {}).get('rust_queued_players')
                e = brand_embed(t(lang, 'serverwatch.' + current, server=str(attrs.get('name', sid))[:200], n=above if current == 'above' else below),
                                t(lang, 'serverwatch.body', p=players, m=attrs.get('maxPlayers', 0)) + (f" · {t(lang, 'server.queue', n=queue)}" if queue else ''),
                                color=GREEN if current == 'above' else ORANGE)
                await send_alert(channel, owner_id, e, server_button(lang, sid))
            alerts.set_pop_state(channel_id, sid, current)
        except Exception:
            logging.exception('server watch failed')

    for guild_id, team, channel_id, owner_id, _, online_json in team_rows:
        channel = bot.get_channel(channel_id)
        members = alerts.members(guild_id, team)
        if not channel or not members:
            continue
        lang = settings_lang(bot, guild_id)
        try:
            presence = await team_presence(bot, members)
            previous = set(json.loads(online_json)) if online_json else None
            # Unknown readings keep the member's previous state: missing data never counts as a disconnect.
            online = {bm for bm, (state, _, _) in presence.items() if state is True}
            if previous is not None:
                online |= {bm for bm in previous if presence.get(bm, (None,))[0] is None}
            if previous is not None and online != previous:
                labels = dict(members)
                joined, left = online - previous, previous - online
                lines = [f"🟢 **{esc(labels[b])}** · {esc(presence[b][2] or '?')}" for b in joined]
                lines += [f"🔴 **{esc(labels[b])}**" for b in left if b in labels]
                e = brand_embed(t(lang, 'team.alert.title', team=team, n=len(online), m=len(members)), '\n'.join(lines),
                                color=GREEN if len(online) > len(previous) else ORANGE)
                where = {}
                for b in online:
                    if presence.get(b, (None, None, None))[2]:
                        where.setdefault(presence[b][2], []).append(labels.get(b, b))
                if where:
                    e.add_field(name=t(lang, 'team.where'), value='\n'.join(f'🖥️ **{esc(s)}** · {", ".join(esc(n) for n in names)}' for s, names in where.items())[:1024], inline=False)
                await send_alert(channel, owner_id, e)
            if online != previous:
                alerts.set_team_online(guild_id, team, channel_id, online)
        except Exception:
            logging.exception('team watch failed')


def register_alerts(bot, can_manage):
    bot.alerts = AlertStore(bot.store.conn)
    servers = bot.server_choices
    players = player_autocomplete(bot)

    @tasks.loop(minutes=2)
    async def alerts_loop():
        await check_alerts(bot)

    @alerts_loop.before_loop
    async def wait_ready():
        await bot.wait_until_ready()

    bot.extra_loops.append(alerts_loop)

    def guild_only(interaction, lang):
        if interaction.guild:
            return None
        return error_embed(t(lang, 'track.guild'), lang=lang)

    async def owns_or_manages(interaction, owner_id) -> bool:
        return owner_id in (0, interaction.user.id) or await can_manage(interaction)

    def server_name(sid, lang):
        return t(lang, 'wipealert.forced.name') if sid == FORCED else bot.directory.name(sid)

    # ── /wipealert ──
    @bot.tree.command(name='wipealert', description='🧹 Get a ping in this channel when a server wipes (or before the forced wipe)')
    @app_commands.describe(action='What to do', server='Server name or BattleMetrics server ID', forced='Also remind one hour before the monthly forced wipe')
    @app_commands.choices(action=[app_commands.Choice(name='Add', value='add'), app_commands.Choice(name='Remove', value='remove'), app_commands.Choice(name='List', value='list')])
    @app_commands.autocomplete(server=servers)
    async def wipealert(interaction: discord.Interaction, action: str = 'add', server: str | None = None, forced: bool = False):
        lang = lang_for(interaction)
        if (err := guild_only(interaction, lang)):
            await interaction.response.send_message(embed=err, ephemeral=True)
            return
        if action == 'list':
            rows = bot.alerts.wipes(interaction.guild_id)
            lines = [f"🧹 **{esc(server_name(sid, lang))}** → <#{ch}>" + (f' · <@{owner}>' if owner else '') for ch, sid, _, owner, _ in rows]
            await interaction.response.send_message(embed=brand_embed(t(lang, 'wipealert.list', n=len(rows)), '\n'.join(lines)[:4000] or t(lang, 'wipealert.none')),
                                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        if not server and not forced:
            await interaction.response.send_message(embed=error_embed(t(lang, 'wipealert.need'), t(lang, 'wipealert.need.hint'), lang), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        targets = ([FORCED] if forced else [])
        name = None
        if server:
            try:
                sid = bot.directory.resolve(server)
            except ValueError:
                await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
                return
            targets.append(sid)
        if action == 'remove':
            rows = {(ch, sid): owner for ch, sid, _, owner, _ in bot.alerts.wipes(interaction.guild_id)}
            removed = 0
            for sid in targets:
                owner = rows.get((interaction.channel_id, sid))
                if owner is None:
                    continue
                if not await owns_or_manages(interaction, owner):
                    await interaction.followup.send(embed=error_embed(t(lang, 'alerts.owner'), lang=lang), ephemeral=True)
                    return
                bot.alerts.remove_wipe(interaction.channel_id, sid)
                removed += 1
            await interaction.followup.send(embed=success_embed(t(lang, 'alerts.removed', n=removed)), ephemeral=True)
            return
        lines = []
        for sid in targets:
            if sid == FORCED:
                bot.alerts.add_wipe(interaction.channel_id, FORCED, interaction.guild_id, interaction.user.id)
                ts = int(forced_wipes()[0].timestamp())
                lines.append(t(lang, 'wipealert.added.forced', ts=ts))
                continue
            try:
                attrs = (await bot.bm.server(sid)).get('attributes') or {}
            except Exception:
                await interaction.followup.send(embed=error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang), ephemeral=True)
                return
            name = attrs.get('name', sid)
            bot.directory.merge([{'id': sid, 'name': name}])
            bot.store.save_servers([{'id': sid, 'name': name}])
            last = (attrs.get('details') or {}).get('rust_last_wipe')
            bot.alerts.add_wipe(interaction.channel_id, sid, interaction.guild_id, interaction.user.id, last)
            line = t(lang, 'wipealert.added', server=esc(name))
            if ts := iso_to_ts(last):
                line += '\n-# ' + t(lang, 'wipealert.last', ts=ts)
            if nxt := iso_to_ts((attrs.get('details') or {}).get('rust_next_wipe')):
                line += '\n-# ' + t(lang, 'wipealert.next', ts=nxt)
            lines.append(line)
        e = success_embed('\n'.join(lines))
        e.set_footer(text=t(lang, 'wipealert.footer'))
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /serverwatch ──
    @bot.tree.command(name='serverwatch', description='📈 Get a ping when a server fills up or empties')
    @app_commands.describe(action='What to do', server='Server name or BattleMetrics server ID', above='Ping when players reach this number',
                           below='Ping when players drop to this number', days='Duration in days (maximum 15)')
    @app_commands.choices(action=[app_commands.Choice(name='Add', value='add'), app_commands.Choice(name='Remove', value='remove'), app_commands.Choice(name='List', value='list')])
    @app_commands.autocomplete(server=servers)
    async def serverwatch(interaction: discord.Interaction, action: str = 'add', server: str | None = None, above: app_commands.Range[int, 1, 2000] | None = None,
                          below: app_commands.Range[int, 0, 2000] | None = None, days: app_commands.Range[int, 1, 15] = 3):
        lang = lang_for(interaction)
        if (err := guild_only(interaction, lang)):
            await interaction.response.send_message(embed=err, ephemeral=True)
            return
        if action == 'list':
            rows = bot.alerts.pops(interaction.guild_id)
            lines = [f"📈 **{esc(bot.directory.name(sid))}** · " + ' · '.join(x for x in (f'≥ {a}' if a is not None else '', f'≤ {b}' if b is not None else '') if x)
                     + f' → <#{ch}> · <t:{int(exp)}:R>' for ch, sid, _, _, a, b, _, exp in rows]
            await interaction.response.send_message(embed=brand_embed(t(lang, 'serverwatch.list', n=len(rows)), '\n'.join(lines)[:4000] or t(lang, 'serverwatch.none')), ephemeral=True)
            return
        if not server:
            await interaction.response.send_message(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
            return
        try:
            sid = bot.directory.resolve(server)
        except ValueError:
            await interaction.response.send_message(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
            return
        if action == 'remove':
            owner = next((o for ch, s, _, o, *_ in bot.alerts.pops(interaction.guild_id) if ch == interaction.channel_id and s == sid), None)
            if owner is not None and not await owns_or_manages(interaction, owner):
                await interaction.response.send_message(embed=error_embed(t(lang, 'alerts.owner'), lang=lang), ephemeral=True)
                return
            bot.alerts.remove_pop(interaction.channel_id, sid)
            await interaction.response.send_message(embed=success_embed(t(lang, 'alerts.removed', n=int(owner is not None))), ephemeral=True)
            return
        if above is None and below is None:
            await interaction.response.send_message(embed=error_embed(t(lang, 'serverwatch.need'), t(lang, 'serverwatch.need.hint'), lang), ephemeral=True)
            return
        if above is not None and below is not None and below >= above:
            await interaction.response.send_message(embed=error_embed(t(lang, 'serverwatch.order'), lang=lang), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            attrs = (await bot.bm.server(sid)).get('attributes') or {}
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.fail'), t(lang, 'server.fail.hint'), lang), ephemeral=True)
            return
        name = attrs.get('name', sid)
        bot.directory.merge([{'id': sid, 'name': name}])
        bot.store.save_servers([{'id': sid, 'name': name}])
        players_now = attrs.get('players') or 0
        bot.alerts.add_pop(interaction.channel_id, sid, interaction.guild_id, interaction.user.id, above, below, pop_state(players_now, above, below), days)
        rules = ' · '.join(x for x in (t(lang, 'serverwatch.rule.above', n=above) if above is not None else '', t(lang, 'serverwatch.rule.below', n=below) if below is not None else '') if x)
        e = success_embed(t(lang, 'serverwatch.added', server=esc(name), rules=rules))
        e.add_field(name=t(lang, 'serverwatch.now'), value=t(lang, 'serverwatch.body', p=players_now, m=attrs.get('maxPlayers', 0)), inline=True)
        e.add_field(name=t(lang, 'track.summary.expires'), value=f'<t:{int(time.time() + days * 86400)}:R>', inline=True)
        e.set_footer(text=t(lang, 'alerts.footer'))
        await interaction.followup.send(embed=e, ephemeral=True)

    # ── /team ──
    async def team_choices(interaction, current: str):
        if not interaction.guild_id:
            return []
        return [app_commands.Choice(name=f'{name} · {n} 👤'[:100], value=name) for name, _, n in bot.alerts.teams(interaction.guild_id, current)][:25]

    @bot.tree.command(name='team', description='👥 Group players (a rival clan) and see who is online, or get pinged when they connect')
    @app_commands.describe(action='What to do', name='Team name', player='Player to add or remove: name, SteamID64 or BattleMetrics ID', days='Alert duration in days (maximum 15)',
                           share='Publish the result in this channel')
    @app_commands.choices(action=[app_commands.Choice(name=n, value=v) for n, v in (('Show', 'show'), ('Add player', 'add'), ('Remove player', 'remove'), ('Create', 'create'),
                                                                                    ('List', 'list'), ('Alerts on', 'watch'), ('Alerts off', 'unwatch'), ('Delete', 'delete'))])
    @app_commands.autocomplete(name=team_choices, player=players)
    async def team(interaction: discord.Interaction, action: str = 'show', name: app_commands.Range[str, 1, 40] | None = None, player: str | None = None,
                   days: app_commands.Range[int, 1, 15] = 7, share: bool = False):
        lang = lang_for(interaction)
        if (err := guild_only(interaction, lang)):
            await interaction.response.send_message(embed=err, ephemeral=True)
            return
        gid = interaction.guild_id
        if action == 'list' or (action == 'show' and not name):
            rows = bot.alerts.teams(gid)
            watched = {r[1].casefold() for r in bot.alerts.team_watches(gid)}
            lines = [f"👥 **{esc(n)}** · {count} 👤" + (' · 🔔' if n.casefold() in watched else '') for n, _, count in rows]
            e = brand_embed(t(lang, 'team.list', n=len(rows)), '\n'.join(lines) or t(lang, 'team.none'))
            e.set_footer(text=t(lang, 'team.footer'))
            await interaction.response.send_message(embed=e, ephemeral=not share)
            return
        if not name:
            await interaction.response.send_message(embed=error_embed(t(lang, 'team.need_name'), lang=lang), ephemeral=True)
            return
        name = name.strip()
        existing = bot.alerts.team(gid, name)
        if action == 'create':
            if existing:
                await interaction.response.send_message(embed=error_embed(t(lang, 'team.exists', team=esc(name)), lang=lang), ephemeral=True)
                return
            if len(bot.alerts.teams(gid)) >= MAX_TEAMS:
                await interaction.response.send_message(embed=error_embed(t(lang, 'team.too_many', n=MAX_TEAMS), lang=lang), ephemeral=True)
                return
            bot.alerts.create_team(gid, name, interaction.user.id)
            await interaction.response.send_message(embed=success_embed(t(lang, 'team.created', team=esc(name))), ephemeral=True)
            return
        if not existing:
            await interaction.response.send_message(embed=error_embed(t(lang, 'team.unknown', team=esc(name)), t(lang, 'team.unknown.hint'), lang), ephemeral=True)
            return
        name, owner = existing
        if action in ('delete',) and not await owns_or_manages(interaction, owner):
            await interaction.response.send_message(embed=error_embed(t(lang, 'alerts.owner'), lang=lang), ephemeral=True)
            return
        if action == 'delete':
            bot.alerts.delete_team(gid, name)
            await interaction.response.send_message(embed=success_embed(t(lang, 'team.deleted', team=esc(name))), ephemeral=True)
            return
        if action in ('add', 'remove'):
            if not player:
                await interaction.response.send_message(embed=error_embed(t(lang, 'team.need_player'), lang=lang), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            members = bot.alerts.members(gid, name)
            if action == 'remove':
                match = [bm for bm, label in members if label.casefold() == player.strip().casefold() or bm == player.strip()]
                if not match:
                    try:
                        match = [await resolve_player(bot, interaction, player)]
                    except Exception as exc:
                        await player_error(bot, interaction, lang, exc, player)
                        return
                for bm in match:
                    bot.alerts.remove_member(gid, name, bm)
                await interaction.followup.send(embed=success_embed(t(lang, 'team.removed', team=esc(name))), ephemeral=True)
                return
            if len(members) >= MAX_TEAM:
                await interaction.followup.send(embed=error_embed(t(lang, 'team.full', n=MAX_TEAM), lang=lang), ephemeral=True)
                return
            try:
                pid = await resolve_player(bot, interaction, player)
                profile = await bot.bm.profile(pid)
            except Exception as exc:
                await player_error(bot, interaction, lang, exc, player)
                return
            label = ((profile.get('data') or {}).get('attributes') or {}).get('name') or pid
            bot.alerts.add_member(gid, name, pid, label)
            await interaction.followup.send(embed=success_embed(t(lang, 'team.added', player=esc(label), team=esc(name), n=len(members) + 1)), ephemeral=True)
            return
        if action == 'watch':
            if not bot.alerts.members(gid, name):
                await interaction.response.send_message(embed=error_embed(t(lang, 'team.empty', team=esc(name)), lang=lang), ephemeral=True)
                return
            bot.alerts.watch_team(gid, name, interaction.channel_id, interaction.user.id, days)
            e = success_embed(t(lang, 'team.watching', team=esc(name), ch=f'<#{interaction.channel_id}>'))
            e.add_field(name=t(lang, 'track.summary.expires'), value=f'<t:{int(time.time() + days * 86400)}:R>')
            e.set_footer(text=t(lang, 'alerts.footer'))
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        if action == 'unwatch':
            bot.alerts.unwatch_team(gid, name)
            await interaction.response.send_message(embed=success_embed(t(lang, 'team.unwatched', team=esc(name))), ephemeral=True)
            return
        # show
        members = bot.alerts.members(gid, name)
        if not members:
            await interaction.response.send_message(embed=error_embed(t(lang, 'team.empty', team=esc(name)), lang=lang), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not share)
        presence = await team_presence(bot, members)
        online = [(bm, label) for bm, label in members if presence[bm][0] is True]
        where = {}
        for bm, label in online:
            where.setdefault(presence[bm][2] or '?', []).append(label)
        e = brand_embed(t(lang, 'team.title', team=name, n=len(online), m=len(members)), color=GREEN if online else YELLOW)
        e.description = '\n'.join(f'🖥️ **{esc(s)}**\n' + ', '.join(f'🟢 {esc(n)}' for n in names) for s, names in where.items()) or t(lang, 'team.nobody')
        rest = [f"{'🔴' if presence[bm][0] is False else '⚪'} {esc(label)}" for bm, label in members if presence[bm][0] is not True]
        if rest:
            e.add_field(name=t(lang, 'team.offline'), value=' · '.join(rest)[:1024], inline=False)
        e.set_footer(text=t(lang, 'team.show.footer'))
        await interaction.followup.send(embed=e, ephemeral=not share)
