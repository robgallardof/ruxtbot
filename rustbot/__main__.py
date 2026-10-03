from __future__ import annotations
import asyncio, logging
import time
from pathlib import Path
from .utility_commands import register_utilities, comparison
from .servers import ServerDirectory, profile_id
import discord
from discord import app_commands
from discord.ext import commands, tasks
from .config import Settings
from .catalog import Catalog
from .tracking import Store, valid_steamid64, transition
from .battlemetrics import BattleMetrics

YELLOW=0xD5A522
class RustBot(commands.Bot):
 def __init__(self, settings, catalog):
  super().__init__(command_prefix="!",intents=discord.Intents.default()); self.settings,self.catalog=settings,catalog; self.store=Store(settings.state_path); self.bm=BattleMetrics(settings.battlemetrics_token); self.directory=ServerDirectory(Path(settings.data_path).with_name("servers.json")); self.directory.merge(self.store.servers()); self.last_poll={}; self.poll.change_interval(seconds=10)
 async def setup_hook(self): await self.tree.sync(); self.poll.start()
 async def on_ready(self): logging.info("RuxtBot connected as %s", self.user)
 async def close(self):
  self.poll.cancel()
  await self.bm.client.aclose()
  self.store.conn.close()
  await super().close()
 @tasks.loop(seconds=10)
 async def poll(self):
  for w in self.store.watches():
   try:
    ch=self.get_channel(w.channel_id)
    if not ch or not ch.guild: continue
    saved=self.store.settings(ch.guild.id)
    interval=saved[3] if saved else self.settings.poll_interval
    key=(w.steamid,w.server_id,w.channel_id)
    if time.monotonic()-self.last_poll.get(key,0)<interval: continue
    self.last_poll[key]=time.monotonic()
    online=await self.bm.player_online(w.server_id,w.steamid)
    if online is None: continue
    event=transition(w.was_online,online)
    if event and (not saved or saved[2]):
     roles=[role for role in ch.guild.roles if role.name.casefold()=='wipe']
     if len(roles)!=1:
      logging.warning('Tracking alert waiting: guild %s needs exactly one wipe role',ch.guild.id)
      continue
     role=roles[0]
     if not role.mentionable and not ch.permissions_for(ch.guild.me).mention_everyone:
      logging.warning('Tracking alert waiting: wipe role is not mentionable in guild %s',ch.guild.id)
      continue
     label=discord.utils.escape_markdown(discord.utils.escape_mentions(w.label or w.steamid))
     name=discord.utils.escape_markdown(self.directory.name(w.server_id))
     await ch.send(f"{role.mention} {'🟢' if online else '🔴'} **{label}** {'se conectó a' if online else 'se desconectó de'} **{name}**.\nhttps://www.battlemetrics.com/servers/rust/{w.server_id}",allowed_mentions=discord.AllowedMentions(roles=[role],users=False,everyone=False))
    self.store.set_state(w,online)
   except Exception: logging.exception('tracker poll failed')
 @poll.before_loop
 async def before_poll(self): await self.wait_until_ready()

def embed(title, description): return discord.Embed(title=title,description=description,color=YELLOW)
def raid_embed(catalog, target: dict, method: str, used: int = 0):
 m=target['methods'][method]; count=m['count']; per=m['damage']; used=max(0,min(used,count))
 item=catalog.raw['items'][method]
 remaining=max(0,target['hp']-used*per); pct=round(100*remaining/target['hp']); bars=round(pct/10)
 state='✅ Objetivo destruido' if remaining==0 else '🎯 Objetivo en pie'
 e=embed(target['name'],f"**{state}**\n**Vida restante: {remaining:,.3f}/{target['hp']:,} HP**\n`{'█'*bars}{'░'*(10-bars)}` **{pct}% de vida**")
 e.color=discord.Color.green() if remaining==0 else discord.Color(YELLOW)
 e.add_field(name=item['name'],value=f"Usados: **{used:,}** · Faltan: **{max(0,count-used):,}**\nTotal estimado: **{count:,}** · Daño/unidad: **{per:g}**",inline=False)
 mats=catalog.materials(method,count)
 resources='\n'.join(f"• {n:,} {catalog.raw['items'].get(k,{}).get('name',k)}" for k,n in mats.items())
 e.add_field(name='Materiales para fabricar el total',value=(resources+'\nEquipo/lanzador no incluido; lotes completos de fabricación.') if resources else 'Costo no verificado; no significa gratis. Equipo/lanzador no incluido.',inline=False)
 e.add_field(name='Siguiente paso',value='Reinicia o compara otro método.' if remaining==0 else 'Usa «Aplicar 1» para avanzar o «Completar» para ver el resultado final. Cambiar método reinicia la simulación.',inline=False)
 e.add_field(name='Condiciones',value=target.get('notes','Estimación; colocación y splash pueden cambiar el resultado.'),inline=False)
 if target.get('source'): e.url=target['source']
 e.set_footer(text=f"{catalog.version} · Estimación comunitaria · No es tiempo real")
 return e
