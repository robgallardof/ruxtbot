"""Punto de entrada de RuxtBot: el bot, el tracker de presencia y los comandos básicos.

Los grupos grandes de comandos viven en sus propios módulos:
    raid.py              → /raid, /raidcalc, /raidbudget, /raidcompare, /raidtools, /raidplan
    who.py               → /who
    utility_commands.py  → /ping, /status, /servers, /syncservers, /wipe, alertas
    help.py              → menú de /help
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
from .help import HelpView, home_embed
from .raid import (CompareMethodsButton, DetonateButton, RaidBackButton, RaidProgressView, RaidStartView,  # noqa: F401  (reexportados)
                   comparison, item_name, raid_embed, raidable, register_raid_commands)
from .servers import ServerDirectory, profile_id
from .tracking import Store, transition
from .ui import GREEN, GREY, RED, brand_embed, error_embed, reply, success_embed
from .utility_commands import iso_to_ts, register_utilities
from .who import WhoService, register_who


class RustBot(commands.Bot):
    """Bot con estado compartido: base de datos, clientes HTTP y directorio de servidores."""

    def __init__(self, settings, catalog):
        super().__init__(command_prefix='!', intents=discord.Intents.default())
        self.settings, self.catalog = settings, catalog
        self.store = Store(settings.state_path)
        self.bm = BattleMetrics(settings.battlemetrics_token)
        self.who = WhoService(self.bm, settings.steam_api_key)
        # Directorio base (servers.json) + servidores importados con /syncservers.
        self.directory = ServerDirectory(Path(settings.data_path).with_name('servers.json'))
        self.directory.merge(self.store.servers())
        self.last_poll = {}  # (steamid, servidor, canal) → última consulta, para respetar el intervalo
        self.poll.change_interval(seconds=10)

    async def setup_hook(self):
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
        """Revisa cada vigilancia y avisa al rol @wipe solo cuando cambia el estado.

        Reglas de seguridad:
        - Datos desconocidos (None) nunca cuentan como desconexión.
        - La primera lectura es silenciosa (solo fija la base).
        - Si Discord falla al enviar, no se guarda el estado para reintentar en la siguiente vuelta.
        """
        for w in self.store.watches():
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
                online = await self.bm.player_online(w.server_id, w.steamid)
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
                    # El nombre viene de datos del jugador: se escapa para que no pueda mencionar a nadie.
                    label = discord.utils.escape_markdown(discord.utils.escape_mentions(w.label or w.steamid))
                    name = discord.utils.escape_markdown(self.directory.name(w.server_id))
                    verb = 'se conectó a' if online else 'se desconectó de'
                    link = discord.ui.View()
                    link.add_item(discord.ui.Button(label='Ver servidor', emoji='📊', url=f'https://www.battlemetrics.com/servers/rust/{w.server_id}'))
                    await ch.send(f"{role.mention} {'🟢' if online else '🔴'} **{label}** {verb} **{name}** · <t:{int(time.time())}:R>",
                                  view=link, allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False))
                self.store.set_state(w, online)
            except Exception:
                logging.exception('tracker poll failed')

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


def embed(title, description):
    """Atajo histórico: embed amarillo de la marca."""
    return brand_embed(title, description)


async def require_admin(interaction) -> bool:
    """Corta la interacción con un aviso si quien la usa no es administrador del Discord."""
    if not interaction.guild or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(embed=error_embed('Solo administradores pueden usar este comando.', 'Pídeselo a un admin del Discord.'), ephemeral=True)
        return False
    return True


def main():
    s = Settings.from_env()
    logging.basicConfig(level=s.log_level)
    cat = Catalog.load(s.data_path)
    bot = RustBot(s, cat)

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Último recurso: cualquier error no controlado se muestra de forma amable y se registra."""
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = error_embed(f'Espera {error.retry_after:.0f} s antes de repetirlo.')
        elif isinstance(error, app_commands.CheckFailure):
            msg = error_embed('No tienes permiso para usar este comando aquí.')
        else:
            logging.exception('Unhandled command error', exc_info=error)
            msg = error_embed('Algo salió mal al ejecutar el comando.', 'Inténtalo de nuevo en un momento. Si se repite, avisa a un admin.')
        try:
            await reply(interaction, embed=msg)
        except discord.HTTPException:
            pass

    # ── Ayuda ──
    @bot.tree.command(description='📚 Menú principal: todas las herramientas de RuxtBot')
    async def help(interaction: discord.Interaction):
        await interaction.response.send_message(embed=home_embed(cat), view=HelpView(cat, interaction.user.id), ephemeral=True)

    # ── Ítems y crafteo ──
    async def item_choices(interaction, current: str):
        return [app_commands.Choice(name=i['name'][:100], value=i['id']) for i in cat.matches(current)][:25]

    async def craftable_choices(interaction, current: str):
        return [app_commands.Choice(name=i['name'][:100], value=i['id']) for i in cat.matches(current) if i.get('recipe')][:25]

    @bot.tree.command(description='🔎 Ficha de un ítem: receta, alias y usos en raid')
    @app_commands.describe(query='Nombre o alias del ítem (también en español)')
    @app_commands.autocomplete(query=item_choices)
    async def item(interaction: discord.Interaction, query: str):
        found = cat.item(query) or cat.raw['items'].get(query)
        if not found:
            options = cat.matches(query)
            hint = ('¿Quisiste decir: ' + ', '.join(f"`{x['id']}`" for x in options[:10]) + '?') if options else 'Escribe y elige una sugerencia.'
            await interaction.response.send_message(embed=error_embed('Ítem ambiguo o desconocido.', hint), ephemeral=True)
            return
        e = brand_embed(f"🔎 {found['name']}", f"`{found['id']}`")
        if found.get('aliases'):
            e.add_field(name='🏷️ Alias', value=', '.join(found['aliases'])[:1024], inline=False)
        if found.get('recipe'):
            batch = found.get('yield', 1)
            recipe = '\n'.join(f'• {n:,} {item_name(cat, k)}' for k, n in found['recipe'].items())
            e.add_field(name='🛠️ Receta' + (f' (fabrica {batch})' if batch > 1 else ''), value=recipe, inline=True)
            base = cat.materials(found['id'], batch)
            e.add_field(name='⛏️ Recursos base', value='\n'.join(f'• {n:,} {item_name(cat, k)}' for k, n in base.items()), inline=True)
        used_in = [i['name'] for i in cat.raw['items'].values() if found['id'] in i.get('recipe', {})]
        if used_in:
            e.add_field(name='🔗 Se usa para fabricar', value=', '.join(used_in)[:1024], inline=False)
        raids = [f"{t['name']} ({t['methods'][found['id']]['count']:,})" for t in raidable(cat).values() if found['id'] in t['methods']]
        if raids:
            e.add_field(name='💥 Sirve para raidear (unidades)', value=' · '.join(raids)[:1024], inline=False)
        if found.get('source'):
            e.url = found['source']
        e.set_footer(text=f'Datos: {cat.version}')
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(description='🛠️ Calculadora de fabricación: recursos base e intermedios')
    @app_commands.describe(item='Ítem a fabricar', quantity='Cantidad')
    @app_commands.autocomplete(item=craftable_choices)
    async def craft(interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100000]):
        found = cat.item(item) or cat.raw['items'].get(item)
        if not found or not found.get('recipe'):
            await interaction.response.send_message(embed=error_embed('Ítem desconocido o no fabricable.', 'Elige uno de las sugerencias.'), ephemeral=True)
            return
        mats = cat.materials(found['id'], quantity)
        inter = cat.intermediates(found['id'], quantity)
        e = brand_embed(f"🛠️ {quantity:,} × {found['name']}")
        if 'sulfur' in mats:
            e.description = f"🧪 **{mats['sulfur']:,}** azufre en total"
        e.add_field(name='⚙️ Intermedios', value='\n'.join(f'• {n:,} {item_name(cat, k)}' for k, n in inter.items()) or '—', inline=True)
        e.add_field(name='⛏️ Recursos y componentes', value='\n'.join(f'• {n:,} {item_name(cat, k)}' for k, n in mats.items()), inline=True)
        e.set_footer(text=f'Datos: {cat.version} · Lotes completos de fabricación')
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Ajustes ──
    @bot.tree.command(description='⚙️ Canal de alertas, idioma, alertas e intervalo (solo admins)')
    @app_commands.describe(language='Idioma', alerts='Enviar avisos', interval_seconds='Cada cuántos segundos revisar', channel='Canal para los avisos')
    @app_commands.choices(language=[app_commands.Choice(name='Español', value='es'), app_commands.Choice(name='English', value='en')])
    async def settings(interaction: discord.Interaction, language: str = 'es', alerts: bool = True,
                       interval_seconds: app_commands.Range[int, 10, 3600] = 10, channel: discord.TextChannel | None = None):
        if not await require_admin(interaction):
            return
        if language not in ('es', 'en'):
            await interaction.response.send_message(embed=error_embed('El idioma debe ser `es` o `en`.'), ephemeral=True)
            return
        target_channel = channel or interaction.channel
        bot.store.set_settings(interaction.guild_id, target_channel.id, language, alerts, interval_seconds)
        e = success_embed('Ajustes guardados.')
        e.add_field(name='📢 Canal', value=f'<#{target_channel.id}>')
        e.add_field(name='🌐 Idioma', value=language)
        e.add_field(name='🔔 Alertas', value='Activas' if alerts else 'Pausadas')
        e.add_field(name='⏱️ Intervalo', value=f'{interval_seconds} s')
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Servidores y presencia ──
    async def server_choices(interaction, current: str):
        return [app_commands.Choice(name=row['name'][:100], value=row['id']) for row in bot.directory.search(current)]

    @bot.tree.command(description='🖥️ Estado del servidor: jugadores, cola, mapa y wipe')
    @app_commands.describe(server='Escribe parte del nombre y elige una sugerencia')
    @app_commands.autocomplete(server=server_choices)
    async def server(interaction: discord.Interaction, server: str):
        await interaction.response.defer(ephemeral=True)
        try:
            sid = bot.directory.resolve(server)
            a = (await bot.bm.server(sid))['attributes']
            d = a.get('details') or {}
            online = a.get('status') == 'online'
            players, cap = a.get('players') or 0, a.get('maxPlayers') or 0
            pct = round(100 * players / cap) if cap else 0
            e = brand_embed(f"🖥️ {a.get('name', 'Servidor')}", color=GREEN if online else RED)
            e.url = f'https://www.battlemetrics.com/servers/rust/{sid}'
            e.description = f"{'🟢 En línea' if online else '🔴 ' + str(a.get('status', 'desconocido')).capitalize()} · 👥 **{players}/{cap}** ({pct}%)"
            if d.get('rust_queued_players'):
                e.description += f" · ⏳ cola **{d['rust_queued_players']}**"
            if d.get('map'):
                size = d.get('rust_world_size')
                e.add_field(name='🗺️ Mapa', value=str(d['map']) + (f' · {size:,} m' if isinstance(size, int) else ''))
            if a.get('rank'):
                e.add_field(name='🏆 Ranking', value=f"#{a['rank']:,}")
            if a.get('country'):
                e.add_field(name='🌎 País', value=a['country'])
            if stamp := iso_to_ts(d.get('rust_last_wipe')):
                e.add_field(name='🧹 Último wipe', value=f'<t:{stamp}:R>')
            if stamp := iso_to_ts(d.get('rust_next_wipe')):
                e.add_field(name='⏭️ Próximo wipe', value=f'<t:{stamp}:R>')
            if a.get('ip') and a.get('port'):
                e.add_field(name='🔌 Conectar (F1)', value=f"`client.connect {a['ip']}:{a['port']}`", inline=False)
            e.set_footer(text='BattleMetrics')
            await interaction.followup.send(embed=e, ephemeral=True)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed('No se pudo consultar el servidor.', 'Selecciona su nombre en las sugerencias y revisa BattleMetrics.'), ephemeral=True)

    @bot.tree.command(description='🟢 ¿Está conectado? Perfil BattleMetrics + servidor')
    @app_commands.describe(profile='Enlace del perfil de BattleMetrics', server='Servidor (elige de la lista)')
    @app_commands.autocomplete(server=server_choices)
    async def player(interaction: discord.Interaction, profile: str, server: str):
        await interaction.response.defer(ephemeral=True)
        try:
            sid = bot.directory.resolve(server)
            online = await bot.bm.player_online(sid, 'bm:' + profile_id(profile))
            text, color = {True: ('🟢 **Conectado**', GREEN), False: ('🔴 **Desconectado**', RED),
                           None: ('⚪ **Estado desconocido**: BattleMetrics no tiene una observación reciente.', GREY)}[online]
            e = brand_embed(description=f'{text}\n🖥️ {discord.utils.escape_markdown(bot.directory.name(sid))}', color=color)
            e.set_footer(text='Usa /track para recibir avisos automáticos.')
            await interaction.followup.send(embed=e, ephemeral=True)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed('No se pudo consultar BattleMetrics.'), ephemeral=True)

    # ── Vigilancias ──
    @bot.tree.command(description='👀 Gestiona vigilancias de conexión (solo admins)')
    @app_commands.describe(action='Qué hacer', profile='Enlace del perfil BattleMetrics', server='Servidor (vacío = todos los conocidos)', label='Nombre a mostrar en los avisos')
    @app_commands.choices(action=[app_commands.Choice(name='➕ Añadir', value='add'), app_commands.Choice(name='➖ Quitar', value='remove'),
                                  app_commands.Choice(name='📋 Listar', value='list')])
    @app_commands.autocomplete(server=server_choices)
    async def track(interaction: discord.Interaction, action: str, profile: str | None = None, server: str | None = None, label: str | None = None):
        if not await require_admin(interaction):
            return
        if action == 'list':
            mine = [w for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and ch.guild.id == interaction.guild_id]
            dot = {1: '🟢', 0: '🔴'}
            rows = [f"{dot.get(w.was_online, '⚪')} **{discord.utils.escape_markdown(w.label or w.steamid)}** · "
                    f"{discord.utils.escape_markdown(bot.directory.name(w.server_id))} → <#{w.channel_id}>" for w in mine]
            e = brand_embed(f'👀 Vigilancias · {len(rows)}', '\n'.join(rows)[:4000] or 'No hay vigilancias. Añade una con `/track action:➕ Añadir`.')
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        if not profile:
            await interaction.response.send_message(embed=error_embed('Falta el perfil.', 'Pega el enlace del perfil de BattleMetrics. Elige el servidor por nombre o déjalo vacío para sus servidores conocidos.'), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pid = profile_id(profile)
            saved = bot.store.settings(interaction.guild_id)
            channel_id = saved[0] if saved else interaction.channel_id
            data = await bot.bm.profile(pid) if action == 'add' else None
            # Servidores: el elegido; si no, los del perfil presentes en el directorio (add) o los ya vigilados (remove).
            if server:
                ids = [bot.directory.resolve(server)]
            elif data:
                known = {r['id'] for r in bot.directory.rows}
                ids = [s['id'] for s in data.get('included', []) if s.get('type') == 'server' and s['id'] in known]
            else:
                ids = [w.server_id for w in bot.store.watches() if w.steamid == 'bm:' + pid and w.channel_id == channel_id]
            if not ids:
                raise ValueError('No hay servidores compartidos con el directorio importado.')
            if action == 'add':
                roles = [r for r in interaction.guild.roles if r.name.casefold() == 'wipe']
                if len(roles) != 1:
                    raise ValueError('Debe existir exactamente un rol llamado wipe para las alertas.')
                name = label or data['data']['attributes'].get('name', pid)
                for sid in ids:
                    bot.store.add('bm:' + pid, sid, channel_id, name)
                e = success_embed(f'Vigilancia activada en **{len(ids)}** servidor(es). Avisaré a @wipe cuando se conecte o desconecte.')
                e.set_footer(text='La primera lectura es silenciosa; datos no disponibles no generan falsas desconexiones.')
            else:
                for sid in ids:
                    bot.store.remove('bm:' + pid, sid, channel_id)
                e = success_embed(f'Vigilancias eliminadas: **{len(ids)}**.')
            await interaction.followup.send(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed('No se pudo consultar BattleMetrics. No se han confirmado cambios.'), ephemeral=True)

    # ── Fuentes ──
    @bot.tree.command(description='📚 Versión del catálogo, fuentes y confianza de los datos')
    async def sources(interaction: discord.Interaction):
        meta = cat.raw['meta']
        e = brand_embed('📚 Fuentes de datos')
        e.add_field(name='🏷️ Versión', value=meta['version'])
        e.add_field(name='📅 Actualizado', value=str(meta['updated']))
        e.add_field(name='🎯 Objetivos con datos', value=f"{len(raidable(cat))}/{len(cat.raw['targets'])}")
        e.add_field(name='🔗 Fuente', value=meta['source'], inline=False)
        e.add_field(name='⚖️ Confianza', value=meta['confidence'], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    register_raid_commands(bot, cat)
    register_utilities(bot, cat, require_admin)
    register_who(bot, bot.who)
    bot.run(s.discord_token)


if __name__ == '__main__':
    main()
