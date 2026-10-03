"""Raid panels and commands.

Panels are Components V2 layouts so they can show pictures next to the text:
    home_layout      categories, each with an "Open" button
    category_layout  picture gallery of every target in a category + target picker
    target_layout    simulator: target and explosive pictures, HP bar, costs, controls
    builder_layout   base calculator for several targets (/raidcalc)
    budget_layout    what a sulfur budget buys (/raidbudget)

Every panel is rebuilt from scratch on each click (state lives in the callback closures),
which keeps the code simple and makes stale panels impossible.
"""
from __future__ import annotations
import discord
from discord import app_commands, ui
from .i18n import lang_for, t
from .raid_data import BEST, CATEGORY_EMOJI, METHOD_EMOJI, RaidData
from .ui import GREEN, ORANGE, YELLOW, OwnedLayout, error_embed, fmt_num, progress_bar, swap

MAX_GALLERY = 10  # Discord limit per media gallery


# ───────────────────────────── Text helpers ─────────────────────────────

def explosive_name(data: RaidData, method: str) -> str:
    return data.explosives[method]['name']


def method_label(data: RaidData, method: str) -> str:
    return f"{METHOD_EMOJI.get(method, '💥')} {explosive_name(data, method)}"


def short_cost(data: RaidData, lang: str, method: str, amount: int) -> str:
    """'6,250 sulfur' / 'no sulfur' / 'cost not verified'."""
    cost = data.cost(method, amount)
    if cost is None:
        return t(lang, 'raid.unknown_cost')
    return t(lang, 'raid.sulfur_short', n=cost['sulfur']) if cost['sulfur'] else t(lang, 'raid.no_sulfur')


def group_tag(lang: str, group: str) -> str:
    return f" *({t(lang, 'group.' + group)})*" if group in ('siege', 'fire') else ''


def best_line(data: RaidData, lang: str, key: str, side: str = 'hard') -> str:
    best = data.best(key, side)
    if not best:
        return ''
    amount = data.amount(key, best[0], side)
    return f"🏆 {METHOD_EMOJI.get(best[0], '💥')} ×{amount:,} ({best[1]:,} 🧪)"


def footer(data: RaidData, lang: str, key: str | None = None) -> ui.TextDisplay:
    source = 'Rustly' if key and data.targets[key]['source'] == 'rustly' else 'RustClash' if key else 'Rustly · RustClash'
    return ui.TextDisplay('-# ' + t(lang, 'raid.footer', source=source, version=data.version))


def button(label: str, callback, *, emoji: str | None = None, style=discord.ButtonStyle.secondary, disabled: bool = False) -> ui.Button:
    b = ui.Button(label=label, emoji=emoji, style=style, disabled=disabled)
    b.callback = callback
    return b


def select(placeholder: str, options: list[discord.SelectOption], callback) -> ui.Select:
    s = ui.Select(placeholder=placeholder, options=options[:25])
    s.callback = callback
    return s


# ───────────────────────────── Panels ─────────────────────────────

def home_layout(data: RaidData, lang: str, owner_id: int | None = None) -> OwnedLayout:
    view = OwnedLayout(owner_id)
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(f"# {t(lang, 'raid.home.title')}\n{t(lang, 'raid.home.intro')}"))
    box.add_item(ui.Separator())
    for category in data.categories():
        keys = data.in_category(category)
        hps = [data.targets[k]['hp'] for k in keys]
        sample = ', '.join(data.targets[k]['name'] for k in keys[:4]) + ('…' if len(keys) > 4 else '')

        async def open_category(interaction, category=category):
            await swap(interaction, category_layout(data, lang_for(interaction), category, view.owner_id))

        box.add_item(ui.Section(
            ui.TextDisplay(f"### {CATEGORY_EMOJI[category]} {t(lang, 'cat.' + category)}\n"
                           f"{t(lang, 'cat.count', n=len(keys), min=min(hps), max=max(hps))}\n-# {sample}"),
            accessory=button(t(lang, 'raid.open'), open_category, emoji='➡️', style=discord.ButtonStyle.primary)))
    box.add_item(ui.Separator())

    async def open_calc(interaction):
        await swap(interaction, builder_layout(data, lang_for(interaction), {}, BEST, 'doors', view.owner_id))

    box.add_item(ui.ActionRow(button(t(lang, 'raid.calc.button'), open_calc, emoji='🧮', style=discord.ButtonStyle.success)))
    box.add_item(ui.TextDisplay(f"-# {t(lang, 'raid.budget.tip')} · {data.version}"))
    view.add_item(box)
    return view


