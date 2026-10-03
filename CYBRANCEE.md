# Deploying on Cybrancee

This project targets Cybrancee's **Discord Bot Hosting → Python** product. Do not pick a custom Docker image: the panel installs `requirements.txt` and runs `bot.py`.

1. Create a **Python Discord Bot** server with Python 3.12 or newer.
2. Upload this folder over SFTP or connect the Git repository. Never upload `.env` or any token.
3. In **Startup**, set `BOT PY FILE` to `bot.py` and `Requirements File` to `requirements.txt`.
4. In the panel's startup/environment variables, create:
   - `DISCORD_TOKEN`: the token from **Developer Portal → Bot → Reset Token**.
   - `BATTLEMETRICS_TOKEN`: optional, required for BattleMetrics commands.
   - `STEAM_API_KEY`: optional; adds Rust hours and exact game count to `/who` ([get a key](https://steamcommunity.com/dev/apikey)).
   - `RUST_TRACKER_STATE_PATH`: `rustbot.sqlite3`.
   - `RUST_POLL_INTERVAL_SECONDS`: `10`.
   - `RUST_LOG_LEVEL`: `INFO`.
   - `BOT_OWNER_IDS`: optional, comma-separated Discord user IDs that may use `/update` and `/restart` (the application owner always can).
   - `RUST_DATA_PATH`: `data/rust_catalog.yml` (`data/raid.json` and `data/servers.json` are read from the same folder).
5. Start the server from the console. Slash commands are registered on first start; Discord can take a few minutes to show them.

## The right secret

`DISCORD_TOKEN` is the **Bot Token**. The application's Client Secret and Public Key are not used to connect to the Discord Gateway and must not go in this variable.

## Updating

With the Git integration, `/update` in Discord pulls the latest commit and restarts the bot (bot owner only); `/version` shows the commit that is running. Without git (files uploaded over SFTP), upload the new files and restart from the panel.
