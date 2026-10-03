"""Base maintenance: /upkeep (daily Tool Cupboard cost) and /decay (time until a grade decays).

Rules (checked 2026-10-03):
- Upkeep per 24 h is a fraction of each block's build cost. The fraction grows with base size:
  first 15 blocks 10 %, next 50 15 %, next 125 20 %, every block after that 33.3 %
  (a 100-piece base pays 16 %).
- Breach and Clear (3 September 2026) adds a group tax on top, counting players authed on the TC or
  any code lock (including guests, and anyone deauthed in the last 24 h): first 4 players free,
  next 6 add 2 % each, every player after adds 4 %, capped at 300 %.
- Full decay from full health: twig 1 h, wood 3 h, stone 5 h, sheet metal 8 h, armored 12 h
  (Facepunch wiki, "Tool Cupboard, decay and building privilege").
Servers can change all of this with the decay convars, so replies say these are vanilla values.
"""
from __future__ import annotations
import math
import discord
from discord import app_commands
from .i18n import lang_for, t
from .ui import ORANGE, YELLOW, error_embed, fmt_num, progress_bar

ICON = 'https://wiki.rustclash.com/img/items180/{}.png'

# (blocks in this bracket, fraction of build cost per day); blocks beyond the last bracket pay the final rate.
UPKEEP_BRACKETS = [(15, 0.10), (50, 0.15), (125, 0.20)]
UPKEEP_REST = 1 / 3

# grade -> (resource shortName, cost of a full block such as a foundation or wall)
GRADES = {
    'wood': ('wood', 200),
    'stone': ('stones', 300),
    'metal': ('metal.fragments', 200),
    'hqm': ('metal.refined', 25),
}
RESOURCE_KEYS = {'wood': 'base.wood', 'stones': 'base.stone', 'metal.fragments': 'base.metal', 'metal.refined': 'base.hqm'}

# grade -> hours to decay from full health.
DECAY_HOURS = {'twig': 1, 'wood': 3, 'stone': 5, 'metal': 8, 'hqm': 12}
DECAY_ICONS = {'twig': 'wood', 'wood': 'wood', 'stone': 'stones', 'metal': 'metal.fragments', 'hqm': 'metal.refined'}


def upkeep_fraction(blocks: int) -> float:
    """Blended daily fraction of build cost for a base with `blocks` building blocks."""
    if blocks <= 0:
        return 0.0
    paid, left = 0.0, blocks
    for size, rate in UPKEEP_BRACKETS:
        taken = min(left, size)
        paid += taken * rate
        left -= taken
    paid += left * UPKEEP_REST
    return paid / blocks


def group_tax(players: int) -> float:
    """Extra upkeep (0.2 = +20 %) for the number of players counted on the base."""
    extra = max(0, players - 4)
    return min(3.0, min(extra, 6) * 0.02 + max(0, extra - 6) * 0.04)


def upkeep(counts: dict[str, tuple[int, int]], players: int = 1, multiplier: float = 1.0) -> dict:
    """counts: grade -> (full blocks, half blocks). `multiplier` is the server's upkeep setting (1 = vanilla).
    Returns blocks, rates and daily cost per resource."""
    blocks = sum(full + half for full, half in counts.values())
    rate, tax = upkeep_fraction(blocks), group_tax(players)
    daily: dict[str, float] = {}
    for grade, (full, half) in counts.items():
        resource, cost = GRADES[grade]
        build = (full + half / 2) * cost
        daily[resource] = daily.get(resource, 0) + build * rate * (1 + tax) * multiplier
    return {'blocks': blocks, 'rate': rate, 'tax': tax, 'multiplier': multiplier, 'daily': {k: math.ceil(v) for k, v in daily.items() if v}}


def upkeep_embed(lang: str, result: dict, players: int, server: str | None = None) -> discord.Embed:
    e = discord.Embed(title=t(lang, 'upkeep.title', n=result['blocks']), color=YELLOW)
    lines = [t(lang, 'upkeep.rate', pct=fmt_num(round(result['rate'] * 100, 1)))]
    if result['tax']:
        lines.append(t(lang, 'upkeep.tax', pct=fmt_num(round(result['tax'] * 100, 1)), n=players))
    else:
        lines.append(t(lang, 'upkeep.no_tax', n=players))
    if server:
        lines.append(t(lang, 'upkeep.server', server=server, n=fmt_num(result.get('multiplier', 1))))
    e.description = '\n'.join(lines)
    for resource, amount in result['daily'].items():
        e.add_field(name=t(lang, RESOURCE_KEYS[resource]), value=t(lang, 'upkeep.amounts', day=amount, week=amount * 7), inline=True)
    e.set_thumbnail(url=ICON.format('cupboard.tool'))
    e.set_footer(text=t(lang, 'upkeep.footer'))
    return e