async def require_admin(interaction):
 if not interaction.guild or not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Solo administradores / Administrators only.",ephemeral=True); return False
 return True
class HelpView(discord.ui.View):
 def __init__(self):
  super().__init__(timeout=180)
 @discord.ui.button(label="Raid", style=discord.ButtonStyle.primary, emoji="💥")
 async def raid_button(self, interaction, _): await interaction.response.send_message("Use `/raid target:hqdoor` or `/raid target:garage-door`. / Usa `/raid target:hqdoor`.", ephemeral=True)
 @discord.ui.button(label="Craft", style=discord.ButtonStyle.secondary, emoji="🛠️")
 async def craft_button(self, interaction, _): await interaction.response.send_message("Use `/craft item:rocket quantity:100`. / Usa `/craft item:rocket quantity:100`.", ephemeral=True)
 @discord.ui.button(label="Sources", style=discord.ButtonStyle.secondary, emoji="📚")
 async def source_button(self, interaction, _): await interaction.response.send_message("Use `/sources` to view catalog version and confidence. / Usa `/sources`.", ephemeral=True)
class RaidTargetSelect(discord.ui.Select):
 def __init__(self, catalog, category):
  self.catalog=catalog
  options=[discord.SelectOption(label=t['name'][:100],value=key,description=(f"{t['hp']} HP" if 'hp' in t else "Pending verification")) for key,t in catalog.raw['targets'].items() if t.get('category') == category]
  super().__init__(placeholder="Choose a raid target / Elige objetivo",options=options)
 async def callback(self, interaction):
  target=self.catalog.raw['targets'][self.values[0]]
  if target.get('status') == 'pending_verification':
   await interaction.response.edit_message(embed=embed(target['name'],f"Pending verification after patch / pendiente de verificar tras el parche.\n\nData: {self.catalog.version}"),view=RaidBackButtonView(self.catalog)); return
  method=next(iter(target['methods']))
  await interaction.response.edit_message(embed=raid_embed(self.catalog,target,method),view=RaidProgressView(self.catalog,target,method))
class RaidCategorySelect(discord.ui.Select):
 def __init__(self,catalog):
  self.catalog=catalog
  labels={'doors':'Doors / Puertas','walls':'Walls / Muros','building':'Roofs & Floors / Techos y pisos','deployables':'Defense & Deployables / Defensa','siege':'Siege / Propano y cañones'}
  options=[discord.SelectOption(label=label,value=key,description=f"{sum(1 for t in catalog.raw['targets'].values() if t.get('category') == key)} targets") for key,label in labels.items()]
  super().__init__(placeholder="Choose category / Elige categoría",options=options)
 async def callback(self,interaction): await interaction.response.edit_message(embed=embed("Raid planner",f"Choose a target / elige objetivo. Data: {self.catalog.version}"),view=RaidTargetView(self.catalog,self.values[0]))
class RaidMethodSelect(discord.ui.Select):
 def __init__(self,catalog,target):
  self.catalog,self.target=catalog,target
  options=[discord.SelectOption(label=catalog.raw['items'][method]['name'][:100],value=method,description=f"{data['count']} unidades estimadas") for method,data in target['methods'].items()]
  super().__init__(placeholder="Change method / Cambiar método",options=options)
 async def callback(self,interaction): await interaction.response.edit_message(embed=raid_embed(self.catalog,self.target,self.values[0]),view=RaidProgressView(self.catalog,self.target,self.values[0]))
class RaidStartView(discord.ui.View):
 def __init__(self,catalog): super().__init__(timeout=180); self.add_item(RaidCategorySelect(catalog))
class RaidTargetView(discord.ui.View):
 def __init__(self,catalog,category): super().__init__(timeout=180); self.add_item(RaidTargetSelect(catalog,category)); self.add_item(RaidBackButton(catalog))
