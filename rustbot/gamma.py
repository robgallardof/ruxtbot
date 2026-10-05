"""/gamma: a step-by-step panel to install an AutoHotkey script that raises the NVIDIA gamma, with your own keys.

The panel is public. Picking a key on it opens your own copy (only you see it), and picking again there updates it.
Every control carries the chosen keys in its ID, so the panel keeps working after the bot restarts.
"""
from __future__ import annotations
import io
import re
from pathlib import Path
import discord
from discord import app_commands, ui
from .i18n import lang_for, t
from .ui import YELLOW

AHK_URL = 'https://www.autohotkey.com'
MESSAGE_LIMIT = 2000  # characters per Discord message

# (label shown in Discord, AutoHotkey key name) for the menus. At most 25, Discord's limit for options.
MENU_KEYS = [*((f'F{n}', f'F{n}') for n in range(1, 13)), ('Mouse 4', 'XButton1'), ('Mouse 5', 'XButton2'),
             ('Middle click', 'MButton'), ('Insert', 'Insert'), ('Home', 'Home'), ('End', 'End'), ('Page Up', 'PgUp'),
             ('Page Down', 'PgDn'), ('Pause', 'Pause'), ('Scroll Lock', 'ScrollLock'), ('Numpad 0', 'Numpad0'),
             ('Numpad +', 'NumpadAdd'), ('Numpad -', 'NumpadSub')]
LABELS = {key: label for label, key in MENU_KEYS}

# Every key that can be typed in the modal, by lowercase name, so a typo never reaches the script.
TYPED_KEYS = {k.lower(): k for k in [
    *(f'F{n}' for n in range(1, 25)), *'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    *(f'Numpad{n}' for n in range(10)), 'NumpadAdd', 'NumpadSub', 'NumpadMult', 'NumpadDiv', 'NumpadDot', 'NumpadEnter',
    'XButton1', 'XButton2', 'MButton', 'Insert', 'Delete', 'Home', 'End', 'PgUp', 'PgDn', 'Pause', 'ScrollLock',
    'CapsLock', 'Tab', 'Space', 'Up', 'Down', 'Left', 'Right', 'AppsKey', 'PrintScreen']}
TYPED_KEYS.update({'mouse4': 'XButton1', 'mouse5': 'XButton2', 'm4': 'XButton1', 'm5': 'XButton2', 'pageup': 'PgUp',
                   'pagedown': 'PgDn', 'del': 'Delete', 'ins': 'Insert', 'middleclick': 'MButton'})

ID = r'gamma:(?P<action>{actions}):(?P<toggle>\w{{1,20}}):(?P<reset>\w{{1,20}})'


def parse_key(text: str) -> str | None:
    """AutoHotkey name for a typed key ('mouse 4', 'f10', 'Numpad5'…), or None if it is not one we allow."""
    return TYPED_KEYS.get(re.sub(r'[\s_-]', '', text or '').lower())


def label(key: str) -> str:
    return LABELS.get(key, key)


def gamma_script(template: str, toggle: str = 'F10', reset: str = 'F9') -> str:
    """The AutoHotkey script with the chosen keys: `toggle` alone, `reset` with Shift."""
    toggle_label, reset_label = label(toggle), f'Shift + {label(reset)}'
    width = max(len(toggle_label), len(reset_label))
    return (template
            .replace('; F10        -> Toggle', f'; {toggle_label.ljust(width)} -> Toggle')
            .replace('; Shift + F9 -> Emergency', f'; {reset_label.ljust(width)} -> Emergency')
            .replace('TOGGLE_KEY := "F10"', f'TOGGLE_KEY := "{toggle}"')
            .replace('RESET_KEY  := "+F9"', f'RESET_KEY  := "+{reset}"'))


