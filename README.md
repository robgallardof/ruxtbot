# RuxtBot

RuxtBot es un bot profesional de Discord para cálculos de raid/crafting, datos de servidores y seguimiento autorizado mediante BattleMetrics. El catálogo se mantiene separado de la lógica: tras cada wipe o parche, revisa `data/rust_catalog.yml`, ajusta su versión, fecha, fuente y confianza, y ejecuta las pruebas.

## Instalación en Fedora

1. Instala Docker Engine y el complemento Compose siguiendo la documentación de Fedora/Docker; habilita el servicio Docker y añade tu usuario al grupo `docker` si procede.
2. Copia `.env.example` a `.env` y define `DISCORD_TOKEN`. Añade `BATTLEMETRICS_TOKEN` para `/server`, `/player` y `/track`.
3. Ejecuta `docker compose up -d --build` desde esta carpeta. El volumen `rustbot-data` conserva vigilancias y estado entre actualizaciones.
4. Tras editar datos o código: `docker compose up -d --build`. La imagen corre como usuario sin privilegios, se reinicia automáticamente y contiene un healthcheck.

## Conectar Discord

1. Crea una aplicación y un bot en el [Discord Developer Portal](https://discord.com/developers/applications), y copia su token en `DISCORD_TOKEN` dentro de `.env`.
2. En **OAuth2 → URL Generator**, selecciona los scopes `bot` y `applications.commands`; concede al bot permisos de enviar mensajes, usar comandos de aplicación y adjuntar enlaces.
3. Abre la URL generada, añade el bot a tu servidor y arranca el contenedor. Los comandos globales pueden tardar unos minutos en aparecer.

Para alojarlo en el panel de Cybrancee, sigue [CYBRANCEE.md](CYBRANCEE.md); ese proveedor ejecuta el proyecto directamente con Python y no requiere Docker.

## Comandos

`/help`, `/raid`, `/craft`, `/item`, `/server`, `/player`, `/who`, `/track`, `/settings` y `/sources` están disponibles desde el registro de comandos de Discord. `/track` está limitado a administradores; usa `add`, `remove` o `list`. La primera lectura crea una base silenciosa y solo se avisa ante transiciones posteriores. `/settings` permite fijar el canal de alertas, idioma, activación de alertas e intervalo. `/who` es una consulta pública bajo demanda, efímera y limitada a una por usuario cada 10 segundos; no se usa para vigilancias ni alertas.

## Datos y límites

Cada respuesta expone la versión del catálogo. Los valores de daño incluidos tienen confianza mixta y deben comprobarse tras un parche; objetivos no incluidos se declaran **pendientes de verificar**, nunca se inventan. BattleMetrics puede limitar o rechazar peticiones: el cliente usa reintentos con backoff y no expone detalles internos al usuario.

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. pytest
```

El avatar original está en `assets/rustbot-mascot.png`. No contiene logos ni assets de Rust.

## Nuevo flujo de raideo y tracking

- `/raid`: elige categoría, objetivo y método. La barra representa **vida restante**. «Aplicar 1», «Completar», «Reiniciar» y «Comparar» permiten explorar el resultado. Cambiar método reinicia el cálculo.
- `/server server:`: escribe parte del nombre y selecciona una sugerencia; no necesitas IDs.
- `/player profile:<URL de BattleMetrics> server:<nombre>`: consulta presencia explícita o estado desconocido.
- `/track action:add profile:<URL de BattleMetrics> server:<nombre>`: avisa de conexión y desconexión al rol **wipe**. Sin servidor, vigila los servidores conocidos del jugador que están en el directorio importado. `remove` admite el mismo flujo. `list` muestra las vigilancias del Discord actual.
- Debe existir exactamente un rol `wipe`, y ser mencionable o el bot debe poder mencionarlo en el canal. El comando es solo para administradores. No se permite mencionar otros roles ni `@everyone` desde datos del jugador.
- `/who jugador:<SteamID64 o enlace> battlemetrics:<URL opcional>`: ficha completa del jugador (reemplaza a `/rustwho`). Acepta SteamID64, `STEAM_0:X:Y`, `[U:1:N]`, URL personalizada o enlaces de Steam, steamid.io, SteamDB, RustWho y BattleMetrics. Muestra:
  - 👤 **Steam**: estado, país, todos los formatos de SteamID (como steamid.io), fecha de creación, nivel, juegos, insignias y cuenta limitada.
  - 🛡️ **Baneos**: VAC, game bans, comunidad, tradeo y bans en servidores (RustWho).
  - 📝 **Nombres usados**: historial fusionado de Steam, RustWho y BattleMetrics con fecha y fuente.
  - 🦀 **Rust** (RustWho): PvP, disparos, construcción, recolección y mundo.
  - 📊 **BattleMetrics**: horas totales, servidores, primer registro y los más jugados. Sin el enlace `battlemetrics:` solo sugiere perfiles con el mismo nombre (sin verificar), porque la API pública no permite convertir SteamID en jugador BattleMetrics.
  - Botones a Steam, SteamID I/O, SteamDB (calculadora en MXN), RustWho y BattleMetrics. SteamDB bloquea bots, por eso el valor de la cuenta se abre allí.
  - `STEAM_API_KEY` (opcional) añade horas jugadas en Rust y conteo exacto de juegos.
- `/settings interval_seconds:10` guarda el intervalo por Discord. Nuevas instalaciones usan 10 segundos; configuraciones anteriores conservan su valor hasta cambiarlas.

Consulta [SOURCES.md](SOURCES.md) para fuentes, correcciones de recetas, 75 servidores importados y límites de las observaciones. No se han enviado mensajes de prueba a Discord ni desplegado esta versión automáticamente.

## Comandos adicionales

| Comando | Uso |
| --- | --- |
| `/servers query:moose page:1` | Directorio por nombre, 10 resultados por página |
| `/syncservers profile:<enlace>` | Importa y actualiza nombres desde BattleMetrics; persiste en SQLite |
| `/status` | Estado del tracker, intervalo y últimas lecturas del Discord actual |
| `/ping` | Latencia de la conexión con Discord |
| `/wipe server:<nombre>` | Último/próximo wipe publicado, en la zona horaria de Discord |
| `/pausealerts` | Silencia avisos sin borrar vigilancias |
| `/resumealerts` | Reactiva avisos para cambios futuros |
| `/raidtools target:<objetivo>` | Métodos y daño estimado |
| `/raidcompare target:<objetivo>` | Compara cantidades y azufre conocido |
| `/raidplan target:<objetivo> method:<método> quantity:2` | Materiales para múltiples objetivos, sin asumir splash compartido |

`/syncservers`, `/status`, `/pausealerts` y `/resumealerts` son solo para administradores. Las importaciones amplían el directorio compartido del bot, pero no crean vigilancias automáticamente. Los comandos de raideo ofrecen autocompletado de objetivos y métodos.

### Validación de esta versión

34 pruebas automatizadas: recetas y lotes, invariantes de daño, límites de componentes Discord, presencia explícita/frescura, backoff, transiciones y mención del rol, fallo de envío, almacenamiento y registro de los 20 comandos. Se consultó el perfil real y los tres servidores solicitados por API de solo lectura. Falta la comprobación en el Discord de destino tras desplegar/reiniciar el bot; no se ha iniciado una segunda instancia local.
