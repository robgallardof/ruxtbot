# Fuentes y alcance del catálogo

Consulta: 2026-10-02. PC vanilla; los multiplicadores de servidores modificados no están incluidos.

- [Puerta blindada](https://wiki.rustclash.com/item/armored-door): 1000 HP, 440 por C4, 3 cargas. Sustituye el dato antiguo de 800 HP.
- [Puerta de madera](https://wiki.rustclash.com/item/wooden-door), [metal](https://wiki.rustclash.com/item/sheet-metal-door), [garaje](https://wiki.rustclash.com/item/garage-door).
- Muros: [madera](https://wiki.rustclash.com/building/wooden-wall), [piedra](https://wiki.rustclash.com/building/stone-wall), [metal](https://wiki.rustclash.com/building/metal-wall), [blindado](https://wiki.rustclash.com/building/armored-wall). Se usa lado duro; no extrapolar automáticamente a pisos o techos.
- Recetas oficiales: [explosivos](https://wiki.facepunch.com/rust/item/explosives), [satchel](https://wiki.facepunch.com/rust/item/explosive.satchel), [beancan](https://wiki.facepunch.com/rust/item/grenade.beancan), [F1](https://wiki.facepunch.com/rust/item/grenade.f1), [munición explosiva](https://wiki.facepunch.com/rust/item/ammo.rifle.explosive), [molotov](https://wiki.facepunch.com/rust/item/grenade.molotov).
- Recetas adicionales: [rocket](https://wiki.rustclash.com/item/rocket), [HV](https://wiki.rustclash.com/item/high-velocity-rocket), [incendiario](https://wiki.rustclash.com/item/incendiary-rocket), [propano](https://wiki.rustclash.com/item/propane-explosive-bomb), [mortero](https://wiki.rustclash.com/item/mortar-shell), [cañón](https://wiki.rustclash.com/item/cannonball), [ballesta](https://wiki.rustclash.com/item/hammerhead-bolt).

Las tablas de durabilidad son comunitarias, no pruebas ejecutadas en el juego. Cada objetivo lleva su URL. Cantidad = techo(HP / daño), con pruebas que impiden declarar destrucción antes de tiempo. La munición explosiva usa Assault Rifle; las granadas se fijan al objetivo. Propano plantado y lanzado son métodos distintos. Molotov e incendiario son estimaciones variables por fuego. Un golpe del ariete no equivale a fabricar un ariete nuevo.

Costos de munición: lotes enteros, sin inventario previo, componentes adquiridos (tubos, combustible, cuerda, tanque) no descompuestos en sus propias recetas. No incluyen fabricar, reparar ni operar el lanzador/arma. MLRS, HE, ariete y handmade shell conservan costo no verificado; no se presentan como gratis. Pisos, techos y desplegables que no se verificaron siguen marcados como pendientes.

## Servidores

`data/servers.json` contiene 75 nombres/IDs recuperados mediante la API autenticada del perfil solicitado, más los tres enlaces explícitos (ya presentes). No contiene tokens, direcciones IP ni historial de sesiones. Los nombres pueden cambiar con cada wipe.

El tracker utiliza `GET /players/{id}?include=server`, `included[type=server].meta.online`. Solo acepta valores booleanos con servidor online, consulta válida y actualización de menos de cinco minutos. Los datos ausentes, privados, antiguos, errores y límites de API conservan la última observación: no equivalen a desconexión. La revisión cada 10 segundos no garantiza que BattleMetrics publique cambios cada 10 segundos.

Las vigilancias antiguas de SteamID deben reemplazarse con `/track add profile:<enlace BattleMetrics>`; no es seguro convertir SteamID en ID BattleMetrics por coincidencias de texto. La primera observación es silenciosa. El envío se reintenta si Discord falla antes de guardar estado; una caída entre envío y guardado puede duplicar una alerta. No se promete entrega exactamente una vez.

## /who

Fuentes públicas consultadas en paralelo; si una falla, el resto se muestra y el pie indica cuál no respondió:

- Steam Community: `/profiles/{id}?xml=1` (estado, baneo VAC, tradeo, cuenta limitada, ubicación), la página del perfil (nivel, juegos, insignias), `/ajaxaliases` (nombres anteriores) y `/id/{vanity}?xml=1` para URLs personalizadas.
- Formatos SteamID calculados localmente con la misma fórmula que steamid.io.
- RustWho: `fetch-v1.rustwho.com/stats/public/{id}` (baneos, bans en servidores, historial de nombres, estadísticas de Rust). Son estadísticas de Steam: orientativas, no prueba de trampas.
- BattleMetrics: `GET /players/{id}?include=server,identifier` cuando se pasa el enlace del perfil. Sin enlace, `filter[search]` por nombre exacto solo muestra candidatos sin verificar.
- Steam Web API (`IPlayerService/GetOwnedGames`) solo con `STEAM_API_KEY`.
- SteamDB devuelve 403 a clientes automatizados; se enlaza su calculadora (`?cc=mx`) en lugar de extraer datos.