def category_layout(data: RaidData, lang: str, category: str, owner_id: int | None = None) -> OwnedLayout:
    view = OwnedLayout(owner_id)
    keys = data.in_category(category)
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(f"## {CATEGORY_EMOJI[category]} {t(lang, 'cat.' + category)}"))

    # Picture gallery so players recognise what they are looking at in game.
    pictured = [k for k in keys if data.targets[k].get('icon')][:MAX_GALLERY]
    if pictured:
        box.add_item(ui.MediaGallery(*[discord.MediaGalleryItem(data.targets[k]['icon'], description=data.targets[k]['name'])
                                       for k in pictured]))
    lines = [f"**{data.targets[k]['name']}** · {data.targets[k]['hp']:,} HP · {best_line(data, lang, k)}" for k in keys]
    box.add_item(ui.TextDisplay('\n'.join(lines)))

    async def pick(interaction):
        key = interaction.data['values'][0]
        await swap(interaction, target_layout(data, lang_for(interaction), key, owner_id=view.owner_id))

    options = []
    for k in keys:
        best = data.best(k)
        desc = f"{data.targets[k]['hp']:,} HP" + (f" · {t(lang, 'raid.cheapest')}: {explosive_name(data, best[0])}" if best else '')
        options.append(discord.SelectOption(label=data.targets[k]['name'][:100], value=k, description=desc[:100],
                                            emoji=CATEGORY_EMOJI[category]))
    box.add_item(ui.ActionRow(select(t(lang, 'raid.pick_target'), options, pick)))

    async def back(interaction):
        await swap(interaction, home_layout(data, lang_for(interaction), view.owner_id))

    box.add_item(ui.ActionRow(button(t(lang, 'common.back'), back, emoji='⬅️')))
    box.add_item(footer(data, lang))
    view.add_item(box)
    return view


