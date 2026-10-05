"""/gamma: a guided setup for an AutoHotkey script that raises the NVIDIA gamma, with your own keys.

The command posts a short public card. 🚀 Start opens a private 4-step wizard (only the clicker sees it, in their
Discord language): install AutoHotkey, pick keys, download the script, run it as administrator.
Every control carries the step and the keys in its ID, so cards and wizards keep working after the bot restarts.
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
ICON = 'https://wiki.rustclash.com/img/items180/nightvisiongoggles.png'
MESSAGE_LIMIT = 2000  # characters per Discord message
STEPS = 4

# (English label, AutoHotkey key name) for the menus. At most 25, Discord's limit for options.
MENU_KEYS = [*((f'F{n}', f'F{n}') for n in range(1, 13)), ('Mouse 4', 'XButton1'), ('Mouse 5', 'XButton2'),
             ('Middle click', 'MButton'), ('Insert', 'Insert'), ('Home', 'Home'), ('End', 'End'), ('Page Up', 'PgUp'),
             ('Page Down', 'PgDn'), ('Pause', 'Pause'), ('Scroll Lock', 'ScrollLock'), ('Numpad 0', 'Numpad0'),
             ('Numpad +', 'NumpadAdd'), ('Numpad -', 'NumpadSub')]
LABELS = {key: name for name, key in MENU_KEYS}
LABELS_ES = {'MButton': 'Clic central', 'PgUp': 'Re Pág', 'PgDn': 'Av Pág', 'Home': 'Inicio', 'End': 'Fin'}

# Every key that can be typed in the modal, by lowercase name, so a typo never reaches the script.
TYPED_KEYS = {k.lower(): k for k in [
    *(f'F{n}' for n in range(1, 25)), *'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    *(f'Numpad{n}' for n in range(10)), 'NumpadAdd', 'NumpadSub', 'NumpadMult', 'NumpadDiv', 'NumpadDot', 'NumpadEnter',
    'XButton1', 'XButton2', 'MButton', 'Insert', 'Delete', 'Home', 'End', 'PgUp', 'PgDn', 'Pause', 'ScrollLock',
    'CapsLock', 'Tab', 'Space', 'Up', 'Down', 'Left', 'Right', 'AppsKey', 'PrintScreen']}
TYPED_KEYS.update({'mouse4': 'XButton1', 'mouse5': 'XButton2', 'm4': 'XButton1', 'm5': 'XButton2', 'pageup': 'PgUp',
                   'pagedown': 'PgDn', 'del': 'Delete', 'ins': 'Insert', 'middleclick': 'MButton', 'cliccentral': 'MButton',
                   'inicio': 'Home', 'fin': 'End', 'repág': 'PgUp', 'avpág': 'PgDn', 'repag': 'PgUp', 'avpag': 'PgDn',
                   'supr': 'Delete', 'espacio': 'Space'})

# The script's own messages (MsgBox and tooltips), in Spanish for Spanish users.
SCRIPT_ES = [
    ('"Failed to initialize NVIDIA NVAPI.`n`n"', '"No se pudo iniciar NVIDIA NVAPI.`n`n"'),
    ('"Make sure the display is connected to the NVIDIA GPU."', '"Revisa que el monitor esté conectado a la gráfica NVIDIA."'),
    ('"NVIDIA rejected the gamma change."', '"NVIDIA rechazó el cambio de gamma."'),
    ('"NVIDIA rejected the gamma reset."', '"NVIDIA rechazó el reset de gamma."'),
    ('"This NVIDIA driver does not expose the required "', '"Este driver de NVIDIA no trae la función "'),
    ('. "gamma correction function."', '. "de corrección de gamma."'),
    ('"Gamma: HIGH ("', '"Gamma: ALTO ("'),
]

ID = r'gamma:(?P<action>{actions}):(?P<step>\d):(?P<toggle>\w{{1,20}}):(?P<reset>\w{{1,20}})'


def parse_key(text: str) -> str | None:
    """AutoHotkey name for a typed key ('mouse 4', 'f10', 'Numpad5'…), or None if it is not one we allow."""
    return TYPED_KEYS.get(re.sub(r'[\s_-]', '', text or '').lower())


def label(key: str, lang: str = 'en') -> str:
    return (LABELS_ES.get(key) if lang == 'es' else None) or LABELS.get(key, key)


def gamma_script(template: str, toggle: str = 'F10', reset: str = 'F9', lang: str = 'en') -> str:
    """The AutoHotkey script with the chosen keys (`toggle` alone, `reset` with Shift) and messages in `lang`."""
    toggle_label, reset_label = label(toggle), f'Shift + {label(reset)}'
    width = max(len(toggle_label), len(reset_label))
    script = (template
              .replace('; F10        -> Toggle', f'; {toggle_label.ljust(width)} -> Toggle')
              .replace('; Shift + F9 -> Emergency', f'; {reset_label.ljust(width)} -> Emergency')
              .replace('TOGGLE_KEY := "F10"', f'TOGGLE_KEY := "{toggle}"')
              .replace('RESET_KEY  := "+F9"', f'RESET_KEY  := "+{reset}"'))
    if lang == 'es':
        for english, spanish in SCRIPT_ES:
            script = script.replace(english, spanish)
    return script


def compact(script: str) -> str:
    """The script without comments and blank lines: same behaviour, fewer parts to copy."""
    return '\n'.join(line for line in script.split('\n') if line.strip() and not line.lstrip().startswith(';'))


def code_blocks(code: str, language: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Wrap code in as few ```language blocks as fit in `limit` characters each (minus room for a part number)."""
    room = limit - len(f'**99/99**\n```{language}\n\n```')
    blocks, block = [], []
    for line in code.rstrip().split('\n'):
        if block and len('\n'.join(block)) + 1 + len(line) > room:
            # Full: cut before the last line at column 0 (a new function or statement), so parts read whole.
            cut = max((n for n, l in enumerate(block) if n and l[:1] not in ' \t{}'), default=len(block))
            blocks.append('\n'.join(block[:cut]))
            block = block[cut:]
        block.append(line)
    blocks.append('\n'.join(block))
    return [f'```{language}\n{b}\n```' for b in blocks if b.strip()]


