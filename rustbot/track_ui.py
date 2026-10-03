"""Small guided tracking panel; mutations reuse the slash command's checks."""
import discord
from .i18n import t
from .ui import OwnedView


class TrackModal(discord.ui.Modal):
    def __init__(self, callback, lang, days, action='add'):
        super().__init__(title=t(lang, 'track.form.remove' if action == 'remove' else 'track.form.add', days=days))
        self.callback, self.days, self.action = callback, days, action
        self.player = discord.ui.TextInput(label=t(lang, 'track.form.player'), placeholder=t(lang, 'track.form.placeholder'), max_length=100)
        self.add_item(self.player)
        if action == 'add':
            self.nickname = discord.ui.TextInput(label=t(lang, 'track.form.label'), required=False, max_length=80)
            self.add_item(self.nickname)

    async def on_submit(self, interaction):
        await self.callback(interaction, action=self.action, player=self.player.value.strip(),
                            label=self.nickname.value.strip() or None if self.action == 'add' else None,
                            days=self.days)


class TrackingPanel(OwnedView):
    def __init__(self, callback, lang, owner_id, recent=()):
        """`recent`: (label, player ref) pairs from the player book, offered as a one-click 7-day watch."""
        super().__init__(owner_id)
        self.callback, self.lang = callback, lang
        if recent:
            quick = discord.ui.Select(placeholder=t(lang, 'track.quick'), row=0, options=[
                discord.SelectOption(label=label[:100], value=ref, emoji='👀') for label, ref in recent[:25]])

            async def watch(interaction):
                await callback(interaction, action='add', player=interaction.data['values'][0], days=7)
            quick.callback = watch
            self.add_item(quick)
        for days in (7, 15):
            button = discord.ui.Button(label=t(lang, 'track.button.add', days=days), emoji='👀', style=discord.ButtonStyle.primary, row=1)
            async def add(interaction, duration=days):
                await interaction.response.send_modal(TrackModal(callback, lang, duration))
            button.callback = add
            self.add_item(button)
        stop = discord.ui.Button(label=t(lang, 'track.button.stop'), emoji='🔕', style=discord.ButtonStyle.secondary, row=1)
        async def remove(interaction):
            await interaction.response.send_modal(TrackModal(callback, lang, 7, 'remove'))
        stop.callback = remove
        self.add_item(stop)
        refresh = discord.ui.Button(label=t(lang, 'track.button.refresh'), emoji='🔄', style=discord.ButtonStyle.secondary, row=1)
        async def refresh_list(interaction):
            await callback(interaction, action='list')
        refresh.callback = refresh_list
        self.add_item(refresh)
