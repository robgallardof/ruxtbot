# 🌗 Gamma NVIDIA · ve de noche en Rust

Script de **AutoHotkey v2** que sube el gamma del monitor con una tecla, para ver en las noches de Rust 🌙
-# 🟩 Solo gráficas **NVIDIA**, con el monitor conectado a la gráfica (no a la placa madre).

## ⌨️ Tus teclas
🔆 **{toggle}** → gamma alto / normal
🧯 **{reset}** → reset de emergencia (vuelve a 1.00)
-# 🎛️ ¿Otra tecla? Usa `/gamma key:` y `reset:` y descarga de nuevo. Elige una que no uses en Rust.

## 📥 Instalación
**1️⃣** Descarga **AutoHotkey v2** en <https://www.autohotkey.com> (botón **Download v2.0**) e instálalo.
**2️⃣** Toca ⬇️ **Descargar .ahk** abajo y guarda `gamma.ahk` (por ejemplo en Documentos).
-# 📋 ¿Prefieres copiarlo? Toca **Copiar código**, abre el Bloc de notas, pega todas las partes en orden y guarda como `gamma.ahk` con **Tipo: Todos los archivos** (si no, queda `gamma.ahk.txt`).
**3️⃣** Doble clic en `gamma.ahk` y en el aviso de Windows dale **Sí** 🛡️: el script se abre **como administrador** solo, si no, las teclas no jalan con Rust abierto.
**4️⃣** Aparece una **H** verde junto al reloj ✅. Entra a Rust (mejor en **Borderless / Pantalla completa sin bordes**) y presiona **{toggle}**.

## 🔁 Que arranque con Windows
**Win + R** → escribe `shell:startup` → Enter, y pega ahí un acceso directo a `gamma.ahk`.
-# 🛡️ Al prender la PC te pedirá permiso de administrador: dale **Sí**.

## ⚙️ Más o menos claro
Clic derecho en `gamma.ahk` → **Abrir con → Bloc de notas** y cambia este número (más alto = más claro):
```
HIGH_GAMMA   := 2.80
```
Guarda 💾 y en la **H** del reloj → **Reload Script**.

## 🛠️ Problemas
❌ **Failed to initialize NVIDIA NVAPI** → no es NVIDIA o el monitor está conectado a la gráfica integrada.
❌ **does not expose the required gamma correction function** → tu driver no trae esa función: actualiza el driver de NVIDIA.
⌨️ La tecla no hace nada en el juego → revisa que el script corra como admin (dale **Sí** al aviso) y pon Rust en Borderless.
🌞 Cerrar el script **no** regresa el gamma: presiona **{reset}** antes de salir (clic derecho en la **H** → **Exit**).
-# ⚠️ Úsalo bajo tu propio riesgo: no toca el juego, solo el gamma del monitor.
