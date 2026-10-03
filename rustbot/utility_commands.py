"""Comandos de servidores y administración (/ping, /status, /servers, /syncservers, /wipe, alertas)."""
from datetime import datetime
import math
import discord
from discord import app_commands
from .raid import comparison  # noqa: F401  (se reexporta por compatibilidad)
from .servers import profile_id
from .ui import GREEN, ORANGE, OwnedView, brand_embed, error_embed, success_embed

PAGE_SIZE = 10


def iso_to_ts(value) -> int | None:
    """Fecha ISO de BattleMetrics → timestamp Unix (o None si no hay)."""
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except (AttributeError, ValueError, TypeError):
        return None


def servers_page_embed(rows: list[dict], query: str, page: int) -> tuple[discord.Embed, int]:
    """Página `page` (1-based) del directorio filtrado."""
    pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = max(1, min(page, pages))
    lines = [f"• [{discord.utils.escape_markdown(r['name'])}](https://www.battlemetrics.com/servers/rust/{r['id']})"
             for r in rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]]
    title = f'🖥️ Servidores · {page}/{pages}' + (f' · «{query}»' if query else '')
    e = brand_embed(title, '\n'.join(lines) or '🔍 Sin coincidencias.')
    e.set_footer(text=f'{len(rows)} servidores · Usa /server o /track y elige por nombre; no necesitas IDs.')
    return e, pages