def target_layout(data: RaidData, lang: str, key: str, side: str = 'hard', method: str | None = None,
                  used: int = 0, owner_id: int | None = None) -> OwnedLayout:
    """Raid simulator for one target: pictures, HP left, cost and controls."""
    view = OwnedLayout(owner_id)
    target = data.targets[key]
    method = method or (data.best(key, side) or (next(iter(target[side])),))[0]
    amount = data.amount(key, method, side)
    used = max(0, min(used, amount))
    hp = target['hp']
    remaining = hp * (1 - used / amount)
    pct = round(100 * remaining / hp)
    destroyed = used >= amount
    state = 'raid.state.destroyed' if destroyed else ('raid.state.intact' if used == 0 else 'raid.state.damaged')
    group = data.explosives[method]['group']

    box = ui.Container(accent_colour=GREEN if destroyed else (YELLOW if pct > 50 else ORANGE))
    box.add_item(ui.Section(
        ui.TextDisplay(f"## {CATEGORY_EMOJI[target['category']]} [{target['name']}]({target['url']})\n"
                       f"-# {t(lang, 'cat.' + target['category'])} · {hp:,} HP · {t(lang, 'side.' + side)}"),
        accessory=ui.Thumbnail(data.icon(key), description=target['name'])))
    box.add_item(ui.Separator())
    box.add_item(ui.Section(
        ui.TextDisplay(f"### {t(lang, state)}\n{t(lang, 'raid.hp_left', left=fmt_num(round(remaining, 1)), hp=hp, bar=progress_bar(pct), pct=pct)}\n"
                       f"**{method_label(data, method)}**{group_tag(lang, group)} — {t(lang, 'raid.used', used=used, amount=amount, left=amount - used)}"),
        accessory=ui.Thumbnail(data.explosives[method]['icon'], description=explosive_name(data, method))))

    # Cost of the whole method, cheapest alternative and caveats.
    cost = data.cost(method, amount)
    lines = [t(lang, 'raid.cost.unknown') if cost is None else
             t(lang, 'raid.cost', sulfur=cost['sulfur'], charcoal=cost['charcoal'], frags=cost['metalFragments']) if cost['sulfur'] else
             t(lang, 'raid.cost.free')]
    best = data.best(key, side)
    if best and best[0] == method:
        lines.append(t(lang, 'raid.cheapest.is'))
    elif best:
        lines.append(t(lang, 'raid.cheapest.other', name=explosive_name(data, best[0]), amount=data.amount(key, best[0], side), sulfur=best[1]))
    if group in ('siege', 'fire'):
        lines.append(t(lang, 'raid.warn.' + group))
    box.add_item(ui.TextDisplay('\n'.join(lines)))
    box.add_item(ui.Separator())

    def redraw(**changes):
        async def callback(interaction):
            state = {'side': side, 'method': method, 'used': used} | changes
            await swap(interaction, target_layout(data, lang_for(interaction), key, owner_id=view.owner_id, **state))
        return callback

    # Row 1: method picker, cheapest first, with each method's cost.
    async def pick_method(interaction):
        await redraw(method=interaction.data['values'][0], used=0)(interaction)

    options = [discord.SelectOption(label=explosive_name(data, r.method)[:100], value=r.method, emoji=METHOD_EMOJI.get(r.method, '💥'),
                                    description=(('🏆 ' if best and r.method == best[0] else '') +
                                                 t(lang, 'raid.method.option', amount=r.amount, cost=short_cost(data, lang, r.method, r.amount)))[:100],
                                    default=r.method == method)
               for r in data.rows(key, side)]
    box.add_item(ui.ActionRow(select(t(lang, 'raid.method.placeholder'), options, pick_method)))

    # Row 2: simulation controls.
    box.add_item(ui.ActionRow(
        button(t(lang, 'raid.btn.destroyed' if destroyed else 'raid.btn.apply'), redraw(used=used + 1), emoji='💥',
               style=discord.ButtonStyle.success if destroyed else discord.ButtonStyle.danger, disabled=destroyed),
        button(t(lang, 'raid.btn.undo'), redraw(used=used - 1), emoji='↩️', disabled=used == 0),
        button(t(lang, 'raid.btn.complete'), redraw(used=amount), emoji='⏭️', style=discord.ButtonStyle.primary, disabled=destroyed),
        button(t(lang, 'raid.btn.reset'), redraw(used=0), emoji='🔄', disabled=used == 0)))

    # Row 3: side toggle (walls/floors), compare, back to the category.
    async def compare(interaction):
        await interaction.response.send_message(view=compare_layout(data, lang_for(interaction), key, side), ephemeral=True)

    async def back(interaction):
        await swap(interaction, category_layout(data, lang_for(interaction), target['category'], view.owner_id))

    extras = []
    if len(data.sides(key)) > 1:
        other = 'soft' if side == 'hard' else 'hard'
        extras.append(button(t(lang, 'raid.btn.side', side=t(lang, 'side.' + other)), redraw(side=other, method=None, used=0), emoji='🔃'))
    extras += [button(t(lang, 'raid.btn.compare'), compare, emoji='📊'), button(t(lang, 'common.back'), back, emoji='⬅️')]
    box.add_item(ui.ActionRow(*extras))
    box.add_item(footer(data, lang, key))
    view.add_item(box)
    return view


def compare_lines(data: RaidData, lang: str, key: str, side: str = 'hard') -> list[str]:
    best = data.best(key, side)
    return [f"{'🏆 ' if best and r.method == best[0] else ''}{METHOD_EMOJI.get(r.method, '💥')} **{explosive_name(data, r.method)}**"
            f"{group_tag(lang, r.group)}: ×{r.amount:,} · {short_cost(data, lang, r.method, r.amount)}"
            for r in data.rows(key, side)]


def compare_layout(data: RaidData, lang: str, key: str, side: str = 'hard') -> ui.LayoutView:
    target = data.targets[key]
    view = ui.LayoutView()
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.Section(
        ui.TextDisplay(f"## {t(lang, 'raid.compare.title', name=target['name'], side=t(lang, 'side.' + side))}"),
        accessory=ui.Thumbnail(data.icon(key))))
    box.add_item(ui.TextDisplay('\n'.join(compare_lines(data, lang, key, side))))
    box.add_item(ui.TextDisplay('-# ' + t(lang, 'raid.compare.footer')))
    view.add_item(box)
    return view