def script_file(script: str) -> discord.File:
    # BOM so Notepad and AutoHotkey both read the accents right.
    return discord.File(io.BytesIO(script.encode('utf-8-sig')), filename='gamma.ahk')


def keys_text(lang: str, toggle: str, reset: str) -> dict[str, str]:
    return {'toggle': label(toggle, lang), 'reset': f'Shift + {label(reset, lang)}'}


# ── public card ──

def gamma_card(lang: str, toggle: str = 'F10', reset: str = 'F9') -> ui.LayoutView:
    """What /gamma posts: what it is, what you need, and 🚀 Start."""
    view = ui.LayoutView(timeout=None)
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.Section(ui.TextDisplay(t(lang, 'gamma.card', **keys_text(lang, toggle, reset))), accessory=ui.Thumbnail(ICON)))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay(t(lang, 'gamma.card.needs')))
    box.add_item(ui.ActionRow(GammaButton('start', 1, toggle, reset, lang), GammaButton('download', 0, toggle, reset, lang),
                              ui.Button(label='AutoHotkey', emoji='🌐', url=AHK_URL)))
    view.add_item(box)
    return view


# ── private wizard ──

def wizard(lang: str, step: int, toggle: str, reset: str) -> tuple[ui.LayoutView, list[discord.File]]:
    """One step of the setup with ◀️ / ▶️. Also returns the files the step shows (only step 3 has the script)."""
    keys = keys_text(lang, toggle, reset)
    files = []
    view = ui.LayoutView(timeout=None)
    box = ui.Container(accent_colour=YELLOW)
    bar = '🟩' * step + '⬛' * (STEPS - step)
    box.add_item(ui.TextDisplay(t(lang, 'gamma.wizard.head', bar=bar, step=step, steps=STEPS, name=t(lang, f'gamma.step{step}.name'))))
    box.add_item(ui.Separator())
    if step == 1:
        box.add_item(ui.Section(ui.TextDisplay(t(lang, 'gamma.step1')),
                                accessory=ui.Button(label=t(lang, 'gamma.button.ahk'), emoji='🌐', url=AHK_URL)))
    elif step == 2:
        box.add_item(ui.TextDisplay(t(lang, 'gamma.step2', **keys)))
        box.add_item(ui.ActionRow(KeyMenu('toggle', toggle, reset, lang)))
        box.add_item(ui.ActionRow(KeyMenu('reset', toggle, reset, lang)))
        box.add_item(ui.ActionRow(GammaButton('type', 2, toggle, reset, lang)))
    elif step == 3:
        box.add_item(ui.TextDisplay(t(lang, 'gamma.step3', **keys)))
        box.add_item(ui.File('attachment://gamma.ahk'))
        files.append(script_file(gamma_script(GammaButton.script, toggle, reset, lang)))
        box.add_item(ui.ActionRow(GammaButton('download', 3, toggle, reset, lang), GammaButton('copy', 3, toggle, reset, lang)))
        box.add_item(ui.TextDisplay(t(lang, 'gamma.step3.note')))
    else:
        box.add_item(ui.TextDisplay(t(lang, 'gamma.step4', **keys)))
        box.add_item(ui.Separator())
        box.add_item(ui.TextDisplay(t(lang, 'gamma.tips', **keys)))
    box.add_item(ui.Separator())
    back = GammaButton('back', max(step - 1, 1), toggle, reset, lang, disabled=step == 1)
    forward = GammaButton('next', step + 1, toggle, reset, lang) if step < STEPS else GammaButton('restart', 1, toggle, reset, lang)
    box.add_item(ui.ActionRow(back, forward))
    view.add_item(box)
    return view, files


