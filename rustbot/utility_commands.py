"""Additional slash commands, separated from the interactive raid views."""
from datetime import datetime
import math
import discord
from discord import app_commands
from .servers import profile_id


def comparison(catalog, target: dict) -> list[str]:
    rows=[]
    for method,data in target.get('methods',{}).items():
        item=catalog.raw['items'][method]
        cost=catalog.materials(method,data['count'])
        sulfur=cost.get('sulfur',0) if cost else None
        cost_label=f'{sulfur:,} azufre' if sulfur is not None else 'costo no verificado'
        rows.append((sulfur is None,sulfur or 0,f"• **{item['name']}**: {data['count']:,} unidades · {cost_label}"))
    return [row[2] for row in sorted(rows)]


def register_utilities(bot, catalog, require_admin):
    async def targets(interaction,current: str):
        return [app_commands.Choice(name=t['name'][:100],value=k) for k,t in catalog.raw['targets'].items() if t.get('methods') and (current.casefold() in t['name'].casefold() or current.casefold() in k)][:25]

    async def methods(interaction,current: str):
        target=catalog.raid(getattr(interaction.namespace,'target','') or '')
        keys=target.get('methods',{}) if target else {m for t in catalog.raw['targets'].values() for m in t.get('methods',{})}
        return [app_commands.Choice(name=catalog.raw['items'][k]['name'][:100],value=k) for k in sorted(keys) if current.casefold() in catalog.raw['items'][k]['name'].casefold() or current.casefold() in k][:25]

    async def servers(interaction,current: str):
        return [app_commands.Choice(name=r['name'][:100],value=r['id']) for r in bot.directory.search(current)]

    def guild_watches(interaction):
        return [w for w in bot.store.watches() if (ch:=bot.get_channel(w.channel_id)) and ch.guild and ch.guild.id==interaction.guild_id]

    @bot.tree.command(name='ping',description='Comprueba la conexión del bot con Discord')
    async def ping(interaction):
        latency=bot.latency
        await interaction.response.send_message(f'Pong · {round(latency*1000)} ms' if math.isfinite(latency) else 'Conectando con Discord…',ephemeral=True)

    @bot.tree.command(name='status',description='Estado del bot, vigilancias y configuración de este Discord')
    async def status(interaction):
        if not await require_admin(interaction):return
        saved=bot.store.settings(interaction.guild_id)
        watches=guild_watches(interaction)
        online=sum(w.was_online==1 for w in watches);unknown=sum(w.was_online is None or not w.steamid.startswith('bm:') for w in watches)
        e=discord.Embed(title='Estado de RuxtBot',color=0xD5A522)
        e.add_field(name='Tracker',value='Ejecutándose' if bot.poll.is_running() else 'Detenido')
        e.add_field(name='Alertas',value='Activas' if not saved or saved[2] else 'Pausadas')
        e.add_field(name='Intervalo',value=f'{saved[3] if saved else bot.settings.poll_interval} s')
        e.add_field(name='Vigilancias',value=f'{len(watches)} total · {online} última lectura online · {unknown} sin datos',inline=False)
        e.add_field(name='Directorio',value=f'{len(bot.directory.rows)} servidores')
        e.set_footer(text='Último estado conocido; /player consulta una observación reciente.')
        await interaction.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name='servers',description='Busca y lista tus servidores por nombre con paginación')
    async def list_servers(interaction,query:str='',page:app_commands.Range[int,1,1000]=1):
        rows=[r for r in bot.directory.rows if query.casefold() in r['name'].casefold()]
        pages=max(1,math.ceil(len(rows)/10))
        if page>pages:
            await interaction.response.send_message(f'Solo hay {pages} página(s).',ephemeral=True);return
        lines=[f"• [{discord.utils.escape_markdown(r['name'])}](https://www.battlemetrics.com/servers/rust/{r['id']})" for r in rows[(page-1)*10:page*10]]
        e=discord.Embed(title=f'Servidores · {page}/{pages}',description='\n'.join(lines) or 'Sin coincidencias.',color=0xD5A522)
        e.set_footer(text='Usa /server o /track y selecciona el nombre. No necesitas copiar IDs.')
        await interaction.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name='syncservers',description='Importa servidores de un perfil BattleMetrics al selector')
    async def sync_servers(interaction,profile:str='https://www.battlemetrics.com/players/1128280744'):
        if not await require_admin(interaction):return
        await interaction.response.defer(ephemeral=True)
        try:
            pid=profile_id(profile);data=await bot.bm.profile(pid)
            rows=[{'id':r['id'],'name':r['attributes']['name'].strip()} for r in data.get('included',[]) if r.get('type')=='server' and r.get('relationships',{}).get('game',{}).get('data',{}).get('id')=='rust']
            if not rows:raise ValueError('El perfil no tiene servidores Rust accesibles.')
            bot.store.save_servers(rows);bot.directory.merge(rows)
            await interaction.followup.send(f'Importados/actualizados: {len(rows)} servidores. Usa /servers para verlos. Esto no activa vigilancias.',ephemeral=True)
        except ValueError as exc:await interaction.followup.send(str(exc),ephemeral=True)
        except Exception:await interaction.followup.send('No se pudo actualizar el directorio; revisa acceso a BattleMetrics.',ephemeral=True)

    async def toggle(interaction,enabled):
        if not await require_admin(interaction):return
        saved=bot.store.settings(interaction.guild_id) or (interaction.channel_id,'es',1,bot.settings.poll_interval)
        bot.store.set_settings(interaction.guild_id,saved[0],saved[1],enabled,saved[3])
        await interaction.response.send_message('Alertas reactivadas para cambios futuros.' if enabled else 'Alertas pausadas. Las vigilancias se conservan; no se enviarán avisos atrasados.',ephemeral=True)

    @bot.tree.command(name='pausealerts',description='Pausa alertas de este Discord sin borrar vigilancias')
    async def pause_alerts(interaction):await toggle(interaction,False)

    @bot.tree.command(name='resumealerts',description='Reactiva alertas para futuros cambios de presencia')
    async def resume_alerts(interaction):await toggle(interaction,True)

    @bot.tree.command(name='raidtools',description='Explora los métodos disponibles para un objetivo')
    @app_commands.autocomplete(target=targets)
    async def raid_tools(interaction,target:str):
        t=catalog.raid(target)
        if not t or not t.get('methods'):
            await interaction.response.send_message('Objetivo desconocido o pendiente de verificar.',ephemeral=True);return
        lines=[f"• **{catalog.raw['items'][k]['name']}** · {v['damage']:g} daño/unidad" for k,v in t['methods'].items()]
        e=discord.Embed(title=t['name'],description='\n'.join(lines),color=0xD5A522)
        e.set_footer(text='Consulta /raidcompare para costos y /raid para simular.')
        await interaction.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name='raidcompare',description='Compara cantidades y azufre de todos los métodos del objetivo')
    @app_commands.autocomplete(target=targets)
    async def raid_compare(interaction,target:str):
        t=catalog.raid(target)
        if not t or not t.get('methods'):
            await interaction.response.send_message('Objetivo desconocido o pendiente de verificar.',ephemeral=True);return
        e=discord.Embed(title=f"Comparar · {t['name']}",description='\n'.join(comparison(catalog,t)),color=0xD5A522)
        e.set_footer(text='Orden por azufre conocido; cero azufre no significa gratis. Equipo y reparaciones aparte.')
        await interaction.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name='raidplan',description='Calcula munición y materiales para varios objetivos iguales')
    @app_commands.autocomplete(target=targets,method=methods)
    async def raid_plan(interaction,target:str,method:str,quantity:app_commands.Range[int,1,100]=1):
        t=catalog.raid(target)
        if not t or method not in t.get('methods',{}):
            await interaction.response.send_message('Selecciona un objetivo y método disponibles.',ephemeral=True);return
        units=t['methods'][method]['count']*quantity
        mats=catalog.materials(method,units)
        cost='\n'.join(f'• {n:,} {catalog.raw["items"].get(k,{}).get("name",k)}' for k,n in mats.items()) or 'Costo no verificado; no significa gratis.'
        e=discord.Embed(title=f"Plan · {quantity} × {t['name']}",description=f"**{units:,} × {catalog.raw['items'][method]['name']}**\n\n{cost}",color=0xD5A522)
        e.set_footer(text='Objetivos completos, impactos separados; no descuenta splash. Equipo no incluido.')
        await interaction.response.send_message(embed=e,ephemeral=True)

    @bot.tree.command(name='wipe',description='Consulta el último y próximo wipe publicados por el servidor')
    @app_commands.autocomplete(server=servers)
    async def wipe(interaction,server:str):
        await interaction.response.defer(ephemeral=True)
        try:
            d=await bot.bm.server(bot.directory.resolve(server));a=d['attributes'];details=a.get('details',{})
            lines=[]
            for label,key in [('Último wipe','rust_last_wipe'),('Próximo wipe','rust_next_wipe')]:
                value=details.get(key)
                try:stamp=int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp());line=f'<t:{stamp}:F> · <t:{stamp}:R>'
                except (AttributeError,ValueError,TypeError):line='No publicado'
                lines.append(f'**{label}**: {line}')
            e=discord.Embed(title=a.get('name','Servidor'),description='\n'.join(lines),color=0xD5A522)
            e.set_footer(text='Horario publicado por BattleMetrics; puede cambiar.')
            await interaction.followup.send(embed=e,ephemeral=True)
        except Exception:await interaction.followup.send('No se pudo consultar el wipe de ese servidor.',ephemeral=True)

    # Apply the same discoverable target/method choices to the original simulator.
    bot.tree.get_command('raid').autocomplete('target')(targets)
    bot.tree.get_command('raid').autocomplete('method')(methods)