def decay_embed(lang: str, grade: str | None, health: int, scale: float = 1.0, server: str | None = None) -> discord.Embed:
    """`scale`: the server's decay multiplier (2 = decays twice as fast, so times are halved; 0 = no decay)."""
    e = discord.Embed(title=t(lang, 'decay.title'), color=ORANGE)
    if scale <= 0:
        e.description = t(lang, 'decay.off', server=server or '?')
        e.set_footer(text=t(lang, 'decay.footer'))
        return e
    if grade:
        hours = DECAY_HOURS[grade] * health / 100 / scale
        e.description = t(lang, 'decay.one', grade=t(lang, 'grade.' + grade), pct=health, time=duration(hours)) + f'\n`{progress_bar(health)}` {health}%'
        e.set_thumbnail(url=ICON.format(DECAY_ICONS[grade]))
    else:
        e.description = '\n'.join(f"**{t(lang, 'grade.' + g)}** · {duration(h * health / 100 / scale)}" for g, h in DECAY_HOURS.items())
        if health != 100:
            e.description = t(lang, 'decay.from', pct=health) + '\n' + e.description
    if server:
        e.description += '\n-# ' + t(lang, 'decay.server', server=server, n=fmt_num(scale))
    e.add_field(name=t(lang, 'decay.how'), value=t(lang, 'decay.how.value'), inline=False)
    e.set_footer(text=t(lang, 'decay.footer'))
    return e


def duration(hours: float) -> str:
    minutes = round(hours * 60)
    return f'{minutes // 60} h {minutes % 60:02d} min' if minutes >= 60 else f'{minutes} min'


async def server_settings(bot, value: str | None) -> tuple[str | None, dict]:
    """(server name, rust_settings) for an optional server option; ({}) when missing or unavailable."""
    if not value:
        return None, {}
    sid = bot.directory.resolve(value)
    attrs = (await bot.bm.server(sid)).get('attributes') or {}
    cfg = (attrs.get('details') or {}).get('rust_settings')
    return attrs.get('name', sid), cfg if isinstance(cfg, dict) else {}


def register_base(bot) -> None:
    @bot.tree.command(name='upkeep', description='🏠 Daily Tool Cupboard upkeep for your base')
    @app_commands.describe(stone='Stone full pieces (foundations, walls, doorways, frames, stairs, roofs)', stone_half='Stone half pieces (floors, triangles, half/low walls)',
                           metal='Sheet metal full pieces', metal_half='Sheet metal half pieces', hqm='Armored full pieces', hqm_half='Armored half pieces',
                           wood='Wood full pieces', wood_half='Wood half pieces', players='Players authed on the TC or a code lock (guests count)',
                           server="Use this server's upkeep multiplier (optional)", share='Publish the result in this channel')
    @app_commands.autocomplete(server=bot.server_choices)
    async def upkeep_command(interaction: discord.Interaction, stone: app_commands.Range[int, 0, 5000] = 0, stone_half: app_commands.Range[int, 0, 5000] = 0,
                             metal: app_commands.Range[int, 0, 5000] = 0, metal_half: app_commands.Range[int, 0, 5000] = 0,
                             hqm: app_commands.Range[int, 0, 5000] = 0, hqm_half: app_commands.Range[int, 0, 5000] = 0,
                             wood: app_commands.Range[int, 0, 5000] = 0, wood_half: app_commands.Range[int, 0, 5000] = 0,
                             players: app_commands.Range[int, 1, 200] = 1, server: str | None = None, share: bool = False):
        lang = lang_for(interaction)
        counts = {g: c for g, c in {'stone': (stone, stone_half), 'metal': (metal, metal_half), 'hqm': (hqm, hqm_half), 'wood': (wood, wood_half)}.items() if any(c)}
        if not counts:
            await interaction.response.send_message(embed=error_embed(t(lang, 'upkeep.empty'), t(lang, 'upkeep.empty.hint'), lang), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=not share)
        try:
            name, cfg = await server_settings(bot, server)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
            return
        multiplier = float(cfg.get('upkeep', 1) or 0) if 'upkeep' in cfg else 1.0
        await interaction.followup.send(embed=upkeep_embed(lang, upkeep(counts, players, multiplier), players, name), ephemeral=not share)

    @bot.tree.command(name='decay', description='⏳ How long until a building grade fully decays')
    @app_commands.describe(grade='Building grade (empty = all)', health='Current health in percent', server="Use this server's decay multiplier (optional)")
    @app_commands.choices(grade=[app_commands.Choice(name=n, value=v) for n, v in
                                 (('Twig', 'twig'), ('Wood', 'wood'), ('Stone', 'stone'), ('Sheet metal', 'metal'), ('Armored', 'hqm'))])
    @app_commands.autocomplete(server=bot.server_choices)
    async def decay(interaction: discord.Interaction, grade: str | None = None, health: app_commands.Range[int, 1, 100] = 100, server: str | None = None):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        try:
            name, cfg = await server_settings(bot, server)
        except Exception:
            await interaction.followup.send(embed=error_embed(t(lang, 'server.pick'), lang=lang), ephemeral=True)
            return
        scale = float(cfg['decay']) if isinstance(cfg.get('decay'), (int, float)) else 1.0
        await interaction.followup.send(embed=decay_embed(lang, grade if grade in DECAY_HOURS else None, health, scale, name), ephemeral=True)