async def show_wizard(interaction: discord.Interaction, step: int, toggle: str, reset: str) -> None:
    """From the public card: open the user's own wizard. From their wizard: move it in place."""
    view, files = wizard(lang_for(interaction), step, toggle, reset)
    message = getattr(interaction, 'message', None)
    if message is not None and message.flags.ephemeral:
        await interaction.response.edit_message(view=view, attachments=files)
    else:
        await interaction.response.send_message(view=view, files=files, ephemeral=True)


class KeyMenu(ui.DynamicItem[ui.Select], template=ID.format(actions='toggle|reset')):
    """🔆 / 🧯 menu on step 2: picks the on/off key or the reset key."""

    def __init__(self, which: str, toggle: str, reset: str, lang: str = 'en'):
        current = toggle if which == 'toggle' else reset
        options = [discord.SelectOption(label=label(key, lang), value=key, default=key == current,
                                        description=t(lang, 'gamma.f1') if key == 'F1' else None) for _, key in MENU_KEYS]
        super().__init__(ui.Select(placeholder=t(lang, f'gamma.pick.{which}', name=label(current, lang)), options=options,
                                   custom_id=f'gamma:{which}:2:{toggle}:{reset}'))
        self.which, self.toggle, self.reset = which, toggle, reset

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(match['action'], match['toggle'], match['reset'], lang_for(interaction))

    async def callback(self, interaction: discord.Interaction):
        key = parse_key((interaction.data.get('values') or [''])[0])
        if not key:
            return await interaction.response.defer()
        toggle, reset = (key, self.reset) if self.which == 'toggle' else (self.toggle, key)
        await show_wizard(interaction, 2, toggle, reset)


