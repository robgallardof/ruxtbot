"""Player book: every player looked up in a guild can be picked again by name.

Commands that take a player autocomplete from this book, so after the first lookup nobody has to
paste an ID again. The book is per guild (per user in DMs), so names never leak between servers.
"""
from __future__ import annotations
import logging
import re
from discord import app_commands


def scope_of(interaction) -> int:
    """Guild ID, or the negative user ID in DMs."""
    return interaction.guild_id or -interaction.user.id


def choice_label(name: str | None, steamid: str | None, bm_id: str | None) -> str:
    ident = steamid or f'BM {bm_id}'
    return f'{name} · {ident}'[:100] if name else ident


def player_autocomplete(bot):
    async def complete(interaction, current: str):
        rows = bot.store.known_players(scope_of(interaction), current)
        choices = [app_commands.Choice(name=choice_label(name, steamid, bm_id), value=steamid or bm_id) for name, steamid, bm_id in rows]
        typed = current.strip()
        # A typed ID that is not in the book yet is offered as-is, so it can still be submitted with one tap.
        if re.fullmatch(r'[0-9]{1,17}', typed) and not any(c.value == typed for c in choices):
            label = f'SteamID {typed}' if len(typed) == 17 else f'BattleMetrics ID {typed}'
            choices.insert(0, app_commands.Choice(name=label, value=typed))
        return choices[:25]

    return complete


async def remember(bot, interaction, bm_id: str | None = None, steamid: str | None = None, name: str | None = None, profile: dict | None = None):
    """Store the player for autocomplete. Never fails the command that called it."""
    try:
        if bm_id and not name and not profile:
            # Already in the book with a name: just refresh it, no extra BattleMetrics request.
            name = bot.store.player_name(scope_of(interaction), bm_id)
        if bm_id and not name:
            profile = profile or await bot.bm.profile(bm_id)
            name = ((profile.get('data') or {}).get('attributes') or {}).get('name')
        bot.store.remember_player(scope_of(interaction), name, steamid, bm_id)
    except Exception as exc:
        logging.info('player book: could not remember %s/%s: %r', steamid, bm_id, exc)


def steam_of(value: str) -> str | None:
    """SteamID64 typed by the user, if the value is one (any format); None for BattleMetrics IDs and names."""
    from .who import parse_target
    try:
        return parse_target(value).steamid
    except ValueError:
        return None
