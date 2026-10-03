"""Piezas de interfaz compartidas: colores, embeds de marca y vistas con dueño.

Todo lo visual del bot pasa por aquí para que los comandos se vean coherentes
(mismos colores, mismos pies de página, mismos mensajes de error).
"""
from __future__ import annotations
import logging
import discord

# Paleta de la marca RuxtBot.
YELLOW = 0xD5A522   # color principal
GREEN = 0x2ECC71    # éxito / objetivo destruido
ORANGE = 0xE67E22   # en progreso / avisos
RED = 0xC0392B      # error / baneos
GREY = 0x95A5A6     # neutro / sin datos


def brand_embed(title: str | None = None, description: str | None = None, color: int = YELLOW) -> discord.Embed:
    """Embed base con el color de la marca."""
    return discord.Embed(title=title, description=description, color=color)


def error_embed(message: str, hint: str | None = None) -> discord.Embed:
    """Mensaje de error amable: qué pasó y, si se puede, cómo arreglarlo."""
    e = discord.Embed(description=f'❌ {message}', color=RED)
    if hint:
        e.add_field(name='💡 Cómo seguir', value=hint, inline=False)
    return e


def success_embed(message: str) -> discord.Embed:
    return discord.Embed(description=f'✅ {message}', color=GREEN)


def progress_bar(pct: float, size: int = 10) -> str:
    """Barra de texto proporcional a `pct` (0-100); siempre mide `size` caracteres."""
    filled = max(0, min(size, round(pct / 100 * size)))
    return '█' * filled + '░' * (size - filled)


def fmt_num(value: float) -> str:
    """Número legible: sin decimales si es entero, con uno si no (1,234 · 120.5)."""
    if float(value).is_integer():
        return f'{int(value):,}'
    return f'{value:,.1f}'


async def reply(interaction: discord.Interaction, **kwargs) -> None:
    """Responde aunque la interacción ya tenga respuesta o esté diferida."""
    kwargs.setdefault('ephemeral', True)
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


class OwnedView(discord.ui.View):
    """Vista que solo puede usar quien abrió el panel y que se apaga al caducar.

    - `owner_id=None` permite que cualquiera la use (útil en pruebas o paneles compartidos).
    - `message` se rellena tras enviar/editar para poder desactivar los botones al expirar.
    """

    def __init__(self, owner_id: int | None = None, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message('🔒 Este panel es de otra persona. Abre el tuyo con el mismo comando.', ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        # Deja los componentes visibles pero inutilizables para que nadie pulse un panel muerto.
        for item in self.children:
            if not getattr(item, 'url', None):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logging.exception('UI callback failed', exc_info=error)
        await reply(interaction, embed=error_embed('Algo falló al procesar ese botón.', 'Vuelve a abrir el panel con el comando.'))


async def swap(interaction: discord.Interaction, embed: discord.Embed, view: OwnedView | None) -> None:
    """Sustituye el panel actual por otro, conservando el dueño y la referencia al mensaje."""
    if view is not None and isinstance(view, OwnedView):
        view.owner_id = view.owner_id if view.owner_id is not None else getattr(interaction.user, 'id', None)
        view.message = interaction.message
    await interaction.response.edit_message(content=None, embed=embed, view=view)
