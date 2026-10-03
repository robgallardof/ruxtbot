"""/help: a Components V2 menu in the user's language, with buttons that open the tools directly."""
from __future__ import annotations
import discord
from discord import ui
from .i18n import lang_for, t
from .raid import builder_layout, home_layout
from .raid_data import BEST, RaidData
from .ui import YELLOW, OwnedLayout

HELP_SECTIONS = ('help.raid', 'help.craft', 'help.servers', 'help.players', 'help.admin')
LOGO = 'https://wiki.rustclash.com/img/items180/explosive.timed.png'


def help_layout(data: RaidData, lang: str, owner_id: int | None = None, open_players=None) -> OwnedLayout:
    """`open_players`: coroutine that opens the player lookup panel (the /who hub)."""
    view = OwnedLayout(owner_id)
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.Section(ui.TextDisplay(f"# {t(lang, 'help.title')}\n{t(lang, 'help.intro')}"), accessory=ui.Thumbnail(LOGO)))
    box.add_item(ui.Separator())

    async def open_planner(interaction):
        layout = home_layout(data, lang_for(interaction), interaction.user.id)
        await interaction.response.send_message(view=layout, ephemeral=True)
        layout.message = await interaction.original_response()

    async def open_calc(interaction):
        layout = builder_layout(data, lang_for(interaction), {}, BEST, 'doors', interaction.user.id)
        await interaction.response.send_message(view=layout, ephemeral=True)
        layout.message = await interaction.original_response()

    for key in HELP_SECTIONS:
        if key == 'help.raid':
            # The raid section gets a shortcut button right next to its description.
            open_button = ui.Button(label=t(lang, 'raid.open'), emoji='💥', style=discord.ButtonStyle.danger)
            open_button.callback = open_planner
            box.add_item(ui.Section(ui.TextDisplay(t(lang, key)), accessory=open_button))
        elif key == 'help.players' and open_players:
            find_button = ui.Button(label=t(lang, 'help.players.button'), emoji='🔎', style=discord.ButtonStyle.primary)
            find_button.callback = open_players
            box.add_item(ui.Section(ui.TextDisplay(t(lang, key)), accessory=find_button))
        else:
            box.add_item(ui.TextDisplay(t(lang, key)))
    calc_button = ui.Button(label=t(lang, 'raid.calc.button'), emoji='🧮', style=discord.ButtonStyle.primary)
    calc_button.callback = open_calc
    box.add_item(ui.Separator())
    box.add_item(ui.ActionRow(calc_button))
    box.add_item(ui.TextDisplay(f"-# {t(lang, 'help.footer')} · {data.version}"))
    view.add_item(box)
    return view