def plan_items(data: RaidData, lang: str, entries: dict[str, int], method: str = BEST) -> list[ui.Item]:
    """Header, target list, totals and one picture per explosive. Shared by the calculator and its shared copy."""
    mode = t(lang, 'calc.method.best') if method == BEST else method_label(data, method)
    items: list[ui.Item] = [ui.TextDisplay(f"## {t(lang, 'calc.title')}\n{t(lang, 'calc.method', method=mode)}"), ui.Separator()]
    if not entries:
        return items + [ui.TextDisplay(t(lang, 'calc.empty'))]
    plan = data.plan(entries, method)
    lines = []
    for key, qty, chosen, units in plan['rows']:
        name = data.targets[key]['name']
        lines.append(t(lang, 'calc.row.missing', qty=qty, name=name) if chosen is None else
                     t(lang, 'calc.row', qty=qty, name=name, amount=units, emoji=METHOD_EMOJI.get(chosen, '💥')))
    items.append(ui.TextDisplay(t(lang, 'calc.targets') + '\n' + '\n'.join(lines)))
    totals = plan['totals']
    summary = t(lang, 'raid.cost', sulfur=totals.get('sulfur', 0), charcoal=totals.get('charcoal', 0), frags=totals.get('metalFragments', 0))
    if plan['unknown']:
        summary += '\n' + t(lang, 'calc.unknown')
    items.append(ui.TextDisplay(t(lang, 'calc.totals') + '\n' + summary))
    # One picture per explosive type needed (at most 4 to stay within Discord's 40-component budget).
    for m, n in plan['units'].most_common(4):
        items.append(ui.Section(ui.TextDisplay(t(lang, 'calc.explosive', n=n, name=explosive_name(data, m))),
                                accessory=ui.Thumbnail(data.explosives[m]['icon'])))
    return items


def builder_layout(data: RaidData, lang: str, entries: dict[str, int], method: str = BEST, category: str = 'doors',
                   owner_id: int | None = None) -> OwnedLayout:
    """Base calculator: targets -> amount, one global method (or the cheapest per target)."""
    view = OwnedLayout(owner_id, timeout=600)
    box = ui.Container(accent_colour=YELLOW)
    for item in plan_items(data, lang, entries, method):
        box.add_item(item)
    box.add_item(ui.Separator())

    def redraw(entries=entries, method=method, category=category):
        return builder_layout(data, lang, entries, method, category, view.owner_id)

    async def pick_category(interaction):
        await swap(interaction, redraw(category=interaction.data['values'][0]))

    async def add_target(interaction):
        key = interaction.data['values'][0]
        await swap(interaction, redraw(entries=entries | {key: entries.get(key, 0) + 1}))

    async def pick_method(interaction):
        await swap(interaction, redraw(method=interaction.data['values'][0]))

    async def remove_target(interaction):
        key = interaction.data['values'][0]
        left = dict(entries)
        left[key] -= 1
        if left[key] <= 0:
            del left[key]
        await swap(interaction, redraw(entries=left))

    async def clear(interaction):
        await swap(interaction, redraw(entries={}))

    async def share(interaction):
        # Post a read-only copy (no controls) for the whole channel.
        copy = ui.LayoutView()
        snapshot = ui.Container(accent_colour=YELLOW)
        snapshot.add_item(ui.TextDisplay('-# ' + t(lang, 'calc.shared_by', user=discord.utils.escape_markdown(interaction.user.display_name))))
        for item in plan_items(data, lang, entries, method):
            snapshot.add_item(item)
        copy.add_item(snapshot)
        await interaction.response.send_message(view=copy)

    cat_label = t(lang, 'cat.' + category)
    box.add_item(ui.ActionRow(select(t(lang, 'calc.category', category=cat_label), [
        discord.SelectOption(label=t(lang, 'cat.' + c), value=c, emoji=CATEGORY_EMOJI[c], default=c == category) for c in data.categories()],
        pick_category)))
    box.add_item(ui.ActionRow(select(t(lang, 'calc.add', category=cat_label), [
        discord.SelectOption(label=data.targets[k]['name'][:100], value=k, emoji=CATEGORY_EMOJI[category],
                             description=f"{data.targets[k]['hp']:,} HP" + (f" · {t(lang, 'calc.in_plan', n=entries[k])}" if k in entries else ''))
        for k in data.in_category(category)], add_target)))
    methods = sorted({m for k in data.targets for m in data.targets[k]['hard']},
                     key=lambda m: ((data.explosives[m]['cost'] or {}).get('sulfur') or 1e9))
    box.add_item(ui.ActionRow(select(t(lang, 'raid.method.placeholder'), [
        discord.SelectOption(label=t(lang, 'calc.method.best'), value=BEST, emoji='🏆', default=method == BEST)] + [
        discord.SelectOption(label=explosive_name(data, m)[:100], value=m, emoji=METHOD_EMOJI.get(m, '💥'), default=method == m)
        for m in methods[:24]], pick_method)))
    if entries:
        box.add_item(ui.ActionRow(select(t(lang, 'calc.remove'), [
            discord.SelectOption(label=data.targets[k]['name'][:100], value=k, description=t(lang, 'calc.in_plan', n=n))
            for k, n in entries.items()], remove_target)))
    box.add_item(ui.ActionRow(
        button(t(lang, 'calc.clear'), clear, emoji='🗑️', disabled=not entries),
        button(t(lang, 'calc.share'), share, emoji='📤', style=discord.ButtonStyle.primary, disabled=not entries)))
    box.add_item(ui.TextDisplay('-# ' + t(lang, 'calc.footer', version=data.version)))
    view.add_item(box)
    return view


