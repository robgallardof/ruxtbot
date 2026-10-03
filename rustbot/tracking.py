"""Persistencia en SQLite: vigilancias, ajustes por Discord y servidores importados."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass

STEAMID64_MIN, STEAMID64_MAX = 76561197960265728, 99999999999999999


def valid_steamid64(value: str) -> bool:
    return value.isdigit() and STEAMID64_MIN <= int(value) <= STEAMID64_MAX


def transition(previous: bool | None, current: bool | None) -> str | None:
    """Evento a avisar entre dos lecturas. Sin base previa o sin dato actual no hay evento."""
    if current is None or previous is None or previous == current:
        return None
    return "connected" if current else "disconnected"


@dataclass
class Watch:
    steamid: str             # "bm:<id>" para perfiles BattleMetrics (los SteamID antiguos quedan sin datos)
    server_id: str
    channel_id: int
    label: str | None        # nombre que se muestra en el aviso
    was_online: bool | None  # última lectura conocida; None = aún sin base


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS watches(steamid TEXT,server_id TEXT,channel_id INTEGER,label TEXT,was_online INTEGER,PRIMARY KEY(steamid,server_id,channel_id))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS settings(guild_id INTEGER PRIMARY KEY,channel_id INTEGER,language TEXT,alerts INTEGER,poll_interval INTEGER)")
        self.conn.commit()

    # ── Vigilancias ──
    def add(self, steamid, server_id, channel_id, label=None):
        # Volver a añadir solo cambia la etiqueta: se conserva la última lectura para no generar avisos falsos.
        self.conn.execute("INSERT INTO watches VALUES(?,?,?,?,NULL) ON CONFLICT(steamid,server_id,channel_id) DO UPDATE SET label=excluded.label", (steamid, server_id, channel_id, label))
        self.conn.commit()

    def remove(self, steamid, server_id, channel_id):
        self.conn.execute("DELETE FROM watches WHERE steamid=? AND server_id=? AND channel_id=?", (steamid, server_id, channel_id))
        self.conn.commit()

    def watches(self):
        return [Watch(*r) for r in self.conn.execute("SELECT steamid,server_id,channel_id,label,was_online FROM watches")]

    def set_state(self, w, online):
        self.conn.execute("UPDATE watches SET was_online=? WHERE steamid=? AND server_id=? AND channel_id=?", (int(online), w.steamid, w.server_id, w.channel_id))
        self.conn.commit()

    # ── Ajustes por Discord ──
    def set_settings(self, guild_id, channel_id, language, alerts, poll_interval):
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?,?,?)", (guild_id, channel_id, language, int(alerts), poll_interval))
        self.conn.commit()

    def settings(self, guild_id):
        """(canal, idioma, alertas, intervalo) o None si el Discord nunca usó /settings."""
        return self.conn.execute("SELECT channel_id,language,alerts,poll_interval FROM settings WHERE guild_id=?", (guild_id,)).fetchone()

    # ── Servidores importados con /syncservers ──
    def save_servers(self, rows):
        self.conn.execute("CREATE TABLE IF NOT EXISTS server_directory(id TEXT PRIMARY KEY,name TEXT NOT NULL)")
        self.conn.executemany("INSERT INTO server_directory VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", [(r['id'], r['name']) for r in rows])
        self.conn.commit()

    def servers(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS server_directory(id TEXT PRIMARY KEY,name TEXT NOT NULL)")
        return [{'id': r[0], 'name': r[1]} for r in self.conn.execute("SELECT id,name FROM server_directory")]
