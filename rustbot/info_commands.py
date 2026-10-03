"""Informational commands: /author and /examples."""
from __future__ import annotations
import discord
from discord import ui
from .i18n import lang_for, t
from .ui import YELLOW

AUTHOR = 'KingGallardo'
REPO_URL = 'https://github.com/robgallardof/ruxtbot'
ICON = 'https://wiki.rustclash.com/img/items180/{}.png'

# (section key, icon shortName) in display order; texts live in i18n.STRINGS.
EXAMPLE_SECTIONS = [
    ('examples.raid', 'explosive.timed'),
    ('examples.craft', 'ammo.rocket.basic'),
    ('examples.servers', 'map'),
    ('examples.players', 'door.hinged.toptier'),
    ('examples.admin', 'cupboard.tool'),
]


def author_embed(lang: str) -> discord.Embed:
    e = discord.Embed(title=t(lang, 'author.title'), description=t(lang, 'author.body', author=AUTHOR), color=YELLOW, url=REPO_URL)
    e.set_thumbnail(url=ICON.format('explosive.timed'))
    e.set_footer(text='RuxtBot')
    return e


def examples_layout(lang: str) -> ui.LayoutView:
    """Copy-ready examples for every area, each next to a picture."""
    view = ui.LayoutView()
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(f"# {t(lang, 'examples.title')}\n{t(lang, 'examples.intro')}"))
    box.add_item(ui.Separator())
    for key, icon in EXAMPLE_SECTIONS:
        box.add_item(ui.Section(ui.TextDisplay(t(lang, key)), accessory=ui.Thumbnail(ICON.format(icon))))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay('-# ' + t(lang, 'examples.footer')))
    view.add_item(box)
    return view


def register_info(bot) -> None:
    @bot.tree.command(name='author', description='👑 Who made RuxtBot')
    async def author(interaction: discord.Interaction):
        await interaction.response.send_message(embed=author_embed(lang_for(interaction)))

    @bot.tree.command(name='examples', description='📖 Examples of what the bot does and how to use it')
    async def examples(interaction: discord.Interaction):
        await interaction.response.send_message(view=examples_layout(lang_for(interaction)), ephemeral=True)
