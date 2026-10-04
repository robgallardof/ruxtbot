"""Informational commands: /author, /examples, /binds and /cctv."""
from __future__ import annotations
from pathlib import Path
import discord
from discord import ui
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


def split_codes(text: str) -> list[str]:
    """One message per heading and one per code, so each code can be copied on its own.

    The intro (title and notes before the first `## `) is one message, each `## ` heading another,
    and every code block becomes a message holding only the bare code: copying it copies nothing else.
    Bold labels above the codes are for whoever edits the file and are not posted.
    """
    messages, intro, code, in_code = [], [], [], False
    for line in text.strip().split('\n'):
        if line.startswith('```'):
            if in_code and code:
                messages.append('\n'.join(code).strip())
            in_code, code = not in_code, []
        elif in_code:
            code.append(line)
        elif line.startswith('## '):
            if intro:
                messages.append('\n'.join(intro).strip())
                intro = []
            messages.append(line)
        elif not messages:
            intro.append(line)
    if intro:
        messages.append('\n'.join(intro).strip())
    return [m for m in messages if m]


# (section key, icon shortName) in display order; texts live in i18n.STRINGS.
EXAMPLE_SECTIONS = [
    ('examples.setup', 'computerstation'),
    ('examples.servers', 'map'),
    ('examples.players', 'door.hinged.toptier'),
    ('examples.admin', 'smart.alarm'),
    ('examples.raid', 'explosive.timed'),
    ('examples.craft', 'cupboard.tool'),
]


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
    def guide(name: str, description: str, split=split_sections):
        """Register /<name>: posts data/<name>.md publicly, one message per part."""
        path = Path(bot.settings.data_path).with_name(f'{name}.md')
        chunks = split(path.read_text(encoding='utf-8')) if path.exists() else []

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
    guide('cctv', '📹 CCTV camera codes for every monument, ready to copy', split_codes)

    @bot.tree.command(name='author', description='👑 Who made RuxtBot')
    async def author(interaction: discord.Interaction):
        await interaction.response.send_message(embed=author_embed(lang_for(interaction)))

    @bot.tree.command(name='examples', description='📖 Examples of what the bot does and how to use it')
    async def examples(interaction: discord.Interaction):
        # Public on purpose: examples are meant to be seen (and copied) by everyone in the channel.
        await interaction.response.send_message(view=examples_layout(lang_for(interaction), getattr(bot, 'command_ids', None)))
