# 🤖 RUXTBOT — MOVIMIENTO, COMBATE Y FOV

> ⚠️ Puedes cambiar cualquier tecla por la que quieras.
> Ejemplo: `bind q` → `bind z`, `bind mouse4`, `bind f5`, etc.

## 🏃 MOVIMIENTO

**🏃 Auto Run**
```
bind q forward;sprint
```

**🏊 Auto Nadar**
```
bind l forward;sprint;jump
```

**🧎 Auto Crouch al saltar**
```
input.autocrouch true
```

**⛏️ Pegar + agacharse automático**
```
bind p attack;duck
```

**🛡️ Pegar + agacharse mientras mantienes la tecla**
```
bind b +attack;+duck
```

## 🎯 FOV / AIM

**🔭 Zoom FOV**

> Mantén la tecla para hacer zoom y suéltala para volver al FOV normal.

```
bind x +meta.if_true "graphics.fov 70";+meta.if_false "graphics.fov 90"
```

**🔫 Ajustar FOV del arma**
```
graphics.vm_fov_scale false
```

**↩️ Restaurar FOV del arma**
```
graphics.vm_fov_scale true
```

## 🔦 LÁSER / LINTERNA

**💡 Encender al apuntar**
```
bind mouse1 +lighttoggle;+attack2
```

## 💧 AGUA

**🌊 Cambiar calidad del agua**
```
bind j +meta.if_true "water.quality 2";+meta.if_false "water.quality -1"
```

## 💥 COMBAT LOG

**📋 Abrir consola + Combat Log**
```
bind f2 "consoletoggle;clear;combatlog"
```

## 🖐️ CAMBIAR ARMA DE MANO

**🔄 Izquierda / Derecha**
```
bind k ~graphics.vm_horizontal_flip 0;graphics.vm_horizontal_flip 1
```


# 🤖 RUXTBOT — AUDIO, AIM Y RENDIMIENTO

## 🔊 AUDIO

**🔉 Bajar volumen**
```
bind f10 "audio.master 0.1"
```

**🔊 Subir volumen**
```
bind f11 "audio.master 1"
```

**🎮 Solo volumen del juego**
```
bind f10 "audio.game 0.15"
bind f11 "audio.game 1"
```

## 🖱️ SENSIBILIDAD

**🎯 Sensibilidad diferente al apuntar**
```
bind mouse1 "+attack2;+input.sensitivity .6;input.sensitivity .3"
```

> `.6` = apuntando
> `.3` = sensibilidad normal
> Puedes cambiar ambos valores.

## 👁️ LOOK RADIUS

**🎯 Punto de interacción pequeño**
```
client.lookatradius 0.01
```

**🔄 Alternar pequeño / grande**
```
bind f5 ~client.lookatradius 0.01;client.lookatradius 20
```

## ⚡ FPS / RENDIMIENTO

**🧹 Limpiar memoria**
```
gc.collect
```

**⌨️ Limpiar memoria con tecla**
```
bind f9 gc.collect
```

**🧠 Garbage Collector incremental**
```
gc.incremental_milliseconds 1
```

**💥 Reducir escombros**
```
effects.maxgibs -1
```

**🚀 Quitar límite de FPS**
```
fps.limit -1
```

**🎮 Limitar a 180 FPS**
```
fps.limit 180
```

## 🎥 MOVIMIENTO DE CABEZA

**👀 Reducir movimiento**
```
client.headlerp 5
```

**🧊 Reducir inercia**
```
client.headlerp_inertia false
```

**↩️ Restaurar**
```
client.headlerp_inertia true
```


# 🤖 RUXTBOT — ITEMS, CHAT Y UTILIDADES

## 🎒 ITEMS

**🩹 Craftear 1 venda**
```
bind h "craft.add -2072273936 1"
```

**🩹 Craftear 2 vendas**
```
bind mousewheelup "craft.add -2072273936 2"
```

**🎰 Alternar Slot 1 / Slot 2**
```
bind mouse3 ~+slot1;+slot2
```

## ☠️ SUICIDIO / RESPAWN

**💀 Respawn rápido**
```
bind [leftshift+k] kill
```

## 💬 CHAT

**🌍 Mensaje global**
```
bind 7 chat.say "TU MENSAJE"
```

**👥 Mensaje al equipo**
```
bind 8 chat.teamsay "TU MENSAJE"
```

## 🔧 SERVIDORES MODDED

**🏠 Home**
```
bind f5 chat.say "/home 1"
```

**✅ Aceptar TP**
```
bind f6 chat.say "/tpa"
```

**❌ Cancelar TP**
```
bind f7 chat.say "/tpc"
```

**🔨 Remove**
```
bind f8 chat.say "/remove"
```

## ⚙️ OTROS

**⚡ Menos tiempo manteniendo E**
```
input.holdtime 0.1
```

**🎥 Streamer Mode**
```
streamermode 1
```

## 🎨 GAMETIP / TEXTO PERSONALIZADO

```
bind mouse1 "+attack2;+gametip.hidegametip;gametip.showgametip \"<#ff0000>On Live: <#00ff00>M2cGTTV\""
```

## 🗑️ QUITAR UN BINDEO

**Ejemplo**
```
unbind q
```

## 💾 GUARDAR CONFIGURACIÓN

```
writecfg
```

## 🧠 RECUERDA

Puedes cambiar cualquier tecla:

`bind q ...` → `bind z ...`
`bind f5 ...` → `bind mouse4 ...`
`bind p ...` → `bind x ...`
