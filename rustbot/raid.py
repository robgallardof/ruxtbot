"""Todo lo de raid: cálculos de costo y los paneles interactivos.

Cálculos (funciones puras, fáciles de probar):
    sulfur_per_unit / target_cost / best_method / comparison / plan_totals / budget

Paneles (vistas de Discord):
    RaidStartView     → elige categoría
    RaidTargetView    → elige objetivo
    RaidProgressView  → simula el raid unidad a unidad
    RaidBuilderView   → calculadora de base con varios objetivos (/raidcalc)
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import discord
from discord import app_commands
from .ui import GREEN, ORANGE, YELLOW, OwnedView, brand_embed, error_embed, fmt_num, progress_bar, swap

# Etiqueta y emoji de cada categoría del catálogo.
CATEGORIES = {
    'doors': ('🚪', 'Puertas'),
    'walls': ('🧱', 'Muros'),
    'building': ('🏠', 'Techos y pisos'),
    'deployables': ('🛡️', 'Defensa y desplegables'),
    'siege': ('🏹', 'Asedio: propano y cañones'),
}

# Emoji por método para que los menús se escaneen de un vistazo.
METHOD_EMOJI = {
    'rocket': '🚀', 'hv-rocket': '🚀', 'incendiary-rocket': '🔥', 'mlrs': '🎆', 'c4': '🧨', 'satchel': '🎒',
    'explosive-ammo': '🔫', 'beancan': '🥫', 'f1': '💣', 'molotov': '🍾', 'hammerhead': '🏹', 'ram': '🐏',
    'propane': '🛢️', 'catapult-propane': '🛢️', 'he-grenade': '💥', 'cannonball': '⚫', 'mortar': '🎯',
    'handmade-shell': '🔫',
}
BEST = 'best'  # valor especial del selector de método: «el más barato por objetivo»

# Métodos que necesitan equipo de asedio o dependen del fuego. Se muestran al comparar,
# pero no se recomiendan como «más barato» porque casi nadie raidea así una base normal.
SIEGE = {'catapult-propane', 'cannonball', 'mortar', 'hammerhead', 'ram', 'mlrs', 'he-grenade'}
FIRE = {'molotov', 'incendiary-rocket'}


def method_tag(method: str) -> str:
    return ' *(asedio)*' if method in SIEGE else ' *(fuego)*' if method in FIRE else ''


# ───────────────────────────── Cálculos ─────────────────────────────

def item_name(catalog, key: str) -> str:
    return catalog.raw['items'].get(key, {}).get('name', key)


def method_label(catalog, method: str) -> str:
    return f"{METHOD_EMOJI.get(method, '💥')} {item_name(catalog, method)}"


def raidable(catalog) -> dict[str, dict]:
    """Objetivos con datos de daño verificados (los pendientes no se pueden calcular)."""
    return {k: t for k, t in catalog.raw['targets'].items() if t.get('methods') and t.get('status') != 'pending_verification'}


def target_key(catalog, target: dict) -> str:
    return next(k for k, t in catalog.raw['targets'].items() if t is target)


def sulfur_cost(catalog, method: str, units: int) -> int | None:
    """Azufre para fabricar `units` unidades; None si la receta no está verificada."""
    if not catalog.raw['items'].get(method, {}).get('recipe'):
        return None
    return catalog.materials(method, units).get('sulfur', 0)


def sulfur_per_unit(catalog, method: str) -> float | None:
    """Azufre medio por unidad, teniendo en cuenta recetas que fabrican lotes (p. ej. munición x2)."""
    item = catalog.raw['items'].get(method, {})
    batch = item.get('yield', 1)
    cost = sulfur_cost(catalog, method, batch)
    return None if cost is None else cost / batch


def target_cost(catalog, target: dict, method: str) -> int | None:
    """Azufre necesario para destruir un objetivo con un método."""
    data = target.get('methods', {}).get(method)
    return None if not data else sulfur_cost(catalog, method, data['count'])


def best_method(catalog, target: dict, practical: bool = True) -> tuple[str, int] | None:
    """Método con menos azufre (costo conocido y > 0). Empate: menos unidades.

    Con `practical=True` (por defecto) ignora asedio y fuego; si el objetivo solo admite
    esos métodos, recurre a ellos para no dejar al usuario sin recomendación.
    """
    options = [(cost, target['methods'][m]['count'], m) for m in target.get('methods', {})
               if (cost := target_cost(catalog, target, m)) and not (practical and m in SIEGE | FIRE)]
    if not options and practical:
        return best_method(catalog, target, practical=False)
    if not options:
        return None
    cost, _, method = min(options)
    return method, cost


def comparison(catalog, target: dict) -> list[str]:
    """Una línea por método: primero los que gastan azufre (de menos a más),
    luego los que no usan azufre (ballesta, ariete…) y al final los de costo desconocido."""
    best = best_method(catalog, target)
    rows = []
    for method, data in target.get('methods', {}).items():
        cost = target_cost(catalog, target, method)
        group = 2 if cost is None else (1 if cost == 0 else 0)
        crown = '🏆 ' if best and method == best[0] else ''
        label = {0: f'{cost or 0:,} azufre', 1: 'sin azufre', 2: 'costo no verificado'}[group]
        rows.append((group, cost or 0, data['count'], f"{crown}{METHOD_EMOJI.get(method, '💥')} **{item_name(catalog, method)}**{method_tag(method)}: {data['count']:,} unidades · {label}"))
    return [row[3] for row in sorted(rows)]


@dataclass
class PlanRow:
    target: str          # clave del objetivo
    quantity: int        # cuántos objetivos iguales
    method: str | None   # método usado (None = no hay datos para el método elegido)
    units: int           # explosivos necesarios
    sulfur: int | None   # azufre de esta fila (None = desconocido)


def plan_totals(catalog, entries: dict[str, int], method: str = BEST) -> dict:
    """Suma un plan de varios objetivos.

    `method=BEST` elige el método más barato en cada objetivo; si es un método concreto,
    los objetivos que no lo admiten quedan marcados como sin datos.
    Los materiales se calculan sobre el total de cada explosivo para respetar los lotes.
    """
    rows: list[PlanRow] = []
    units: Counter = Counter()
    for key, qty in entries.items():
        target = catalog.raw['targets'][key]
        chosen = (best_method(catalog, target) or (None, None))[0] if method == BEST else method
        data = target.get('methods', {}).get(chosen) if chosen else None
        if not data:
            rows.append(PlanRow(key, qty, None, 0, None))
            continue
        count = data['count'] * qty
        units[chosen] += count
        rows.append(PlanRow(key, qty, chosen, count, sulfur_cost(catalog, chosen, count)))
    materials: Counter = Counter()
    unknown = []
    for m, n in units.items():
        if catalog.raw['items'][m].get('recipe'):
            materials += catalog.materials(m, n)
        else:
            unknown.append(m)
    return {'rows': rows, 'units': units, 'materials': materials, 'sulfur': materials.get('sulfur', 0), 'unknown': unknown}


def budget(catalog, sulfur: int) -> dict:
    """¿Qué se puede fabricar y destruir con cierta cantidad de azufre?"""
    craftable = []
    for method in sorted({m for t in raidable(catalog).values() for m in t['methods']}):
        per = sulfur_per_unit(catalog, method)
        if per:
            craftable.append((method, int(sulfur // per), per))
    destroyable = []
    for key, target in raidable(catalog).items():
        if best := best_method(catalog, target):
            destroyable.append((key, sulfur // best[1], best[0], best[1]))
    return {'craftable': sorted(craftable, key=lambda r: r[2]), 'destroyable': destroyable}


# ───────────────────────────── Embeds ─────────────────────────────

def category_embed(catalog) -> discord.Embed:
    e = brand_embed('💥 Planificador de raid', 'Elige una **categoría** y luego el objetivo. Verás vida restante, costo en azufre y el método más barato.')
    lines = []
    for key, (emoji, label) in CATEGORIES.items():
        total = sum(1 for t in catalog.raw['targets'].values() if t.get('category') == key)
        ready = sum(1 for t in raidable(catalog).values() if t.get('category') == key)
        lines.append(f'{emoji} **{label}** — {ready}/{total} con datos')
    e.add_field(name='📂 Categorías', value='\n'.join(lines), inline=False)
    e.add_field(name='🧮 ¿Varios objetivos?', value='Usa `/raidcalc` para sumar puertas y muros de una base.', inline=False)
    e.set_footer(text=f'{catalog.version} · Estimación comunitaria')
    return e


def target_list_embed(catalog, category: str) -> discord.Embed:
    emoji, label = CATEGORIES.get(category, ('🎯', category))
    e = brand_embed(f'{emoji} {label}', 'Elige un objetivo en el menú.')
    lines = []
    for t in catalog.raw['targets'].values():
        if t.get('category') != category:
            continue
        if best := best_method(catalog, t):
            lines.append(f"• **{t['name']}** · {t['hp']:,} HP · 🏆 {item_name(catalog, best[0])} ({best[1]:,} azufre)")
        else:
            lines.append(f"• {t['name']} · ⏳ pendiente de verificar")
    e.add_field(name='🎯 Objetivos', value='\n'.join(lines)[:1024] or '—', inline=False)
    e.set_footer(text=catalog.version)
    return e


def raid_embed(catalog, target: dict, method: str, used: int = 0) -> discord.Embed:
    """Estado de la simulación: vida restante, unidades usadas, costo y método más barato."""
    m = target['methods'][method]
    count, per, hp = m['count'], m['damage'], target['hp']
    used = max(0, min(used, count))
    remaining = max(0.0, hp - used * per)
    pct = round(100 * remaining / hp)
    destroyed = remaining == 0
    emoji = CATEGORIES.get(target.get('category'), ('🎯', ''))[0]
    state = '✅ **Objetivo destruido**' if destroyed else ('🎯 **Objetivo intacto**' if used == 0 else '⚠️ **Objetivo dañado**')
    e = brand_embed(f"{emoji} {target['name']}",
                    f"{state}\n`{progress_bar(pct)}` **{pct}% de vida**\n❤️ Vida restante: **{fmt_num(remaining)}/{hp:,} HP**")
    e.color = GREEN if destroyed else (YELLOW if pct > 50 else ORANGE)

    # Método actual y progreso.
    e.add_field(name=method_label(catalog, method),
                value=f"Usados **{used:,}**/{count:,} · Faltan **{count - used:,}**\nDaño por unidad: **{per:g}**", inline=True)

    # Costo del método actual y comparación con el más barato.
    cost = target_cost(catalog, target, method)
    best = best_method(catalog, target)
    cost_text = f'**{cost:,}** azufre en total' if cost is not None else 'Costo no verificado'
    if best and best[0] == method:
        cost_text += '\n🏆 Es el método más barato'
    elif best:
        cost_text += f"\n🏆 Más barato: **{item_name(catalog, best[0])}** ({best[1]:,})"
    if method in SIEGE:
        cost_text += '\n⚠️ Requiere equipo de asedio'
    elif method in FIRE:
        cost_text += '\n⚠️ Daño por fuego aproximado'
    e.add_field(name='🧪 Azufre', value=cost_text, inline=True)

    mats = catalog.materials(method, count) if catalog.raw['items'][method].get('recipe') else Counter()
    resources = '\n'.join(f'• {n:,} {item_name(catalog, k)}' for k, n in mats.items())
    e.add_field(name='📦 Materiales para fabricar el total',
                value=(resources + '\n*Lanzador/arma no incluido; lotes completos.*') if resources else 'Costo no verificado; no significa gratis. Equipo/lanzador no incluido.',
                inline=False)
    e.add_field(name='💡 Siguiente paso',
                value='Reinicia o compara otro método.' if destroyed else 'Pulsa **💥 Aplicar 1** para avanzar, **↩️ Deshacer** si te pasaste o **⏭️ Completar** para ver el final.',
                inline=False)
    e.add_field(name='📝 Condiciones', value=target.get('notes', 'Estimación; colocación y splash pueden cambiar el resultado.'), inline=False)
    if target.get('source'):
        e.url = target['source']
    e.set_footer(text=f'{catalog.version} · Estimación comunitaria · No es tiempo real')
    return e


def comparison_embed(catalog, target: dict) -> discord.Embed:
    e = brand_embed(f"📊 Comparar · {target['name']}", '\n'.join(comparison(catalog, target)))
    e.set_footer(text='🏆 = más barato con explosivos comunes · Costo no verificado no significa gratis · Equipo aparte')
    return e


def plan_embed(catalog, entries: dict[str, int], method: str = BEST) -> discord.Embed:
    """Resumen de la calculadora de base."""
    mode = '🏆 Más barato en cada objetivo (explosivos comunes)' if method == BEST else method_label(catalog, method)
    e = brand_embed('🧮 Calculadora de raid', f'**Método:** {mode}')
    if not entries:
        e.description += '\n\n👉 Añade objetivos con el menú **➕ Añadir objetivo**. Cada selección suma uno.'
        e.set_footer(text=catalog.version)
        return e
    plan = plan_totals(catalog, entries, method)
    lines = []
    for row in plan['rows']:
        name = catalog.raw['targets'][row.target]['name']
        if row.method is None:
            lines.append(f'⚠️ **{row.quantity}×** {name} — sin datos para ese método')
        else:
            cost = f'{row.sulfur:,} 🧪' if row.sulfur is not None else 'costo ?'
            lines.append(f"**{row.quantity}×** {name} — {row.units:,} {METHOD_EMOJI.get(row.method, '💥')} · {cost}")
    e.add_field(name='🎯 Objetivos', value='\n'.join(lines)[:1024], inline=False)
    explosives = '\n'.join(f'{METHOD_EMOJI.get(m, "💥")} **{n:,}** × {item_name(catalog, m)}' for m, n in plan['units'].most_common())
    e.add_field(name='💣 Explosivos', value=explosives or '—', inline=True)
    e.add_field(name='🧪 Azufre total', value=f"**{plan['sulfur']:,}**" + ('\n⚠️ + métodos sin costo' if plan['unknown'] else ''), inline=True)
    mats = '\n'.join(f'• {n:,} {item_name(catalog, k)}' for k, n in plan['materials'].most_common() if k != 'sulfur')
    if mats:
        e.add_field(name='📦 Otros materiales', value=mats[:1024], inline=False)
    e.set_footer(text=f'{catalog.version} · Impactos directos, sin splash. Lanzadores no incluidos.')
    return e


def budget_embed(catalog, sulfur: int) -> discord.Embed:
    data = budget(catalog, sulfur)
    e = brand_embed(f'🧪 Presupuesto · {sulfur:,} azufre', 'Lo que te alcanza si todo el azufre va a un solo tipo de explosivo.')
    crafts = [f"{METHOD_EMOJI.get(m, '💥')} **{n:,}** × {item_name(catalog, m)} · {fmt_num(per)}/u" for m, n, per in data['craftable'] if n]
    e.add_field(name='💣 Puedes fabricar', value='\n'.join(crafts)[:1024] or 'No alcanza para ningún explosivo.', inline=False)
    kills = [f"**{n:,}** × {catalog.raw['targets'][k]['name']} · {item_name(catalog, m)} ({cost:,}/u)" for k, n, m, cost in data['destroyable']]
    e.add_field(name='🎯 Puedes destruir (método más barato)', value='\n'.join(kills)[:1024] or '—', inline=False)
    e.set_footer(text=f'{catalog.version} · No incluye carbón, fragmentos ni otros materiales.')
    return e


# ───────────────────────────── Paneles ─────────────────────────────

class RaidCategorySelect(discord.ui.Select):
    def __init__(self, catalog):
        self.catalog = catalog
        options = [discord.SelectOption(label=label, value=key, emoji=emoji,
                                        description=f"{sum(1 for t in catalog.raw['targets'].values() if t.get('category') == key)} objetivos")
                   for key, (emoji, label) in CATEGORIES.items()]
        super().__init__(placeholder='📂 Elige categoría', options=options)

    async def callback(self, interaction):
        await swap(interaction, target_list_embed(self.catalog, self.values[0]), RaidTargetView(self.catalog, self.values[0], self.view.owner_id))


class RaidTargetSelect(discord.ui.Select):
    def __init__(self, catalog, category):
        self.catalog = catalog
        options = []
        for key, t in catalog.raw['targets'].items():
            if t.get('category') != category:
                continue
            best = best_method(catalog, t)
            desc = f"{t['hp']:,} HP · más barato: {item_name(catalog, best[0])}" if best else ('Pendiente de verificar' if 'hp' not in t else f"{t['hp']:,} HP")
            options.append(discord.SelectOption(label=t['name'][:100], value=key, description=desc[:100],
                                                emoji='⏳' if t.get('status') == 'pending_verification' else '🎯'))
        super().__init__(placeholder='🎯 Elige objetivo', options=options)

    async def callback(self, interaction):
        target = self.catalog.raw['targets'][self.values[0]]
        owner = self.view.owner_id
        if target.get('status') == 'pending_verification' or not target.get('methods'):
            e = brand_embed(f"⏳ {target['name']}", 'Este objetivo está **pendiente de verificar** tras el último parche. No inventamos cifras.', color=ORANGE)
            e.set_footer(text=self.catalog.version)
            await swap(interaction, e, RaidBackView(self.catalog, owner))
            return
        # Empieza con el método más barato: es lo que casi todos quieren ver primero.
        method = (best_method(self.catalog, target) or (next(iter(target['methods'])),))[0]
        await swap(interaction, raid_embed(self.catalog, target, method), RaidProgressView(self.catalog, target, method, owner_id=owner))


class RaidMethodSelect(discord.ui.Select):
    def __init__(self, catalog, target, current: str | None = None):
        self.catalog, self.target = catalog, target
        best = best_method(catalog, target)
        options = []
        for method, data in list(target['methods'].items())[:25]:
            cost = target_cost(catalog, target, method)
            desc = f"{data['count']:,} unidades · " + (f'{cost:,} azufre' if cost is not None else 'costo no verificado')
            if best and method == best[0]:
                desc = '🏆 ' + desc
            options.append(discord.SelectOption(label=item_name(catalog, method)[:100], value=method, description=desc[:100],
                                                emoji=METHOD_EMOJI.get(method, '💥'), default=method == current))
        super().__init__(placeholder='🔁 Cambiar método', options=options, row=0)

    async def callback(self, interaction):
        method = self.values[0]
        await swap(interaction, raid_embed(self.catalog, self.target, method), RaidProgressView(self.catalog, self.target, method, owner_id=self.view.owner_id))


class StepButton(discord.ui.Button):
    """Avanza o retrocede la simulación `delta` unidades (o hasta el final con `to_end`)."""

    def __init__(self, catalog, target, method, used, delta=1, to_end=False, **kwargs):
        super().__init__(**kwargs)
        self.catalog, self.target, self.method, self.used, self.delta, self.to_end = catalog, target, method, used, delta, to_end

    async def callback(self, interaction):
        count = self.target['methods'][self.method]['count']
        used = count if self.to_end else max(0, min(count, self.used + self.delta))
        await swap(interaction, raid_embed(self.catalog, self.target, self.method, used),
                   RaidProgressView(self.catalog, self.target, self.method, used, owner_id=self.view.owner_id))


# Alias con los nombres anteriores para no romper código externo.
def DetonateButton(catalog, target, method, used):
    needed = target['methods'][method]['count']
    done = used >= needed
    return StepButton(catalog, target, method, used, 1, label='Destruido' if done else 'Aplicar 1', emoji='💥',
                      style=discord.ButtonStyle.success if done else discord.ButtonStyle.danger, disabled=done, row=1)


class CompareMethodsButton(discord.ui.Button):
    def __init__(self, catalog, target):
        super().__init__(label='Comparar', emoji='📊', style=discord.ButtonStyle.secondary, row=2)
        self.catalog, self.target = catalog, target

    async def callback(self, interaction):
        await interaction.response.send_message(embed=comparison_embed(self.catalog, self.target), ephemeral=True)


class RaidBackButton(discord.ui.Button):
    def __init__(self, catalog, row=None):
        super().__init__(label='Volver', emoji='⬅️', style=discord.ButtonStyle.secondary, row=row)
        self.catalog = catalog

    async def callback(self, interaction):
        await swap(interaction, category_embed(self.catalog), RaidStartView(self.catalog, self.view.owner_id))


class RaidStartView(OwnedView):
    def __init__(self, catalog, owner_id=None):
        super().__init__(owner_id)
        self.add_item(RaidCategorySelect(catalog))


class RaidTargetView(OwnedView):
    def __init__(self, catalog, category, owner_id=None):
        super().__init__(owner_id)
        self.add_item(RaidTargetSelect(catalog, category))
        self.add_item(RaidBackButton(catalog))


class RaidBackView(OwnedView):
    def __init__(self, catalog, owner_id=None):
        super().__init__(owner_id)
        self.add_item(RaidBackButton(catalog))


class RaidProgressView(OwnedView):
    """Simulador: fila 0 método · fila 1 avanzar/deshacer · fila 2 utilidades."""

    def __init__(self, catalog, target, method, used=0, owner_id=None):
        super().__init__(owner_id)
        count = target['methods'][method]['count']
        self.add_item(RaidMethodSelect(catalog, target, method))
        self.add_item(DetonateButton(catalog, target, method, used))
        self.add_item(StepButton(catalog, target, method, used, -1, label='Deshacer', emoji='↩️',
                                 style=discord.ButtonStyle.secondary, disabled=used == 0, row=1))
        self.add_item(StepButton(catalog, target, method, used, to_end=True, label='Completar', emoji='⏭️',
                                 style=discord.ButtonStyle.primary, disabled=used >= count, row=1))
        self.add_item(StepButton(catalog, target, method, 0, to_end=False, delta=-count, label='Reiniciar', emoji='🔄',
                                 style=discord.ButtonStyle.secondary, disabled=used == 0, row=1))
        self.add_item(CompareMethodsButton(catalog, target))
        self.add_item(RaidBackButton(catalog, row=2))


# ─────────────────────── Calculadora de base (/raidcalc) ───────────────────────

class RaidBuilderView(OwnedView):
    """Calculadora con estado: objetivos → cantidad y un método global (o el más barato)."""

    def __init__(self, catalog, entries: dict[str, int] | None = None, method: str = BEST, owner_id=None):
        super().__init__(owner_id, timeout=600)
        self.catalog, self.entries, self.method = catalog, dict(entries or {}), method
        targets = raidable(catalog)

        add = discord.ui.Select(placeholder='➕ Añadir objetivo (suma 1)', row=0, options=[
            discord.SelectOption(label=t['name'][:100], value=k, emoji=CATEGORIES.get(t.get('category'), ('🎯',))[0],
                                 description=f"{t['hp']:,} HP" + (f' · en plan: {self.entries[k]}' if k in self.entries else ''))
            for k, t in list(targets.items())[:25]])
        add.callback = self._add
        self.add_item(add)

        methods = sorted({m for t in targets.values() for m in t['methods']}, key=lambda m: sulfur_per_unit(catalog, m) or 1e9)
        pick = discord.ui.Select(placeholder='🔁 Método', row=1, options=[
            discord.SelectOption(label='Más barato en cada objetivo', value=BEST, emoji='🏆', default=method == BEST)] + [
            discord.SelectOption(label=item_name(catalog, m)[:100], value=m, emoji=METHOD_EMOJI.get(m, '💥'), default=method == m)
            for m in methods[:24]])
        pick.callback = self._method
        self.add_item(pick)

        if self.entries:
            remove = discord.ui.Select(placeholder='➖ Quitar uno de…', row=2, options=[
                discord.SelectOption(label=catalog.raw['targets'][k]['name'][:100], value=k, description=f'En plan: {n}')
                for k, n in self.entries.items()])
            remove.callback = self._remove
            self.add_item(remove)

        clear = discord.ui.Button(label='Vaciar', emoji='🗑️', style=discord.ButtonStyle.secondary, row=3, disabled=not self.entries)
        clear.callback = self._clear
        self.add_item(clear)
        share = discord.ui.Button(label='Compartir en el canal', emoji='📤', style=discord.ButtonStyle.primary, row=3, disabled=not self.entries)
        share.callback = self._share
        self.add_item(share)

    async def _redraw(self, interaction, entries, method):
        await swap(interaction, plan_embed(self.catalog, entries, method), RaidBuilderView(self.catalog, entries, method, self.owner_id))

    async def _add(self, interaction):
        key = interaction.data['values'][0]
        await self._redraw(interaction, self.entries | {key: self.entries.get(key, 0) + 1}, self.method)

    async def _remove(self, interaction):
        key = interaction.data['values'][0]
        entries = dict(self.entries)
        entries[key] -= 1
        if entries[key] <= 0:
            del entries[key]
        await self._redraw(interaction, entries, self.method)

    async def _method(self, interaction):
        await self._redraw(interaction, self.entries, interaction.data['values'][0])

    async def _clear(self, interaction):
        await self._redraw(interaction, {}, self.method)

    async def _share(self, interaction):
        # Publica una copia (sin botones) visible para todo el canal.
        e = plan_embed(self.catalog, self.entries, self.method)
        e.set_author(name=f'Plan de {interaction.user.display_name}')
        await interaction.response.send_message(embed=e)


# ───────────────────────────── Comandos ─────────────────────────────

def register_raid_commands(bot, catalog):
    """Registra /raid, /raidcalc, /raidbudget, /raidcompare, /raidtools y /raidplan."""

    async def target_choices(interaction, current: str):
        # Busca por nombre, clave o alias (también en español: «puerta hq», «muro piedra»…).
        q = current.casefold()
        out = []
        for k, t in raidable(catalog).items():
            haystack = [t['name'].casefold(), k] + [a.casefold() for a in t.get('aliases', [])]
            if any(q in h for h in haystack):
                out.append(app_commands.Choice(name=f"{t['name']} · {t['hp']:,} HP"[:100], value=k))
        return out[:25]

    async def method_choices(interaction, current: str):
        # Si ya eligió objetivo, solo ofrece sus métodos, ordenados por azufre y con su costo.
        ns = interaction.namespace
        target = catalog.raid(getattr(ns, 'target', None) or getattr(ns, 'objetivo', None) or '')
        keys = target.get('methods', {}) if target else {m for t in raidable(catalog).values() for m in t['methods']}
        out = []
        for m in sorted(keys, key=lambda m: sulfur_per_unit(catalog, m) or 1e9):
            if current.casefold() not in item_name(catalog, m).casefold() and current.casefold() not in m:
                continue
            cost = target_cost(catalog, target, m) if target else None
            out.append(app_commands.Choice(name=(item_name(catalog, m) + (f' · {cost:,} azufre' if cost else ''))[:100], value=m))
        return out[:25]

    async def unknown_target(interaction):
        await interaction.response.send_message(embed=error_embed('Objetivo desconocido o pendiente de verificar.',
                                                                  'Escribe parte del nombre y elige una sugerencia, o abre `/raid` sin parámetros.'), ephemeral=True)

    async def send_panel(interaction, embed, view, ephemeral=False):
        # Guarda el mensaje en la vista para poder desactivarla cuando caduque.
        await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
        try:
            view.message = await interaction.original_response()
        except (discord.HTTPException, AttributeError):
            pass

    @bot.tree.command(name='raid', description='💥 Planificador de raid: vida restante, azufre y método más barato')
    @app_commands.describe(target='Objetivo (opcional): escribe y elige de la lista', method='Método (opcional); por defecto el más barato')
    @app_commands.autocomplete(target=target_choices, method=method_choices)
    async def raid(interaction: discord.Interaction, target: str | None = None, method: str | None = None):
        if not target:
            await send_panel(interaction, category_embed(catalog), RaidStartView(catalog, interaction.user.id))
            return
        t = catalog.raid(target)
        if not t or not t.get('methods') or t.get('status') == 'pending_verification':
            await unknown_target(interaction)
            return
        method = method or best_method(catalog, t)[0]
        if method not in t['methods']:
            await interaction.response.send_message(embed=error_embed(f"Ese método no sirve contra {t['name']}.", 'Elige un método de las sugerencias.'), ephemeral=True)
            return
        await send_panel(interaction, raid_embed(catalog, t, method), RaidProgressView(catalog, t, method, owner_id=interaction.user.id))

    @bot.tree.command(name='raidcalc', description='🧮 Calculadora de base: suma varios objetivos y obtén explosivos y azufre')
    @app_commands.describe(objetivo='Objetivo inicial (opcional)', cantidad='Cuántos de ese objetivo', metodo='Método para todo el plan; vacío = el más barato')
    @app_commands.autocomplete(objetivo=target_choices, metodo=method_choices)
    async def raidcalc(interaction: discord.Interaction, objetivo: str | None = None, cantidad: app_commands.Range[int, 1, 50] = 1, metodo: str | None = None):
        entries = {}
        if objetivo:
            t = catalog.raid(objetivo)
            if not t or not t.get('methods'):
                await unknown_target(interaction)
                return
            entries[target_key(catalog, t)] = cantidad
        method = metodo if metodo in catalog.raw['items'] else BEST
        await send_panel(interaction, plan_embed(catalog, entries, method), RaidBuilderView(catalog, entries, method, interaction.user.id), ephemeral=True)

    @bot.tree.command(name='raidbudget', description='🧪 ¿Qué puedo fabricar y destruir con este azufre?')
    @app_commands.describe(azufre='Cantidad de azufre disponible')
    async def raidbudget(interaction: discord.Interaction, azufre: app_commands.Range[int, 1, 10_000_000]):
        await interaction.response.send_message(embed=budget_embed(catalog, azufre), ephemeral=True)

    @bot.tree.command(name='raidtools', description='🔧 Daño por unidad de cada método contra un objetivo')
    @app_commands.autocomplete(target=target_choices)
    async def raid_tools(interaction: discord.Interaction, target: str):
        t = catalog.raid(target)
        if not t or not t.get('methods'):
            await unknown_target(interaction)
            return
        lines = [f"{METHOD_EMOJI.get(k, '💥')} **{item_name(catalog, k)}** · {v['damage']:g} daño/u · {v['count']:,} para destruir" for k, v in t['methods'].items()]
        e = brand_embed(f"🔧 {t['name']} · {t['hp']:,} HP", '\n'.join(lines))
        e.set_footer(text='Usa /raidcompare para costos y /raid para simular.')
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name='raidcompare', description='📊 Compara unidades y azufre de todos los métodos de un objetivo')
    @app_commands.autocomplete(target=target_choices)
    async def raid_compare(interaction: discord.Interaction, target: str):
        t = catalog.raid(target)
        if not t or not t.get('methods'):
            await unknown_target(interaction)
            return
        await interaction.response.send_message(embed=comparison_embed(catalog, t), ephemeral=True)

    @bot.tree.command(name='raidplan', description='📋 Munición y materiales para varios objetivos iguales')
    @app_commands.autocomplete(target=target_choices, method=method_choices)
    async def raid_plan(interaction: discord.Interaction, target: str, method: str, quantity: app_commands.Range[int, 1, 100] = 1):
        t = catalog.raid(target)
        if not t or method not in t.get('methods', {}):
            await interaction.response.send_message(embed=error_embed('Selecciona un objetivo y un método disponibles.', 'Usa las sugerencias que aparecen al escribir.'), ephemeral=True)
            return
        # Cada objetivo se redondea por separado: no se reparte splash entre objetivos.
        units = t['methods'][method]['count'] * quantity
        mats = catalog.materials(method, units) if catalog.raw['items'][method].get('recipe') else Counter()
        cost = '\n'.join(f'• {n:,} {item_name(catalog, k)}' for k, n in mats.items()) or 'Costo no verificado; no significa gratis.'
        e = brand_embed(f"📋 Plan · {quantity} × {t['name']}", f"{METHOD_EMOJI.get(method, '💥')} **{units:,} × {item_name(catalog, method)}**\n\n{cost}")
        e.set_footer(text='Objetivos completos, impactos separados; no descuenta splash. Equipo no incluido.')
        await interaction.response.send_message(embed=e, ephemeral=True)