def budget_layout(data: RaidData, lang: str, sulfur: int) -> ui.LayoutView:
    info = data.budget(sulfur)
    view = ui.LayoutView()
    box = ui.Container(accent_colour=YELLOW)
    box.add_item(ui.TextDisplay(f"## {t(lang, 'budget.title', n=sulfur)}\n{t(lang, 'budget.intro')}"))
    crafts = [f"{METHOD_EMOJI.get(m, '💥')} **{n:,}** × {explosive_name(data, m)} · {fmt_num(per)}/u" for m, n, per in info['crafts'] if n]
    box.add_item(ui.TextDisplay(t(lang, 'budget.crafts') + '\n' + ('\n'.join(crafts) or t(lang, 'budget.none'))))
    # Most common raid targets first, so the list stays readable.
    kills = [f"{CATEGORY_EMOJI[data.targets[k]['category']]} **{n:,}** × {data.targets[k]['name']} · {METHOD_EMOJI.get(m, '💥')} ({cost:,}/u)"
             for k, n, m, cost in info['kills'] if data.targets[k]['category'] in ('doors', 'walls', 'floors')]
    box.add_item(ui.TextDisplay(t(lang, 'budget.kills') + '\n' + '\n'.join(kills)))
    box.add_item(ui.TextDisplay('-# ' + t(lang, 'budget.footer')))
    view.add_item(box)
    return view


# ───────────────────────────── Commands ─────────────────────────────

SIDE_CHOICES = [app_commands.Choice(name='Hard side', value='hard'), app_commands.Choice(name='Soft side', value='soft')]


