# Despliegue en Cybrancee

Este proyecto está preparado para el producto **Discord Bot Hosting → Python** de Cybrancee. No elijas una imagen Docker propia: el panel instala `requirements.txt` y ejecuta `bot.py`.

1. Crea un servidor **Python Discord Bot** y escoge Python 3.12 o posterior.
2. Sube todo el contenido de esta carpeta por SFTP o conecta un repositorio Git. No subas `.env` ni ningún token.
3. En **Startup**, configura `BOT PY FILE` como `bot.py` y `Requirements File` como `requirements.txt`.
4. En las variables de inicio/entorno del panel, crea:
   - `DISCORD_TOKEN`: el token de **Developer Portal → Bot → Reset Token**.
   - `BATTLEMETRICS_TOKEN`: opcional, requerido solo para comandos BattleMetrics.
   - `STEAM_API_KEY`: opcional; en `/who` añade horas de Rust y número exacto de juegos ([obtener clave](https://steamcommunity.com/dev/apikey)).
   - `RUST_TRACKER_STATE_PATH`: `rustbot.sqlite3`.
   - `RUST_POLL_INTERVAL_SECONDS`: `10`.
   - `RUST_LOG_LEVEL`: `INFO`.
   - `RUST_DATA_PATH`: `data/rust_catalog.yml`.
5. Inicia el servidor en la consola. Al primer arranque se registran los comandos de barra; Discord puede tardar unos minutos en mostrarlos.

## Secretos correctos

`DISCORD_TOKEN` es el **Bot Token**. El `Client Secret` y la clave pública de la aplicación no se usan para conectarse al Gateway de Discord y no deben ponerse en esta variable.
