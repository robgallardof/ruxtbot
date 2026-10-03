"""/help: a Components V2 menu in the user's language, with buttons that open the tools directly."""
from __future__ import annotations
import discord
from discord import ui
from .i18n import lang_for, t
from .raid import builder_layout, home_layout
from .raid_data import BEST, RaidData
from .ui import YELLOW, OwnedLayout

HELP_SECTIONS = ('help.raid', 'help.craft', 'help.servers', 'help.players', 'help.alerts', 'help.admin')
LOGO = 'https://wiki.rustclash.com/img/items180/explosive.timed.png'


# section -> (shortcut key, label key, emoji): the button shown next to that section.
SECTION_BUTTONS = {'help.servers': ('sv', 'help.button.sv', '🎮'), 'help.players': ('players', 'help.players.button', '🔎'),
                   'help.alerts': ('track', 'help.button.track', '👀')}


def help_layout(data: RaidData, lang: str, owner_id: int | None = None, open_players=None, shortcuts: dict | None = None) -> OwnedLayout:
    """`shortcuts`: key -> coroutine(interaction) for the buttons ('players', 'sv', 'track', 'me').
    `open_players` is kept as a shorthand for shortcuts['players']."""
    shortcuts = dict(shortcuts or {})
    if open_players:
        shortcuts.setdefault('players', open_players)
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
        elif key in SECTION_BUTTONS and SECTION_BUTTONS[key][0] in shortcuts:
            name, label, emoji = SECTION_BUTTONS[key]
            button = ui.Button(label=t(lang, label), emoji=emoji, style=discord.ButtonStyle.primary)
            button.callback = shortcuts[name]
            box.add_item(ui.Section(ui.TextDisplay(t(lang, key)), accessory=button))
        else:
            box.add_item(ui.TextDisplay(t(lang, key)))
    calc_button = ui.Button(label=t(lang, 'raid.calc.button'), emoji='🧮', style=discord.ButtonStyle.primary)
    calc_button.callback = open_calc
    row = [calc_button]
    if 'me' in shortcuts:
        me_button = ui.Button(label=t(lang, 'help.button.me'), emoji='👤', style=discord.ButtonStyle.success)
        me_button.callback = shortcuts['me']
        row.append(me_button)
    box.add_item(ui.Separator())
    box.add_item(ui.ActionRow(*row))
    box.add_item(ui.TextDisplay(f"-# {t(lang, 'help.footer')} · {data.version}"))
    view.add_item(box)
    return view