def register_raid_commands(bot, data: RaidData):
    """Registers /raid, /raidcalc, /raidbudget, /raidcompare and /raidtools."""

    async def target_choices(interaction, current: str):
        return [app_commands.Choice(name=f"{data.targets[k]['name']} · {data.targets[k]['hp']:,} HP"[:100], value=k)
                for k in data.search(current)]

    async def method_choices(interaction, current: str):
        # With a target already chosen, only offer its methods, cheapest first, with their cost.
        lang = lang_for(interaction)
        key = data.find(getattr(interaction.namespace, 'target', None) or '')
        out = []
        if key:
            for r in data.rows(key):
                label = f"{explosive_name(data, r.method)} · ×{r.amount:,} · {short_cost(data, lang, r.method, r.amount)}"
                if current.casefold() in label.casefold():
                    out.append(app_commands.Choice(name=label[:100], value=r.method))
        else:
            out = [app_commands.Choice(name=explosive_name(data, m), value=m) for m in data.explosives
                   if current.casefold() in explosive_name(data, m).casefold()]
        return out[:25]

    async def unknown_target(interaction):
        lang = lang_for(interaction)
        await interaction.response.send_message(embed=error_embed(t(lang, 'raid.unknown_target'), t(lang, 'raid.unknown_target.hint'), lang), ephemeral=True)

    async def send_layout(interaction, view, ephemeral=False):
        # Keep the message on the view so it can disable itself when it expires.
        await interaction.response.send_message(view=view, ephemeral=ephemeral)
        try:
            view.message = await interaction.original_response()
        except (discord.HTTPException, AttributeError):
            pass

    @bot.tree.command(name='raid', description='💥 Raid planner with pictures: HP left, sulfur and cheapest method')
    @app_commands.describe(target='Target (optional): type and pick', method='Method (optional); default is the cheapest', side='Wall side')
    @app_commands.autocomplete(target=target_choices, method=method_choices)
    @app_commands.choices(side=SIDE_CHOICES)
    async def raid(interaction: discord.Interaction, target: str | None = None, method: str | None = None, side: str = 'hard'):
        lang = lang_for(interaction)
        if not target:
            await send_layout(interaction, home_layout(data, lang, interaction.user.id))
            return
        key = data.find(target)
        if not key:
            await unknown_target(interaction)
            return
        side = side if side in data.sides(key) else 'hard'
        if method and method not in data.targets[key][side]:
            await interaction.response.send_message(embed=error_embed(t(lang, 'raid.bad_method', name=data.targets[key]['name']),
                                                                      t(lang, 'raid.bad_method.hint'), lang), ephemeral=True)
            return
        await send_layout(interaction, target_layout(data, lang, key, side, method, owner_id=interaction.user.id))

    @bot.tree.command(name='raidcalc', description='🧮 Base calculator: add several targets, get explosives and sulfur')
    @app_commands.describe(target='First target (optional)', quantity='How many of that target', method='Method for the whole plan; empty = cheapest')
    @app_commands.autocomplete(target=target_choices, method=method_choices)
    async def raidcalc(interaction: discord.Interaction, target: str | None = None, quantity: app_commands.Range[int, 1, 50] = 1, method: str | None = None):
        lang = lang_for(interaction)
        entries, category = {}, 'doors'
        if target:
            key = data.find(target)
            if not key:
                await unknown_target(interaction)
                return
            entries[key] = quantity
            category = data.targets[key]['category']
        await send_layout(interaction, builder_layout(data, lang, entries, method if method in data.explosives else BEST, category,
                                                      interaction.user.id), ephemeral=True)

    @bot.tree.command(name='raidbudget', description='🧪 What can I craft and destroy with this sulfur?')
    @app_commands.describe(sulfur='Sulfur available')
    async def raidbudget(interaction: discord.Interaction, sulfur: app_commands.Range[int, 1, 10_000_000]):
        await interaction.response.send_message(view=budget_layout(data, lang_for(interaction), sulfur), ephemeral=True)

    @bot.tree.command(name='raidcompare', description='📊 Compare amounts and sulfur of every method')
    @app_commands.describe(target='Target (optional): type and pick', side='Wall side')
    @app_commands.autocomplete(target=target_choices)
    @app_commands.choices(side=SIDE_CHOICES)
    async def raidcompare(interaction: discord.Interaction, target: str, side: str = 'hard'):
        key = data.find(target)
        if not key:
            await unknown_target(interaction)
            return
        side = side if side in data.sides(key) else 'hard'
        await interaction.response.send_message(view=compare_layout(data, lang_for(interaction), key, side), ephemeral=True)

    @bot.tree.command(name='raidtools', description='🔧 Every method and amount against a target')
    @app_commands.describe(target='Target (optional): type and pick')
    @app_commands.autocomplete(target=target_choices)
    async def raidtools(interaction: discord.Interaction, target: str):
        lang = lang_for(interaction)
        key = data.find(target)
        if not key:
            await unknown_target(interaction)
            return
        view = ui.LayoutView()
        box = ui.Container(accent_colour=YELLOW)
        tgt = data.targets[key]
        box.add_item(ui.Section(ui.TextDisplay(f"## 🔧 {tgt['name']}\n-# {tgt['hp']:,} HP"), accessory=ui.Thumbnail(data.icon(key))))
        for side in data.sides(key):
            lines = [t(lang, 'raid.tools.line', emoji=METHOD_EMOJI.get(r.method, '💥'), name=explosive_name(data, r.method), amount=r.amount,
                       cost=short_cost(data, lang, r.method, r.amount)) for r in data.rows(key, side)]
            box.add_item(ui.TextDisplay(f"### {t(lang, 'side.' + side)}\n" + '\n'.join(lines)))
        box.add_item(footer(data, lang, key))
        view.add_item(box)
        await interaction.response.send_message(view=view, ephemeral=True)