class ServerPagesView(OwnedView):
    """Botones ◀️ ▶️ para recorrer el directorio sin volver a escribir el comando."""

    def __init__(self, rows, query, page, owner_id=None):
        super().__init__(owner_id)
        self.rows, self.query, self.page = rows, query, page
        _, pages = servers_page_embed(rows, query, page)
        self.prev.disabled = page <= 1
        self.next.disabled = page >= pages
        self.counter.label = f'{page}/{pages}'

    async def _go(self, interaction, page):
        e, _ = servers_page_embed(self.rows, self.query, page)
        view = ServerPagesView(self.rows, self.query, page, self.owner_id)
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
        # Solo las vigilancias cuyos canales pertenecen a este Discord.
        return [w for w in bot.store.watches() if (ch := bot.get_channel(w.channel_id)) and ch.guild and ch.guild.id == interaction.guild_id]

    @bot.tree.command(name='ping', description='🏓 Comprueba la conexión del bot con Discord')
    async def ping(interaction):
        latency = bot.latency
        if not math.isfinite(latency):
            await interaction.response.send_message('⏳ Conectando con Discord…', ephemeral=True)
            return
        ms = round(latency * 1000)
        dot = '🟢' if ms < 150 else '🟡' if ms < 400 else '🔴'
        await interaction.response.send_message(f'🏓 Pong · {dot} **{ms} ms**', ephemeral=True)

    @bot.tree.command(name='status', description='📡 Estado del bot, vigilancias y configuración de este Discord')
    async def status(interaction):
        if not await require_admin(interaction):
            return
        saved = bot.store.settings(interaction.guild_id)
        watches = guild_watches(interaction)
        online = sum(w.was_online == 1 for w in watches)
        unknown = sum(w.was_online is None or not w.steamid.startswith('bm:') for w in watches)
        running = bot.poll.is_running()
        alerts = not saved or saved[2]
        e = brand_embed('📡 Estado de RuxtBot', color=GREEN if running and alerts else ORANGE)
        e.add_field(name='🔁 Tracker', value='🟢 Ejecutándose' if running else '🔴 Detenido')
        e.add_field(name='🔔 Alertas', value='🟢 Activas' if alerts else '⏸️ Pausadas')
        e.add_field(name='⏱️ Intervalo', value=f'{saved[3] if saved else bot.settings.poll_interval} s')
        e.add_field(name='👀 Vigilancias', value=f'**{len(watches)}** total · 🟢 {online} online · ⚪ {unknown} sin datos', inline=False)
        e.add_field(name='📢 Canal', value=f'<#{saved[0]}>' if saved else 'El canal donde se use /track')
        e.add_field(name='🖥️ Directorio', value=f'{len(bot.directory.rows)} servidores')
        e.set_footer(text='Último estado conocido; /player consulta una observación reciente.')
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name='servers', description='🖥️ Busca y lista tus servidores por nombre con paginación')
    @app_commands.describe(query='Filtra por parte del nombre', page='Página inicial')
    async def list_servers(interaction, query: str = '', page: app_commands.Range[int, 1, 1000] = 1):
        rows = [r for r in bot.directory.rows if query.casefold() in r['name'].casefold()]
        e, pages = servers_page_embed(rows, query, page)
        if page > pages:
            await interaction.response.send_message(embed=error_embed(f'Solo hay {pages} página(s).'), ephemeral=True)
            return
        view = ServerPagesView(rows, query, page, interaction.user.id)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    @bot.tree.command(name='syncservers', description='📥 Importa servidores de un perfil BattleMetrics al selector')
    async def sync_servers(interaction, profile: str = 'https://www.battlemetrics.com/players/1128280744'):
        if not await require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pid = profile_id(profile)
            data = await bot.bm.profile(pid)
            rows = [{'id': r['id'], 'name': r['attributes']['name'].strip()} for r in data.get('included', [])
                    if r.get('type') == 'server' and r.get('relationships', {}).get('game', {}).get('data', {}).get('id') == 'rust']
            if not rows:
                raise ValueError('El perfil no tiene servidores Rust accesibles.')
            bot.store.save_servers(rows)
            bot.directory.merge(rows)
            await interaction.followup.send(embed=success_embed(f'Importados/actualizados **{len(rows)}** servidores. Míralos con `/servers`. Esto no activa vigilancias.'), ephemeral=True)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)), ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed('No se pudo actualizar el directorio.', 'Revisa el acceso a BattleMetrics.'), ephemeral=True)

    async def toggle(interaction, enabled):
        if not await require_admin(interaction):
            return
        # Conserva canal, idioma e intervalo; solo cambia el interruptor de alertas.
        saved = bot.store.settings(interaction.guild_id) or (interaction.channel_id, 'es', 1, bot.settings.poll_interval)
        bot.store.set_settings(interaction.guild_id, saved[0], saved[1], enabled, saved[3])
        msg = '🔔 Alertas reactivadas para cambios futuros.' if enabled else '⏸️ Alertas pausadas. Las vigilancias se conservan; no se enviarán avisos atrasados.'
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(name='pausealerts', description='⏸️ Pausa alertas de este Discord sin borrar vigilancias')
    async def pause_alerts(interaction):
        await toggle(interaction, False)

    @bot.tree.command(name='resumealerts', description='🔔 Reactiva alertas para futuros cambios de presencia')
    async def resume_alerts(interaction):
        await toggle(interaction, True)

    @bot.tree.command(name='wipe', description='🗓️ Último y próximo wipe publicados por el servidor')
    @app_commands.autocomplete(server=servers)
    async def wipe(interaction, server: str):
        await interaction.response.defer(ephemeral=True)
        try:
            d = await bot.bm.server(bot.directory.resolve(server))
            a = d['attributes']
            details = a.get('details', {})
            lines = []
            for label, key in [('🧹 Último wipe', 'rust_last_wipe'), ('⏭️ Próximo wipe', 'rust_next_wipe')]:
                stamp = iso_to_ts(details.get(key))
                lines.append(f'**{label}**: ' + (f'<t:{stamp}:F> · <t:{stamp}:R>' if stamp else 'No publicado'))
            e = brand_embed(f"🗓️ {a.get('name', 'Servidor')}", '\n'.join(lines))
            e.set_footer(text='Horario publicado por BattleMetrics; puede cambiar.')
            await interaction.followup.send(embed=e, ephemeral=True)
        except Exception:
            await interaction.followup.send(embed=error_embed('No se pudo consultar el wipe de ese servidor.', 'Elige el servidor de la lista de sugerencias.'), ephemeral=True)
