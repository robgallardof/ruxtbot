"""Shared UI pieces: brand colors, standard embeds and owner-locked views.

Every command goes through these helpers so the bot looks consistent
(same colors, same error style, same "only the opener can click" rule).
"""
from __future__ import annotations
import logging
import discord
from .i18n import lang_for, t

# RuxtBot palette.
YELLOW = 0xD5A522   # brand / neutral
GREEN = 0x2ECC71    # success / destroyed
ORANGE = 0xE67E22   # in progress / warnings
RED = 0xC0392B      # errors / bans
GREY = 0x95A5A6     # no data
STEAM_BLUE = 0x1B2838


def brand_embed(title: str | None = None, description: str | None = None, color: int = YELLOW) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def error_embed(message: str, hint: str | None = None, lang: str = 'en') -> discord.Embed:
    """Friendly error: what happened and, when possible, how to fix it."""
    e = discord.Embed(description=f'❌ {message}', color=RED)
    if hint:
        e.add_field(name=t(lang, 'hint.title'), value=hint, inline=False)
    return e


def success_embed(message: str) -> discord.Embed:
    return discord.Embed(description=f'✅ {message}', color=GREEN)


def progress_bar(pct: float, size: int = 10) -> str:
    """Text bar proportional to `pct` (0-100); always `size` characters wide."""
    filled = max(0, min(size, round(pct / 100 * size)))
    return '█' * filled + '░' * (size - filled)


def fmt_num(value: float) -> str:
    """1,234 for whole numbers, 120.5 otherwise."""
    if float(value).is_integer():
        return f'{int(value):,}'
    return f'{value:,.1f}'


async def reply(interaction: discord.Interaction, **kwargs) -> None:
    """Reply whether or not the interaction was already answered or deferred."""
    kwargs.setdefault('ephemeral', True)
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


class OwnerLock:
    """Mixin: only the user who opened a panel may use it; components disable themselves on timeout."""

    owner_id: int | None
    message: discord.Message | None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(t(lang_for(interaction), 'err.not_owner'), ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        # Keep the panel visible but inert, so nobody clicks a dead button.
        for item in self.walk_children():
            if hasattr(item, 'disabled') and not getattr(item, 'url', None):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logging.exception('UI callback failed', exc_info=error)
        lang = lang_for(interaction)
        await reply(interaction, embed=error_embed(t(lang, 'err.button'), t(lang, 'err.button.hint'), lang))


class OwnedView(OwnerLock, discord.ui.View):
    """Classic (embed + buttons) view with the owner lock."""

    def __init__(self, owner_id: int | None = None, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message = None


class OwnedLayout(OwnerLock, discord.ui.LayoutView):
    """Components V2 layout (images, sections, galleries) with the owner lock."""

    def __init__(self, owner_id: int | None = None, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message = None


async def swap(interaction: discord.Interaction, view, embed: discord.Embed | None = None) -> None:
    """Replace the current panel with another one, keeping the message reference for timeouts."""
    if hasattr(view, 'message'):
        view.message = interaction.message
    if isinstance(view, discord.ui.LayoutView):
        await interaction.response.edit_message(view=view)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)