class RaidMethodView(discord.ui.View):
 def __init__(self,catalog,target):
  super().__init__(timeout=180); self.add_item(RaidMethodSelect(catalog,target)); self.add_item(RaidBackButton(catalog))
class DetonateButton(discord.ui.Button):
 def __init__(self,catalog,target,method,used):
  self.catalog,self.target,self.method,self.used=catalog,target,method,used; needed=target['methods'][method]['count']
  super().__init__(label=("Destroyed / Destruido" if used >= needed else "Aplicar 1"),style=(discord.ButtonStyle.success if used >= needed else discord.ButtonStyle.danger),disabled=used >= needed,emoji="💥")
 async def callback(self,interaction):
  next_used=self.used+1
  await interaction.response.edit_message(embed=raid_embed(self.catalog,self.target,self.method,next_used),view=RaidProgressView(self.catalog,self.target,self.method,next_used))
class CompleteRaidButton(discord.ui.Button):
 def __init__(self,catalog,target,method):
  super().__init__(label='Completar',style=discord.ButtonStyle.primary)
  self.catalog,self.target,self.method=catalog,target,method
 async def callback(self,interaction):
  count=self.target['methods'][self.method]['count']
  await interaction.response.edit_message(embed=raid_embed(self.catalog,self.target,self.method,count),view=RaidProgressView(self.catalog,self.target,self.method,count))
class ResetRaidButton(discord.ui.Button):
 def __init__(self,catalog,target,method): super().__init__(label="Reset / Reiniciar",style=discord.ButtonStyle.secondary); self.catalog,self.target,self.method=catalog,target,method
 async def callback(self,interaction): await interaction.response.edit_message(embed=raid_embed(self.catalog,self.target,self.method),view=RaidProgressView(self.catalog,self.target,self.method))
class CompareMethodsButton(discord.ui.Button):
 def __init__(self,catalog,target): super().__init__(label="Comparar costos",style=discord.ButtonStyle.secondary); self.catalog,self.target=catalog,target
 async def callback(self,interaction):
  lines=comparison(self.catalog,self.target)
  await interaction.response.send_message("**Methods / métodos**\n"+"\n".join(lines),ephemeral=True)
class RaidProgressView(discord.ui.View):
 def __init__(self,catalog,target,method,used=0):
  super().__init__(timeout=300); self.add_item(RaidMethodSelect(catalog,target)); self.add_item(DetonateButton(catalog,target,method,used)); self.add_item(CompleteRaidButton(catalog,target,method)); self.add_item(ResetRaidButton(catalog,target,method)); self.add_item(CompareMethodsButton(catalog,target)); self.add_item(RaidBackButton(catalog))
class RaidBackButton(discord.ui.Button):
 def __init__(self,catalog): super().__init__(label="Back / Volver",style=discord.ButtonStyle.secondary); self.catalog=catalog
 async def callback(self,interaction): await interaction.response.edit_message(content=None,embed=embed("Raid planner",f"Select a target. Data: {self.catalog.version}"),view=RaidStartView(self.catalog))
class RaidBackButtonView(discord.ui.View):
 def __init__(self,catalog): super().__init__(timeout=180); self.add_item(RaidBackButton(catalog))
