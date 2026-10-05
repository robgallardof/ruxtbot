"""Informational commands: /author, /examples, /binds, /cctv and /gamma."""
from __future__ import annotations
import io
import re
from pathlib import Path
import discord
from discord import app_commands, ui
from .i18n import lang_for, t
from .ui import YELLOW, linkify

AUTHOR = 'KingGallardo'
REPO_URL = 'https://github.com/robgallardof/ruxtbot'
ICON = 'https://wiki.rustclash.com/img/items180/{}.png'

MESSAGE_LIMIT = 2000  # characters per Discord message


def split_sections(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split Markdown into messages of at most `limit` characters, only at `#`/`##` headings.

    Headings are never inside a code block in the binds guide, so a bind is never cut in half.
    A single section longer than `limit` is split at blank lines outside code blocks.
    """
    sections, current, in_code = [], [], False
    for line in text.strip().split('\n'):
        if line.startswith('```'):
            in_code = not in_code
        if not in_code and line.startswith(('# ', '## ')) and current:
            sections.append('\n'.join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append('\n'.join(current).strip())
    pieces = []
    for section in sections:
        if len(section) <= limit:
            pieces.append(section)
            continue
        block, in_code = [], False
        for line in section.split('\n'):
            if line.startswith('```'):
                in_code = not in_code
            if not in_code and not line.strip() and len('\n'.join(block)) > limit * 0.7:
                pieces.append('\n'.join(block).strip())
                block = []
            block.append(line)
        pieces.append('\n'.join(block).strip())
    chunks, chunk = [], ''
    for piece in pieces:
        # A top-level `# ` heading always starts a new message, so every part opens with its title.
        if chunk and (piece.startswith('# ') or len(chunk) + 2 + len(piece) > limit):
            chunks.append(chunk)
            chunk = piece
        else:
            chunk = f'{chunk}\n\n{piece}' if chunk else piece
    if chunk:
        chunks.append(chunk)
    return chunks


# (section key, icon shortName) in display order; texts live in i18n.STRINGS.
EXAMPLE_SECTIONS = [
    ('examples.setup', 'computerstation'),
    ('examples.servers', 'map'),
    ('examples.players', 'door.hinged.toptier'),
    ('examples.admin', 'smart.alarm'),
    ('examples.raid', 'explosive.timed'),
    ('examples.craft', 'cupboard.tool'),
]


# /gamma keys: (label shown in Discord, AutoHotkey key name). At most 25, Discord's limit for choices.
GAMMA_KEYS = [*((f'F{n}', f'F{n}') for n in range(1, 13)), ('Mouse 4', 'XButton1'), ('Mouse 5', 'XButton2'),
              ('Middle click', 'MButton'), ('Insert', 'Insert'), ('Home', 'Home'), ('End', 'End'), ('Page Up', 'PgUp'),
              ('Page Down', 'PgDn'), ('Pause', 'Pause'), ('Scroll Lock', 'ScrollLock'), ('Numpad 0', 'Numpad0'),
              ('Numpad +', 'NumpadAdd'), ('Numpad -', 'NumpadSub')]
GAMMA_KEY_LABELS = {key: label for label, key in GAMMA_KEYS}
GAMMA_AHK_URL = 'https://www.autohotkey.com'


def gamma_script(template: str, toggle: str = 'F10', reset: str = 'F9') -> str:
    """The AutoHotkey script with the chosen keys: `toggle` alone, `reset` with Shift."""
    toggle_label, reset_label = GAMMA_KEY_LABELS[toggle], f'Shift + {GAMMA_KEY_LABELS[reset]}'
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


class GammaButton(ui.DynamicItem[ui.Button], template=r'gamma:(?P<action>copy|download):(?P<toggle>\w+):(?P<reset>\w+)'):
    """📋 / ⬇️ under /gamma. The keys live in the button ID, so it keeps working after a restart."""
    script = ''  # data/gamma.ahk, set by register_info

    def __init__(self, action: str, toggle: str, reset: str, lang: str = 'en'):
        copy = action == 'copy'
        super().__init__(ui.Button(label=t(lang, f'gamma.button.{action}'), emoji='📋' if copy else '⬇️',
                                   style=discord.ButtonStyle.success if copy else discord.ButtonStyle.primary,
                                   custom_id=f'gamma:{action}:{toggle}:{reset}'))
        self.action, self.toggle, self.reset = action, toggle, reset

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(match['action'], match['toggle'], match['reset'])

    async def callback(self, interaction: discord.Interaction):
        lang = lang_for(interaction)
        if self.toggle not in GAMMA_KEY_LABELS or self.reset not in GAMMA_KEY_LABELS or not self.script:
            await interaction.response.send_message(t(lang, 'gamma.missing'), ephemeral=True)
            return
        code = gamma_script(self.script, self.toggle, self.reset)
        if self.action == 'download':
            file = discord.File(io.BytesIO(code.encode('utf-8')), filename='gamma.ahk')
            await interaction.response.send_message(t(lang, 'gamma.download'), file=file, ephemeral=True)
            return
        # Only to whoever clicked. Discord's copy button on each block copies just that part.
        blocks = code_blocks(code, 'ahk')
        await interaction.response.send_message(t(lang, 'gamma.copy', parts=len(blocks)), ephemeral=True)
        for block in blocks:
            await interaction.followup.send(block, ephemeral=True)


def gamma_view(lang: str, toggle: str, reset: str) -> ui.View:
    view = ui.View(timeout=None)
    view.add_item(GammaButton('download', toggle, reset, lang))
    view.add_item(GammaButton('copy', toggle, reset, lang))
    view.add_item(ui.Button(label=t(lang, 'gamma.button.ahk'), emoji='🌐', url=GAMMA_AHK_URL))
    return view


def author_embed(lang: str) -> discord.Embed:
    e = discord.Embed(title=t(lang, 'author.title'), description=t(lang, 'author.body', author=AUTHOR), color=YELLOW, url=REPO_URL)
    e.set_thumbnail(url=ICON.format('explosive.timed'))
    e.set_footer(text='RuxtBot')
    return e


def examples_layout(lang: str, command_ids: dict[str, int] | None = None) -> ui.LayoutView:
    """Copy-ready examples for every area, each next to a picture. Bare `/command` mentions become clickable."""
    view = ui.LayoutView()
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(f"# {t(lang, 'examples.title')}\n{t(lang, 'examples.intro')}"))
    box.add_item(ui.Separator())
    for key, icon in EXAMPLE_SECTIONS:
        box.add_item(ui.Section(ui.TextDisplay(linkify(t(lang, key), command_ids)), accessory=ui.Thumbnail(ICON.format(icon))))
    box.add_item(ui.Separator())
    box.add_item(ui.TextDisplay('-# ' + linkify(t(lang, 'examples.footer'), command_ids)))
    view.add_item(box)
    return view


def register_info(bot) -> None:
    def guide(name: str, description: str):
        """Register /<name>: posts data/<name>.md publicly, one message per part."""
        path = Path(bot.settings.data_path).with_name(f'{name}.md')
        chunks = split_sections(path.read_text(encoding='utf-8')) if path.exists() else []

        @bot.tree.command(name=name, description=description)
        async def command(interaction: discord.Interaction):
            lang = lang_for(interaction)
            if not chunks:
                await interaction.response.send_message(t(lang, f'{name}.missing'), ephemeral=True)
                return
            # Public: the guide is meant to be shared. Several messages because Discord allows 2000 characters each.
            none = discord.AllowedMentions.none()
            await interaction.response.send_message(chunks[0], allowed_mentions=none)
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, allowed_mentions=none)

    guide('binds', '⌨️ Useful Rust binds and console commands (F1), ready to copy')
    guide('cctv', '📹 CCTV camera codes for every monument, ready to copy')

    data = Path(bot.settings.data_path)
    guide_path, script_path = data.with_name('gamma.md'), data.with_name('gamma.ahk')
    gamma_chunks = split_sections(guide_path.read_text(encoding='utf-8')) if guide_path.exists() else []
    GammaButton.script = script_path.read_text(encoding='utf-8') if script_path.exists() else ''
    bot.add_dynamic_items(GammaButton)
    key_choices = [app_commands.Choice(name=label, value=key) for label, key in GAMMA_KEYS]

    @bot.tree.command(name='gamma', description='🌗 NVIDIA gamma script (AutoHotkey) to see at night, with your own key')
    @app_commands.describe(key='Key that turns the high gamma on and off (default F10)', reset='Emergency reset key, pressed with Shift (default F9)')
    @app_commands.choices(key=key_choices, reset=key_choices)
    async def gamma(interaction: discord.Interaction, key: str = 'F10', reset: str = 'F9'):
        lang = lang_for(interaction)
        if not gamma_chunks or not GammaButton.script:
            await interaction.response.send_message(t(lang, 'gamma.missing'), ephemeral=True)
            return
        keys = {'{toggle}': GAMMA_KEY_LABELS[key], '{reset}': f'Shift + {GAMMA_KEY_LABELS[reset]}'}
        chunks = [re.sub('{toggle}|{reset}', lambda m: keys[m[0]], c) for c in gamma_chunks]
        # Public like /binds; the buttons go under the last part.
        none, view = discord.AllowedMentions.none(), gamma_view(lang, key, reset)
        if len(chunks) == 1:
            await interaction.response.send_message(chunks[0], view=view, allowed_mentions=none)
            return
        await interaction.response.send_message(chunks[0], allowed_mentions=none)
        for chunk in chunks[1:-1]:
            await interaction.followup.send(chunk, allowed_mentions=none)
        await interaction.followup.send(chunks[-1], view=view, allowed_mentions=none)

    @bot.tree.command(name='author', description='👑 Who made RuxtBot')
    async def author(interaction: discord.Interaction):
        await interaction.response.send_message(embed=author_embed(lang_for(interaction)))

    @bot.tree.command(name='examples', description='📖 Examples of what the bot does and how to use it')
    async def examples(interaction: discord.Interaction):
        # Public on purpose: examples are meant to be seen (and copied) by everyone in the channel.
        await interaction.response.send_message(view=examples_layout(lang_for(interaction), getattr(bot, 'command_ids', None)))
