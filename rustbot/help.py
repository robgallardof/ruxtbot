"""Menú de ayuda interactivo de /help.

Un selector cambia la sección mostrada y los botones abren las herramientas
directamente, para que el usuario no tenga que memorizar comandos.
"""
from __future__ import annotations
import discord
from .raid import RaidBuilderView, RaidStartView, category_embed, plan_embed
from .ui import OwnedView, brand_embed

# Sección → (emoji, título, [(comando, explicación)]).
SECTIONS = {
    'raid': ('💥', 'Raid', [
        ('/raid', 'Planificador paso a paso: categoría → objetivo → simulación con vida restante, deshacer y comparar.'),
        ('/raidcalc', 'Calculadora de base: suma varias puertas y muros y obtén explosivos, azufre y materiales.'),
        ('/raidbudget azufre:', '¿Qué puedo fabricar y destruir con cierto azufre?'),
        ('/raidcompare objetivo:', 'Todos los métodos de un objetivo ordenados por azufre (🏆 el más barato).'),
        ('/raidplan', 'Varios objetivos iguales con un método concreto.'),
        ('/raidtools objetivo:', 'Daño por unidad de cada método.'),
    ]),
    'craft': ('🛠️', 'Crafteo e ítems', [
        ('/craft item: quantity:', 'Recursos base e intermedios para fabricar cualquier cantidad.'),
        ('/item query:', 'Ficha de un ítem: receta, alias y en qué raids se usa.'),
        ('/sources', 'Versión del catálogo, fuentes y nivel de confianza.'),
    ]),
    'servers': ('🖥️', 'Servidores', [
        ('/server', 'Estado, jugadores, cola, mapa y wipe de un servidor.'),
        ('/servers', 'Lista paginada del directorio de servidores.'),
        ('/wipe', 'Último y próximo wipe publicados.'),
    ]),
    'players': ('🕵️', 'Jugadores', [
        ('/who jugador:', 'Ficha completa: Steam, baneos, nombres usados, estadísticas de Rust y BattleMetrics.'),
        ('/player', 'Si un perfil de BattleMetrics está conectado en un servidor.'),
    ]),
    'admin': ('⚙️', 'Administración', [
        ('/track add|remove|list', 'Vigila conexiones y avisa al rol @wipe.'),
        ('/settings', 'Canal de alertas, idioma, intervalo.'),
        ('/pausealerts · /resumealerts', 'Pausa o reanuda avisos sin borrar vigilancias.'),
        ('/status · /syncservers · /ping', 'Estado del bot, importar servidores y latencia.'),
    ]),
}


def home_embed(catalog) -> discord.Embed:
    e = brand_embed('🦀 RuxtBot', 'Tu compañero para **raids, crafteo, servidores y jugadores** de Rust.\nElige una sección en el menú o abre una herramienta con los botones.')
    for emoji, title, commands in SECTIONS.values():
        e.add_field(name=f'{emoji} {title}', value=' '.join(f'`{c.split()[0]}`' for c, _ in commands), inline=True)
    e.set_footer(text=f'Datos: {catalog.version}')
    return e


def section_embed(catalog, key: str) -> discord.Embed:
    emoji, title, commands = SECTIONS[key]
    e = brand_embed(f'{emoji} {title}', '\n'.join(f'**`{c}`**\n{text}' for c, text in commands))
    e.set_footer(text=f'Datos: {catalog.version}')
    return e


class HelpView(OwnedView):
    def __init__(self, catalog=None, owner_id=None):
        super().__init__(owner_id, timeout=300)
        self.catalog = catalog
        select = discord.ui.Select(placeholder='📚 Elige una sección', options=[
            discord.SelectOption(label='Inicio', value='home', emoji='🏠')] + [
            discord.SelectOption(label=title, value=key, emoji=emoji) for key, (emoji, title, _) in SECTIONS.items()])
        select.callback = self._section
        self.add_item(select)

    async def _section(self, interaction):
        key = interaction.data['values'][0]
        e = home_embed(self.catalog) if key == 'home' else section_embed(self.catalog, key)
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label='Planificador de raid', emoji='💥', style=discord.ButtonStyle.danger, row=1)
    async def raid_button(self, interaction, _):
        view = RaidStartView(self.catalog, interaction.user.id)
        await interaction.response.send_message(embed=category_embed(self.catalog), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @discord.ui.button(label='Calculadora de base', emoji='🧮', style=discord.ButtonStyle.primary, row=1)
    async def calc_button(self, interaction, _):
        view = RaidBuilderView(self.catalog, owner_id=interaction.user.id)
        await interaction.response.send_message(embed=plan_embed(self.catalog, {}), view=view, ephemeral=True)
        view.message = await interaction.original_response()
