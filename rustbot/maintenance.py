"""/version, /update and /restart.

/version is for everyone: bot version, the exact commit it runs, uptime and connection health.
/update and /restart are for the bot owner only (the Discord application owner, or IDs listed in
BOT_OWNER_IDS): /update runs `git pull --ff-only`, reinstalls requirements only when requirements.txt
changed, and restarts the process in place. Only fixed commands run; nothing the user types reaches a shell.
"""
from __future__ import annotations
import asyncio
import logging
import os
import platform
import shutil
import sys
import time
from pathlib import Path
import discord
from discord import app_commands
from . import __version__
from .i18n import lang_for, t
from .ui import GREEN, ORANGE, YELLOW, OwnedView, error_embed

ROOT = Path(__file__).resolve().parents[1]
STARTED = time.time()


async def run(*args: str, timeout: float = 120) -> tuple[int, str]:
    """Run a fixed command in the repository; returns (exit code, combined output). Never uses a shell."""
    proc = await asyncio.create_subprocess_exec(*args, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, 'timeout'
    return proc.returncode, out.decode('utf-8', 'replace').strip()


def is_checkout() -> bool:
    return bool(shutil.which('git')) and (ROOT / '.git').exists()


async def git_info() -> dict:
    """Commit, date, subject and branch of the running copy (empty when it is not a git checkout)."""
    if not is_checkout():
        return {}
    code, out = await run('git', 'log', '-1', '--format=%h%x1f%ct%x1f%s', timeout=10)
    if code != 0 or '\x1f' not in out:
        return {}
    commit, stamp, subject = out.split('\x1f', 2)
    _, branch = await run('git', 'rev-parse', '--abbrev-ref', 'HEAD', timeout=10)
    return {'commit': commit, 'date': int(stamp), 'subject': subject, 'branch': branch}


def uptime() -> str:
    seconds = int(time.time() - STARTED)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    return (f'{days} d ' if days else '') + f'{hours} h {rest // 60} min'


def restart_argv() -> list[str]:
    """Same interpreter and entry point: `python bot.py` or `python -m rustbot`."""
    if sys.argv and sys.argv[0].endswith('__main__.py'):
        return [sys.executable, '-m', 'rustbot', *sys.argv[1:]]
    return [sys.executable, *sys.argv]


async def restart(bot, delay: float = 1.5):
    """Close the bot cleanly and replace the process with a fresh copy of itself."""
    await asyncio.sleep(delay)
    logging.warning('Restarting RuxtBot: %s', restart_argv())
    await bot.close()
    os.execv(sys.executable, restart_argv())


async def is_bot_owner(interaction) -> bool:
    extra = {int(x) for x in os.environ.get('BOT_OWNER_IDS', '').replace(' ', '').split(',') if x.isdigit()}
    if interaction.user.id in extra:
        return True
    try:
        return await interaction.client.is_owner(interaction.user)
    except Exception:
        return False


async def update(bot) -> tuple[str, str, bool]:
    """(status key, details, restart needed) after pulling the latest code."""
    if not is_checkout():
        return 'update.no_git', '', False
    _, before = await run('git', 'rev-parse', 'HEAD', timeout=10)
    code, out = await run('git', 'pull', '--ff-only', timeout=180)
    if code != 0:
        return 'update.failed', out[-900:], False
    _, after = await run('git', 'rev-parse', 'HEAD', timeout=10)
    if before == after:
        return 'update.current', '', False
    _, changed = await run('git', 'diff', '--name-only', before, after, timeout=10)
    _, log = await run('git', 'log', '--format=• %h %s', f'{before}..{after}', timeout=10)
    if 'requirements.txt' in changed.split():
        code, pip = await run(sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', timeout=600)
        if code != 0:
            return 'update.pip_failed', pip[-900:], False
    return 'update.done', log[:900], True


def register_maintenance(bot):
    async def version_embed(lang) -> discord.Embed:
        info = await git_info()
        e = discord.Embed(title=t(lang, 'version.title', v=__version__), color=YELLOW)
        if info:
            e.add_field(name=t(lang, 'version.commit'), value=f"`{info['commit']}` · {discord.utils.escape_markdown(info['subject'][:120])}\n-# {info['branch']} · <t:{info['date']}:R>", inline=False)
        else:
            e.add_field(name=t(lang, 'version.commit'), value=t(lang, 'version.no_git'), inline=False)
        latency = bot.latency * 1000 if bot.latency == bot.latency and bot.latency != float('inf') else None
        e.add_field(name=t(lang, 'version.uptime'), value=uptime())
        e.add_field(name=t(lang, 'version.ping'), value=f'{latency:.0f} ms' if latency is not None else '—')
        e.add_field(name=t(lang, 'version.servers'), value=str(len(bot.guilds)))
        e.add_field(name=t(lang, 'version.commands'), value=str(len(bot.tree.get_commands())))
        e.add_field(name=t(lang, 'version.bm'), value='✅' if bot.bm.token else '—')
        e.set_footer(text=f'Python {platform.python_version()} · discord.py {discord.__version__}')
        return e

    def owner_view(lang, owner_id) -> OwnedView:
        view = OwnedView(owner_id)
        pull = discord.ui.Button(label=t(lang, 'update.button.pull'), emoji='⬇️', style=discord.ButtonStyle.primary)

        async def do_pull(i):
            await updatecmd.callback(i)
        pull.callback = do_pull
        again = discord.ui.Button(label=t(lang, 'update.button.restart'), emoji='♻️', style=discord.ButtonStyle.danger)

        async def do_restart(i):
            await restartcmd.callback(i)
        again.callback = do_restart
        view.add_item(pull)
        view.add_item(again)
        return view

    @bot.tree.command(name='version', description='🏷️ Bot version, running commit and uptime')
    async def version(interaction: discord.Interaction):
        lang = lang_for(interaction)
        await interaction.response.defer(ephemeral=True)
        embed = await version_embed(lang)
        if await is_bot_owner(interaction):
            embed.set_footer(text=embed.footer.text + ' · ' + t(lang, 'version.owner'))
            view = owner_view(lang, interaction.user.id)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name='update', description='⬇️ Pull the latest bot code and restart (bot owner)')
    @app_commands.default_permissions(administrator=True)
    async def updatecmd(interaction: discord.Interaction):
        lang = lang_for(interaction)
        if not await is_bot_owner(interaction):
            await interaction.response.send_message(embed=error_embed(t(lang, 'update.owner'), lang=lang), ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        key, details, needs_restart = await update(bot)
        e = discord.Embed(description=t(lang, key), color=GREEN if key in ('update.done', 'update.current') else ORANGE)
        if details:
            e.add_field(name=t(lang, 'update.details'), value=f'```\n{details}\n```'[:1024], inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)
        if needs_restart:
            asyncio.create_task(restart(bot))

    @bot.tree.command(name='restart', description='♻️ Restart the bot (bot owner)')
    @app_commands.default_permissions(administrator=True)
    async def restartcmd(interaction: discord.Interaction):
        lang = lang_for(interaction)
        if not await is_bot_owner(interaction):
            await interaction.response.send_message(embed=error_embed(t(lang, 'update.owner'), lang=lang), ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(description=t(lang, 'update.restarting'), color=ORANGE), ephemeral=True)
        asyncio.create_task(restart(bot))