def code_blocks(code: str, language: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Wrap code in as few ```language blocks as fit in `limit` characters each, cutting at blank lines."""
    room = limit - len(f'```{language}\n\n```')
    blocks, block = [], []
    for line in code.rstrip().split('\n'):
        size = len('\n'.join(block))
        if block and (size + 1 + len(line) > room or (not line.strip() and size > room * 0.75)):
            blocks.append('\n'.join(block).strip('\n'))
            block = []
        block.append(line)
    blocks.append('\n'.join(block).strip('\n'))
    return [f'```{language}\n{b}\n```' for b in blocks if b]


def script_file(script: str) -> discord.File:
    return discord.File(io.BytesIO(script.encode('utf-8')), filename='gamma.ahk')


def gamma_panel(lang: str, template: str, toggle: str = 'F10', reset: str = 'F9') -> tuple[ui.LayoutView, discord.File]:
    """The four steps with the key menus, a preview of the script and its buttons. Send the file with the view."""
    keys = {'toggle': label(toggle), 'reset': f'Shift + {label(reset)}'}
    config = f'TOGGLE_KEY := "{toggle}"   ; {keys["toggle"]}\nRESET_KEY  := "+{reset}"   ; {keys["reset"]}\nHIGH_GAMMA := 2.80'
    view = ui.LayoutView(timeout=None)
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(t(lang, 'gamma.title')))
    box.add_item(ui.Separator())
    box.add_item(ui.Section(ui.TextDisplay(t(lang, 'gamma.step1')),
                            accessory=ui.Button(label=t(lang, 'gamma.button.ahk'), emoji='🌐', url=AHK_URL)))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay(t(lang, 'gamma.step2', **keys)))
    for which in ('toggle', 'reset'):
        box.add_item(ui.ActionRow(KeyMenu(which, toggle, reset, lang)))
    box.add_item(ui.ActionRow(GammaButton('type', toggle, reset, lang)))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay(t(lang, 'gamma.step3', config=config)))
    box.add_item(ui.File('attachment://gamma.ahk'))
    box.add_item(ui.ActionRow(GammaButton('download', toggle, reset, lang), GammaButton('copy', toggle, reset, lang)))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay(t(lang, 'gamma.step4', **keys)))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay(t(lang, 'gamma.tips', **keys)))
    view.add_item(box)
    return view, script_file(gamma_script(template, toggle, reset))


async def show_panel(interaction: discord.Interaction, toggle: str, reset: str) -> None:
    """From the public panel: open the user's own copy. From their own copy: update it in place."""
    lang = lang_for(interaction)
    view, file = gamma_panel(lang, GammaButton.script, toggle, reset)
    message = getattr(interaction, 'message', None)
    if message is not None and message.flags.ephemeral:
        await interaction.response.edit_message(view=view, attachments=[file])
    else:
        await interaction.response.send_message(view=view, file=file, ephemeral=True)


class KeyMenu(ui.DynamicItem[ui.Select], template=ID.format(actions='toggle|reset')):
    """🔆 / 🧯 menu: picks the on/off key or the reset key."""

    def __init__(self, which: str, toggle: str, reset: str, lang: str = 'en'):
        current = toggle if which == 'toggle' else reset
        options = [discord.SelectOption(label=name, value=key, default=key == current) for name, key in MENU_KEYS]
        super().__init__(ui.Select(placeholder=t(lang, f'gamma.pick.{which}', name=label(current)), options=options,
                                   custom_id=f'gamma:{which}:{toggle}:{reset}'))
        self.which, self.toggle, self.reset = which, toggle, reset

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(match['action'], match['toggle'], match['reset'], lang_for(interaction))

    async def callback(self, interaction: discord.Interaction):
        key = parse_key((interaction.data.get('values') or [''])[0])
        if not key:
            return await interaction.response.defer()
        toggle, reset = (key, self.reset) if self.which == 'toggle' else (self.toggle, key)
        await show_panel(interaction, toggle, reset)


class KeysModal(ui.Modal):
    """✏️ Type any key, for the ones that are not in the menus."""

    def __init__(self, lang: str, toggle: str, reset: str):
        super().__init__(title=t(lang, 'gamma.modal.title'))
        self.lang = lang
        self.toggle = ui.TextInput(label=t(lang, 'gamma.modal.toggle'), default=label(toggle), max_length=20,
                                   placeholder=t(lang, 'gamma.modal.hint'))
        self.reset = ui.TextInput(label=t(lang, 'gamma.modal.reset'), default=label(reset), max_length=20,
                                  placeholder=t(lang, 'gamma.modal.hint'))
        self.add_item(self.toggle)
        self.add_item(self.reset)

    async def on_submit(self, interaction: discord.Interaction):
        toggle, reset = parse_key(self.toggle.value), parse_key(self.reset.value)
        if not toggle or not reset:
            wrong = self.toggle.value if not toggle else self.reset.value
            await interaction.response.send_message(t(self.lang, 'gamma.bad_key', name=wrong[:20]), ephemeral=True)
            return
        await show_panel(interaction, toggle, reset)


class GammaButton(ui.DynamicItem[ui.Button], template=ID.format(actions='download|copy|type')):
    """⬇️ the file · 📋 the code in copyable blocks · ✏️ type another key. Replies only to whoever clicks."""
    script = ''  # data/gamma.ahk, set by register_gamma
    STYLE = {'download': ('⬇️', discord.ButtonStyle.success), 'copy': ('📋', discord.ButtonStyle.primary),
             'type': ('✏️', discord.ButtonStyle.secondary)}

    def __init__(self, action: str, toggle: str, reset: str, lang: str = 'en'):
        emoji, style = self.STYLE[action]
        super().__init__(ui.Button(label=t(lang, f'gamma.button.{action}'), emoji=emoji, style=style,
                                   custom_id=f'gamma:{action}:{toggle}:{reset}'))
        self.action, self.toggle, self.reset = action, toggle, reset

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(match['action'], match['toggle'], match['reset'], lang_for(interaction))

    async def callback(self, interaction: discord.Interaction):
        lang = lang_for(interaction)
        if not self.script or not parse_key(self.toggle) or not parse_key(self.reset):
            await interaction.response.send_message(t(lang, 'gamma.missing'), ephemeral=True)
            return
        if self.action == 'type':
            await interaction.response.send_modal(KeysModal(lang, self.toggle, self.reset))
            return
        code = gamma_script(self.script, self.toggle, self.reset)
        if self.action == 'download':
            await interaction.response.send_message(t(lang, 'gamma.download'), file=script_file(code), ephemeral=True)
            return
        # Discord's copy button on each block copies just that part.
        blocks = code_blocks(code, 'ahk')
        await interaction.response.send_message(t(lang, 'gamma.copy', parts=len(blocks)), ephemeral=True)
        for block in blocks:
            await interaction.followup.send(block, ephemeral=True)


def register_gamma(bot) -> None:
    path = Path(bot.settings.data_path).with_name('gamma.ahk')
    GammaButton.script = path.read_text(encoding='utf-8') if path.exists() else ''
    bot.add_dynamic_items(GammaButton, KeyMenu)
    choices = [app_commands.Choice(name=name, value=key) for name, key in MENU_KEYS]

    @bot.tree.command(name='gamma', description='🌗 NVIDIA gamma script (AutoHotkey) to see at night, with your own key')
    @app_commands.describe(key='Key that turns the high gamma on and off (default F10)', reset='Emergency reset key, pressed with Shift (default F9)')
    @app_commands.choices(key=choices, reset=choices)
    async def gamma(interaction: discord.Interaction, key: str = 'F10', reset: str = 'F9'):
        lang = lang_for(interaction)
        if not GammaButton.script:
            await interaction.response.send_message(t(lang, 'gamma.missing'), ephemeral=True)
            return
        # Public like /binds: anyone in the channel can follow it and pick their own keys.
        view, file = gamma_panel(lang, GammaButton.script, key, reset)
        await interaction.response.send_message(view=view, file=file)