def main():
 s=Settings.from_env(); logging.basicConfig(level=s.log_level); cat=Catalog.load(s.data_path); bot=RustBot(s,cat); rustwho_cooldowns: dict[int, float] = {}
 @bot.tree.command(description="Main menu / Menú principal")
 async def help(interaction): await interaction.response.send_message(embed=embed("RuxtBot",f"Raid, craft, items, servers and authorized tracking.\nData: **{cat.version}**\n`/raid /raidtools /raidcompare /raidplan /craft /item\n/server /servers /syncservers /wipe /player /rustwho\n/track /status /pausealerts /resumealerts /settings /ping /sources`"),view=HelpView(),ephemeral=True)
 @bot.tree.command(description="Find an item / Buscar ítem")
 async def item(interaction, query:str):
  found=cat.item(query); options=cat.matches(query)
  if not found: await interaction.response.send_message("Ambiguous or unknown / ambiguo o desconocido: " + ", ".join(x['id'] for x in options[:10]) if options else "No item found / ítem no encontrado",ephemeral=True); return
  await interaction.response.send_message(embed=embed(found['name'],f"`{found['id']}`\nAliases: {', '.join(found.get('aliases',[]))}\nData: {cat.version}"),ephemeral=True)
 @bot.tree.command(description="Craft calculator / Calculadora de fabricación")
 async def craft(interaction,item:str,quantity:app_commands.Range[int,1,100000]):
  found=cat.item(item)
  if not found or not found.get('recipe'): await interaction.response.send_message("Unknown or not craftable / desconocido o no fabricable.",ephemeral=True); return
  mats=cat.materials(found['id'],quantity); lines="\n".join(f"• {n:,} {k}" for k,n in mats.items()); inter=cat.intermediates(found['id'],quantity); mid="\n".join(f"• {n:,} {k}" for k,n in inter.items()) or "—"
  await interaction.response.send_message(embed=embed(f"{quantity:,} × {found['name']}",f"**Intermediates / intermedios**\n{mid}\n\n**Base resources & components / recursos y componentes**\n{lines}\n\nData: {cat.version}"),ephemeral=True)
 @bot.tree.command(description="Interactive raid estimate / Estimación de raid interactiva")
 async def raid(interaction,target:str|None=None,method:str="rocket"):
  if not target:
   await interaction.response.send_message(embed=embed("Raid planner",f"Select a target / elige un objetivo. Data: {cat.version}"),view=RaidStartView(cat)); return
  r=cat.raid(target)
  if not r or r.get('status') == 'pending_verification' or method not in r.get('methods',{}): await interaction.response.send_message("Target/method pending verification or unknown / objetivo o método pendiente de verificar.",ephemeral=True); return
  await interaction.response.send_message(embed=raid_embed(cat,r,method),view=RaidProgressView(cat,r,method))
 @bot.tree.command(description="Shared channel, language, alerts and polling / Ajustes")
 async def settings(interaction, language: str = "es", alerts: bool = True, interval_seconds: app_commands.Range[int,10,3600] = 10, channel: discord.TextChannel|None = None):
  if not await require_admin(interaction): return
  if language not in ("es", "en"): await interaction.response.send_message("Language must be `es` or `en`.",ephemeral=True); return
  target_channel=channel or interaction.channel
  bot.store.set_settings(interaction.guild_id, target_channel.id, language, alerts, interval_seconds)
  await interaction.response.send_message(f"Settings saved / ajustes guardados: channel=<#{target_channel.id}>, {language}, alerts={alerts}, interval={interval_seconds}s.",ephemeral=True)
 async def server_choices(interaction, current: str):
  return [app_commands.Choice(name=row['name'][:100],value=row['id']) for row in bot.directory.search(current)]
 @bot.tree.command(description="Estado del servidor; selecciona por nombre")
 @app_commands.autocomplete(server=server_choices)
 async def server(interaction,server:str):
  await interaction.response.defer(ephemeral=True)
  try:
   sid=bot.directory.resolve(server); d=await bot.bm.server(sid); a=d['attributes']
   await interaction.followup.send(embed=embed(a.get('name','Server'),f"Estado: {a.get('status')} | Jugadores: {a.get('players')}/{a.get('maxPlayers')}"),ephemeral=True)
  except Exception: await interaction.followup.send('No se pudo consultar el servidor. Selecciona su nombre y revisa BattleMetrics.',ephemeral=True)
 @bot.tree.command(description="Presencia por enlace de perfil BattleMetrics y nombre de servidor")
 @app_commands.autocomplete(server=server_choices)
 async def player(interaction,profile:str,server:str):
  await interaction.response.defer(ephemeral=True)
  try:
   online=await bot.bm.player_online(bot.directory.resolve(server),'bm:'+profile_id(profile))
   await interaction.followup.send({True:'🟢 Conectado',False:'🔴 Desconectado',None:'⚪ Estado desconocido; BattleMetrics no tiene una observación reciente.'}[online],ephemeral=True)
  except Exception: await interaction.followup.send('No se pudo consultar BattleMetrics.',ephemeral=True)
 @bot.tree.command(description="Public RustWho profile lookup / Consulta pública de RustWho")
 async def rustwho(interaction, steamid64: str):
  if not valid_steamid64(steamid64):
   await interaction.response.send_message("Invalid SteamID64.", ephemeral=True); return
  now=time.monotonic(); last=rustwho_cooldowns.get(interaction.user.id, 0); remaining=10-(now-last)
  if remaining > 0:
   await interaction.response.send_message(f"Try again in {int(remaining)} seconds / inténtalo en {int(remaining)} segundos.", ephemeral=True); return
  rustwho_cooldowns[interaction.user.id]=now
  await interaction.response.defer(ephemeral=True)
  try:
   profile=await bot.bm.rustwho_profile(steamid64); info=profile.get('steamInfo',{}); bans=profile.get('steamBans',{}); stats=profile.get('rustStats',{})
   fields=[f"SteamID64: `{steamid64}`",f"VAC bans: **{bans.get('vacBans','—')}** | Game bans: **{bans.get('gameBans','—')}**",f"K/D: **{stats.get('kd','—')}** | Kills: **{stats.get('kills','—')}** | Deaths: **{stats.get('deaths','—')}**",f"Accuracy: **{stats.get('accuracyPct','—')}%** | Headshots: **{stats.get('headshots','—')}**"]
   e=embed(info.get('name','RustWho profile'),"\n".join(fields)+"\n\nInformational only — not proof of cheating / información orientativa; no es prueba de trampas.")
   avatar=info.get('avatar')
   if avatar: e.set_thumbnail(url=avatar)
   e.url=f"https://www.rustwho.com/stats/{steamid64}"
   await interaction.followup.send(embed=e,ephemeral=True)
  except Exception:
   await interaction.followup.send("RustWho lookup is unavailable right now. Open the profile directly: https://www.rustwho.com/stats/"+steamid64,ephemeral=True)
 @bot.tree.command(description="Manage shared tracking / Gestionar vigilancias")
 @app_commands.choices(action=[app_commands.Choice(name='add',value='add'),app_commands.Choice(name='remove',value='remove'),app_commands.Choice(name='list',value='list')])
 @app_commands.autocomplete(server=server_choices)
 async def track(interaction,action:str,profile:str|None=None,server:str|None=None,label:str|None=None):
  if not await require_admin(interaction): return
  if action=='list':
   rows=[f"• {w.label or w.steamid} · {bot.directory.name(w.server_id)} → <#{w.channel_id}>" for w in bot.store.watches() if (bot.get_channel(w.channel_id) and bot.get_channel(w.channel_id).guild.id == interaction.guild_id)]
   await interaction.response.send_message(('\n'.join(rows) or 'No hay vigilancias.')[:1900],ephemeral=True); return
  if not profile:
   await interaction.response.send_message('Pega el enlace del perfil BattleMetrics del jugador. Elige el servidor por nombre o déjalo vacío para sus servidores conocidos.',ephemeral=True); return
  await interaction.response.defer(ephemeral=True)
  try:
   pid=profile_id(profile); saved=bot.store.settings(interaction.guild_id); channel_id=saved[0] if saved else interaction.channel_id
   data=await bot.bm.profile(pid) if action=='add' else None
   ids=[bot.directory.resolve(server)] if server else ([s['id'] for s in data.get('included',[]) if s.get('type')=='server' and s['id'] in {r['id'] for r in bot.directory.rows}] if data else [w.server_id for w in bot.store.watches() if w.steamid=='bm:'+pid and w.channel_id==channel_id])
   if not ids: raise ValueError('No hay servidores compartidos con el directorio importado.')
   if action=='add':
    roles=[r for r in interaction.guild.roles if r.name.casefold()=='wipe']
    if len(roles)!=1: raise ValueError('Debe existir exactamente un rol llamado wipe para las alertas.')
    name=label or data['data']['attributes'].get('name',pid)
    for sid in ids: bot.store.add('bm:'+pid,sid,channel_id,name)
    msg=f'Vigilancia activada en {len(ids)} servidor(es). Avisaré a @wipe cuando se conecte o desconecte. La primera lectura es silenciosa; datos no disponibles no generan falsas desconexiones.'
   else:
    for sid in ids: bot.store.remove('bm:'+pid,sid,channel_id)
    msg=f'Vigilancias eliminadas: {len(ids)}.'
   await interaction.followup.send(msg,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
  except ValueError as exc: await interaction.followup.send(str(exc),ephemeral=True)
  except Exception: await interaction.followup.send('No se pudo consultar BattleMetrics. No se han confirmado cambios.',ephemeral=True)
 @bot.tree.command(description="Data sources / Fuentes de datos")
 async def sources(interaction):
  meta=cat.raw['meta']; await interaction.response.send_message(embed=embed("Data sources",f"Version: **{meta['version']}**\nUpdated: {meta['updated']}\nConfidence: {meta['confidence']}\nSource: {meta['source']}"),ephemeral=True)
 register_utilities(bot,cat,require_admin)
 bot.run(s.discord_token)
if __name__=='__main__': main()
