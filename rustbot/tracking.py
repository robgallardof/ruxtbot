"""SQLite persistence: watches, per-guild settings, imported servers and the player book."""
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass

STEAMID64_MIN, STEAMID64_MAX = 76561197960265728, 99999999999999999


def valid_steamid64(value: str) -> bool:
    return value.isdigit() and STEAMID64_MIN <= int(value) <= STEAMID64_MAX


def transition(previous: bool | None, current: bool | None) -> str | None:
    """Event to announce between two readings. No baseline or no current data means no event."""
    if current is None or previous is None or previous == current:
        return None
    return "connected" if current else "disconnected"


@dataclass
class Watch:
    steamid: str             # "bm:<id>" for BattleMetrics profiles (legacy SteamID watches stay "no data")
    server_id: str
    channel_id: int
    label: str | None        # name shown in the alert
    was_online: bool | None  # last known reading; None = no baseline yet
    owner_id: int = 0
    expires_at: float = 0


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS watches(steamid TEXT,server_id TEXT,channel_id INTEGER,label TEXT,was_online INTEGER,PRIMARY KEY(steamid,server_id,channel_id))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS settings(guild_id INTEGER PRIMARY KEY,channel_id INTEGER,language TEXT,alerts INTEGER,poll_interval INTEGER)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS identities(steamid TEXT PRIMARY KEY,bm_id TEXT NOT NULL,verified_at REAL NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS players(scope INTEGER,ref TEXT,name TEXT,steamid TEXT,bm_id TEXT,used_at REAL,PRIMARY KEY(scope,ref))")
        columns = {r[1] for r in self.conn.execute('PRAGMA table_info(watches)')}
        if 'owner_id' not in columns:
            self.conn.execute('ALTER TABLE watches ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 0')
        if 'expires_at' not in columns:
            self.conn.execute('ALTER TABLE watches ADD COLUMN expires_at REAL NOT NULL DEFAULT 0')
        self.conn.execute('UPDATE watches SET expires_at=? WHERE expires_at=0', (time.time()+7*86400,))
        self.conn.commit()

    # ── Watches ──
    def add(self, steamid, server_id, channel_id, label=None, owner_id=0, days=7):
        if not 1 <= days <= 15:
            raise ValueError('days must be between 1 and 15')
        # Re-adding only updates the label: the last reading is kept so no false alert is sent.
        self.conn.execute("INSERT INTO watches(steamid,server_id,channel_id,label,was_online,owner_id,expires_at) VALUES(?,?,?,?,NULL,?,?) ON CONFLICT(steamid,server_id,channel_id) DO UPDATE SET label=excluded.label,expires_at=excluded.expires_at", (steamid, server_id, channel_id, label, owner_id, time.time()+days*86400))
        self.conn.commit()

    def remove(self, steamid, server_id, channel_id):
        self.conn.execute("DELETE FROM watches WHERE steamid=? AND server_id=? AND channel_id=?", (steamid, server_id, channel_id))
        self.conn.commit()

    def watches(self):
        self.conn.execute('DELETE FROM watches WHERE expires_at<=?', (time.time(),))
        self.conn.commit()
        return [Watch(*r) for r in self.conn.execute("SELECT steamid,server_id,channel_id,label,was_online,owner_id,expires_at FROM watches")]


    def set_state(self, w, online):
        self.conn.execute("UPDATE watches SET was_online=? WHERE steamid=? AND server_id=? AND channel_id=?", (int(online), w.steamid, w.server_id, w.channel_id))
        self.conn.commit()

    # ── Per-guild settings ──
    def set_settings(self, guild_id, channel_id, language, alerts, poll_interval):
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES(?,?,?,?,?)", (guild_id, channel_id, language, int(alerts), poll_interval))
        self.conn.commit()

    def settings(self, guild_id):
        """(channel, language, alerts, interval) or None if the guild never used /settings."""
        return self.conn.execute("SELECT channel_id,language,alerts,poll_interval FROM settings WHERE guild_id=?", (guild_id,)).fetchone()

    # ── Servers imported with /syncservers ──
    def save_servers(self, rows):
        self.conn.execute("CREATE TABLE IF NOT EXISTS server_directory(id TEXT PRIMARY KEY,name TEXT NOT NULL)")
        self.conn.executemany("INSERT INTO server_directory VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", [(r['id'], r['name']) for r in rows])
        self.conn.commit()

    def servers(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS server_directory(id TEXT PRIMARY KEY,name TEXT NOT NULL)")
        return [{'id': r[0], 'name': r[1]} for r in self.conn.execute("SELECT id,name FROM server_directory")]

    # ── Verified SteamID -> BattleMetrics ID matches (global: a fact, not a lookup history) ──
    def save_identity(self, steamid: str, bm_id: str):
        self.conn.execute('INSERT INTO identities VALUES(?,?,?) ON CONFLICT(steamid) DO UPDATE SET bm_id=excluded.bm_id,verified_at=excluded.verified_at',
                          (steamid, bm_id, time.time()))
        self.conn.commit()

    def identity(self, steamid: str, max_age_days: int = 30) -> str | None:
        """BattleMetrics ID verified for this SteamID in the last `max_age_days`, or None."""
        row = self.conn.execute('SELECT bm_id FROM identities WHERE steamid=? AND verified_at>?', (steamid, time.time() - max_age_days * 86400)).fetchone()
        return row[0] if row else None

    # ── Player book: players looked up in each guild, for name autocomplete ──
    def remember_player(self, scope: int, name: str | None, steamid: str | None = None, bm_id: str | None = None):
        """Save or refresh a player. One row per player: a SteamID row absorbs an older BattleMetrics-only row."""
        if not steamid and not bm_id:
            return
        if not steamid and bm_id:
            row = self.conn.execute('SELECT steamid FROM players WHERE scope=? AND bm_id=? AND steamid IS NOT NULL', (scope, bm_id)).fetchone()
            steamid = row[0] if row else None
        if steamid and bm_id:
            old = self.conn.execute('SELECT name FROM players WHERE scope=? AND ref=?', (scope, 'bm:' + bm_id)).fetchone()
            name = name or (old[0] if old else None)
            self.conn.execute('DELETE FROM players WHERE scope=? AND ref=?', (scope, 'bm:' + bm_id))
        ref = steamid or 'bm:' + bm_id
        self.conn.execute('INSERT INTO players(scope,ref,name,steamid,bm_id,used_at) VALUES(?,?,?,?,?,?) ON CONFLICT(scope,ref) DO UPDATE SET '
                          'name=COALESCE(excluded.name,players.name),bm_id=COALESCE(excluded.bm_id,players.bm_id),used_at=excluded.used_at',
                          (scope, ref, (name or '').strip()[:100] or None, steamid, bm_id, time.time()))
        # Bounded: keep the 500 most recent players per guild.
        self.conn.execute('DELETE FROM players WHERE scope=? AND ref NOT IN (SELECT ref FROM players WHERE scope=? ORDER BY used_at DESC LIMIT 500)', (scope, scope))
        self.conn.commit()

    def bm_for_steam(self, scope: int, steamid: str) -> str | None:
        """BattleMetrics ID linked to this SteamID in this guild's book (verified or confirmed by a member)."""
        row = self.conn.execute('SELECT bm_id FROM players WHERE scope=? AND steamid=? AND bm_id IS NOT NULL', (scope, steamid)).fetchone()
        return row[0] if row else None

    def player_name(self, scope: int, bm_id: str) -> str | None:
        row = self.conn.execute('SELECT name FROM players WHERE scope=? AND bm_id=? AND name IS NOT NULL', (scope, bm_id)).fetchone()
        return row[0] if row else None

    def known_players(self, scope: int, query: str = '', limit: int = 25) -> list[tuple[str | None, str | None, str | None]]:
        """(name, steamid, bm_id) matching name or ID, most recently used first."""
        like = f"%{query.strip().replace('%', '').replace('_', '')}%"
        return self.conn.execute('SELECT name,steamid,bm_id FROM players WHERE scope=? AND (name LIKE ? OR steamid LIKE ? OR bm_id LIKE ?) '
                                 'ORDER BY used_at DESC LIMIT ?', (scope, like, like, like, limit)).fetchall()
