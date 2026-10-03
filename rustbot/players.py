"""Player book: every player looked up in a guild can be picked again by name.

Commands that take a player autocomplete from this book, so after the first lookup nobody has to
paste an ID again. The book is per guild (per user in DMs), so names never leak between servers.
"""
from __future__ import annotations
import logging
import re
import discord
from discord import app_commands
from .i18n import t
from .ui import YELLOW, OwnedView, error_embed, private_reply

# What an explicit identifier looks like; anything else is treated as a name to look up in the book.
ID_LIKE = re.compile(r'^\s*(?:[0-9]{1,17}|STEAM_[0-5]:[01]:\d+|\[?U:1:\d+\]?|<?https?://\S+>?)\s*$', re.I)


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


async def resolve_player(bot, interaction, value: str | None) -> str:
    """BattleMetrics ID for what the user typed: a name from the book, a SteamID (cached, quick-match,
    then same-name profiles that list that SteamID) or a BattleMetrics ID."""
    value = expand(bot, interaction, value) or ''
    steamid = steam_of(value)
    if steamid and (linked := bot.store.bm_for_steam(scope_of(interaction), steamid)):
        return linked
    try:
        return await bot.bm.resolve_player(value)
    except ValueError as exc:
        if str(exc) not in ('identity.permission', 'identity.missing') or not steamid:
            raise
        try:
            name = (await bot.who.steam_profile(steamid)).get('name')
            if found := await bot.bm.verify_by_name(steamid, name):
                return found
        except Exception as fallback:
            logging.info('player plan B failed for %s: %r', steamid, fallback)
        raise


def looks_like_id(value: str | None) -> bool:
    return bool(ID_LIKE.match(value or ''))


def expand(bot, interaction, value: str | None) -> str | None:
    """A typed name becomes the ID of the matching player in the book (exact name first, else a single partial match).

    IDs and links pass through untouched; an unknown or ambiguous name is returned as typed.
    """
    if not value or looks_like_id(value):
        return value
    typed = value.strip()
    rows = bot.store.known_players(scope_of(interaction), typed, limit=50)
    exact = [r for r in rows if (r[0] or '').casefold() == typed.casefold()]
    refs = {steamid or bm_id for _, steamid, bm_id in (exact or rows)}
    return refs.pop() if len(refs) == 1 else value


def esc(value) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))[:60]


class AskModal(discord.ui.Modal):
    """One-field form; the answer goes to `on_value(interaction, text)`."""

    def __init__(self, title: str, label: str, placeholder: str, on_value):
        super().__init__(title=title[:45])
        self.field = discord.ui.TextInput(label=label[:45], placeholder=placeholder[:100], min_length=2, max_length=100)
        self.add_item(self.field)
        self.on_value = on_value

    async def on_submit(self, interaction):
        await self.on_value(interaction, self.field.value.strip())


def search_button(bot, lang: str, query: str | None = None) -> discord.ui.Button:
    """🔎 Search «name» on BattleMetrics in one click; without a usable name it asks for one."""
    async def find(interaction, name):
        await bot.tree.get_command('findplayer').callback(interaction, name=name[:64])

    if query and 2 <= len(query.strip()) <= 64:
        button = discord.ui.Button(label=t(lang, 'player.search_for', q=query.strip()[:40]), emoji='🔎', style=discord.ButtonStyle.primary)

        async def run(interaction):
            await find(interaction, query.strip())
    else:
        button = discord.ui.Button(label=t(lang, 'player.search'), emoji='🔎', style=discord.ButtonStyle.primary)

        async def run(interaction):
            await interaction.response.send_modal(AskModal(t(lang, 'player.search'), t(lang, 'player.ask_name'), 'KingGallardo', find))
    button.callback = run
    return button


async def player_error(bot, interaction, lang: str, exc: Exception | str, query: str | None = None, share: bool = False):
    """Friendly error for a player that could not be resolved, with a button to search it by name."""
    key = exc if isinstance(exc, str) else (str(exc) if isinstance(exc, ValueError) and str(exc).startswith('identity.')
                                          else 'identity.input' if isinstance(exc, ValueError) else 'identity.unavailable')
    if key == 'identity.input' and query and not looks_like_id(query):
        key = 'identity.name'
    view = None
    steamid = steam_of(query) if query else None
    if key in ('identity.missing', 'identity.permission') and steamid:
        # The SteamID is fine, BattleMetrics just won't map it: link it once from the profile.
        key = 'identity.link'
        view = OwnedView(interaction.user.id)
        link = discord.ui.Button(label=t(lang, 'identity.link.button'), emoji='🔗', style=discord.ButtonStyle.primary)

        async def open_profile(i):
            await bot.tree.get_command('who').callback(i, player=steamid)
        link.callback = open_profile
        view.add_item(link)
    elif key != 'identity.unavailable' and bot.bm.token:
        view = OwnedView(interaction.user.id)
        view.add_item(search_button(bot, lang, query if query and not looks_like_id(query) else None))
    embed = error_embed(t(lang, key, q=esc(query or '')), t(lang, 'identity.hint'), lang)
    await private_reply(interaction, share, embed=embed, **({'view': view} if view else {}))


def hub(bot, interaction, lang: str) -> tuple[discord.Embed, OwnedView]:
    """Panel for /who with no player: recent players, search by name, or type an ID."""
    rows = bot.store.known_players(scope_of(interaction), limit=25)
    view = OwnedView(interaction.user.id)

    async def who(i, value):
        await bot.tree.get_command('who').callback(i, player=value)

    if rows:
        select = discord.ui.Select(placeholder=t(lang, 'hub.recent'), options=[
            discord.SelectOption(label=(name or steamid or bm_id)[:100], value=steamid or bm_id,
                                 description=(f'SteamID {steamid}' if steamid else f'BattleMetrics ID {bm_id}')[:100], emoji='🕵️')
            for name, steamid, bm_id in rows])

        async def picked(i):
            await who(i, i.data['values'][0])
        select.callback = picked
        view.add_item(select)
    if bot.bm.token:
        view.add_item(search_button(bot, lang))
    ask = discord.ui.Button(label=t(lang, 'hub.enter_id'), emoji='🆔', style=discord.ButtonStyle.secondary)

    async def ask_id(i):
        await i.response.send_modal(AskModal(t(lang, 'hub.enter_id'), t(lang, 'hub.id_label'), '76561198… / 1128280744', who))
    ask.callback = ask_id
    view.add_item(ask)
    body = t(lang, 'hub.body') if rows else t(lang, 'hub.body') + '\n\n' + t(lang, 'hub.empty')
    embed = discord.Embed(title=t(lang, 'hub.title'), description=body, color=YELLOW)
    return embed, view