class KeysModal(ui.Modal):
    """✏️ Type any key, for the ones that are not in the menus."""

    def __init__(self, lang: str, toggle: str, reset: str):
        super().__init__(title=t(lang, 'gamma.modal.title'))
        self.lang = lang
        self.toggle = ui.TextInput(label=t(lang, 'gamma.modal.toggle'), default=label(toggle, lang), max_length=20,
                                   placeholder=t(lang, 'gamma.modal.hint'))
        self.reset = ui.TextInput(label=t(lang, 'gamma.modal.reset'), default=label(reset, lang), max_length=20,
                                  placeholder=t(lang, 'gamma.modal.hint'))
        self.add_item(self.toggle)
        self.add_item(self.reset)

    async def on_submit(self, interaction: discord.Interaction):
        toggle, reset = parse_key(self.toggle.value), parse_key(self.reset.value)
        if not toggle or not reset:
            wrong = self.toggle.value if not toggle else self.reset.value
            await interaction.response.send_message(t(self.lang, 'gamma.bad_key', name=wrong[:20]), ephemeral=True)
            return
        await show_wizard(interaction, 2, toggle, reset)


class GammaButton(ui.DynamicItem[ui.Button], template=ID.format(actions='start|back|next|restart|download|copy|type')):
    """Every button of the card and the wizard. Replies only to whoever clicks, in their language."""
    script = ''  # data/gamma.ahk, set by register_gamma
    STYLE = {'start': ('🚀', discord.ButtonStyle.success), 'download': ('⬇️', discord.ButtonStyle.success),
             'copy': ('📋', discord.ButtonStyle.secondary), 'type': ('✏️', discord.ButtonStyle.secondary),
             'back': ('◀️', discord.ButtonStyle.secondary), 'next': ('▶️', discord.ButtonStyle.primary),
             'restart': ('🔁', discord.ButtonStyle.secondary)}

    def __init__(self, action: str, step: int, toggle: str, reset: str, lang: str = 'en', disabled: bool = False):
        emoji, style = self.STYLE[action]
        # Step 0 marks the card's quick download, which says which key it comes with.
        text = t(lang, 'gamma.button.quick', name=label(toggle, lang)) if action == 'download' and step == 0 else t(lang, f'gamma.button.{action}')
        super().__init__(ui.Button(label=text, emoji=emoji, style=style, disabled=disabled,
                                   custom_id=f'gamma:{action}:{step}:{toggle}:{reset}'))
        self.action, self.step, self.toggle, self.reset = action, step, toggle, reset

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(match['action'], int(match['step']), match['toggle'], match['reset'], lang_for(interaction))

    async def callback(self, interaction: discord.Interaction):
        lang = lang_for(interaction)
        if not self.script or not parse_key(self.toggle) or not parse_key(self.reset):
            await interaction.response.send_message(t(lang, 'gamma.missing'), ephemeral=True)
            return
        if self.action in ('start', 'back', 'next', 'restart'):
            await show_wizard(interaction, min(max(self.step, 1), STEPS), self.toggle, self.reset)
            return
        if self.action == 'type':
            await interaction.response.send_modal(KeysModal(lang, self.toggle, self.reset))
            return
        code = gamma_script(self.script, self.toggle, self.reset, lang)
        if self.action == 'download':
            await interaction.response.send_message(t(lang, 'gamma.download', **keys_text(lang, self.toggle, self.reset)),
                                                    file=script_file(code), ephemeral=True)
            return
        # Without comments it fits in fewer parts; Discord's copy button on each block copies just that part.
        blocks = code_blocks(compact(code), 'ahk')
        await interaction.response.send_message(t(lang, 'gamma.copy', parts=len(blocks)), ephemeral=True)
        for n, block in enumerate(blocks, 1):
            await interaction.followup.send(f'**{n}/{len(blocks)}**\n{block}', ephemeral=True)


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
        # Public like /binds: anyone in the channel can press Start and set up their own copy, in their language.
        await interaction.response.send_message(view=gamma_card(lang, key, reset))
