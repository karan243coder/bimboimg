"""SQLite storage — user settings, usage limits, stats. Async-safe."""
from __future__ import annotations

import asyncio
import json
import time
import sqlite3
from datetime import date

from . import config as C

_lock = asyncio.Lock()
_conn: sqlite3.Connection | None = None

DEFAULTS = {
    "out_fmt": "PNG",
    "bg_mode": "transparent",   # transparent | white | color | blur
    "bg_color": "#ffffff",
    "feather": 1,
    "shrink": 0,
    "zone": "both",
    "zone_pct": 22,
    "quality": 92,
    "lang": "hi",
}


def _init():
    global _conn
    _conn = sqlite3.connect(C.DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      uid INTEGER PRIMARY KEY,
      name TEXT, settings TEXT DEFAULT '{}',
      joined INTEGER, last_seen INTEGER,
      total INTEGER DEFAULT 0, banned INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS usage(
      uid INTEGER, day TEXT, n INTEGER DEFAULT 0,
      PRIMARY KEY(uid, day)
    );
    CREATE TABLE IF NOT EXISTS events(
      ts INTEGER, uid INTEGER, kind TEXT, ms INTEGER, ok INTEGER
    );
    """)
    _conn.commit()


async def init():
    async with _lock:
        if _conn is None:
            await asyncio.get_running_loop().run_in_executor(None, _init)


async def _run(fn, *a):
    async with _lock:
        return await asyncio.get_running_loop().run_in_executor(None, fn, *a)


# ---------------------------------------------------------------- users
def _touch(uid, name):
    now = int(time.time())
    _conn.execute(
        "INSERT INTO users(uid,name,joined,last_seen) VALUES(?,?,?,?) "
        "ON CONFLICT(uid) DO UPDATE SET last_seen=?, name=?",
        (uid, name, now, now, now, name))
    _conn.commit()


async def touch(uid, name=""):
    await _run(_touch, uid, name)


def _get_settings(uid):
    r = _conn.execute("SELECT settings FROM users WHERE uid=?", (uid,)).fetchone()
    s = dict(DEFAULTS)
    if r and r[0]:
        try:
            s.update(json.loads(r[0]))
        except Exception:
            pass
    return s


async def get_settings(uid) -> dict:
    return await _run(_get_settings, uid)


def _set_setting(uid, k, v):
    s = _get_settings(uid)
    s[k] = v
    _conn.execute("UPDATE users SET settings=? WHERE uid=?", (json.dumps(s), uid))
    _conn.commit()
    return s


async def set_setting(uid, k, v) -> dict:
    return await _run(_set_setting, uid, k, v)


# ---------------------------------------------------------------- limits
def _bump(uid):
    d = date.today().isoformat()
    _conn.execute(
        "INSERT INTO usage(uid,day,n) VALUES(?,?,1) "
        "ON CONFLICT(uid,day) DO UPDATE SET n=n+1", (uid, d))
    _conn.execute("UPDATE users SET total=total+1 WHERE uid=?", (uid,))
    _conn.commit()
    return _conn.execute("SELECT n FROM usage WHERE uid=? AND day=?", (uid, d)).fetchone()[0]


async def bump(uid) -> int:
    return await _run(_bump, uid)


def _today(uid):
    r = _conn.execute("SELECT n FROM usage WHERE uid=? AND day=?",
                      (uid, date.today().isoformat())).fetchone()
    return r[0] if r else 0


async def today_count(uid) -> int:
    return await _run(_today, uid)


def _banned(uid):
    r = _conn.execute("SELECT banned FROM users WHERE uid=?", (uid,)).fetchone()
    return bool(r and r[0])


async def is_banned(uid) -> bool:
    return await _run(_banned, uid)


def _set_ban(uid, v):
    _conn.execute("UPDATE users SET banned=? WHERE uid=?", (1 if v else 0, uid))
    _conn.commit()


async def set_ban(uid, v):
    await _run(_set_ban, uid, v)


# ---------------------------------------------------------------- stats
def _log_ev(uid, kind, ms, ok):
    _conn.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                  (int(time.time()), uid, kind, ms, 1 if ok else 0))
    _conn.commit()


async def log_event(uid, kind, ms, ok=True):
    await _run(_log_ev, uid, kind, ms, ok)


def _stats():
    c = _conn.cursor()
    u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    a = c.execute("SELECT COUNT(*) FROM users WHERE last_seen>?",
                  (int(time.time()) - 86400,)).fetchone()[0]
    t = c.execute("SELECT COALESCE(SUM(n),0) FROM usage WHERE day=?",
                  (date.today().isoformat(),)).fetchone()[0]
    tot = c.execute("SELECT COALESCE(SUM(total),0) FROM users").fetchone()[0]
    avg = c.execute("SELECT COALESCE(AVG(ms),0) FROM events WHERE ts>?",
                    (int(time.time()) - 86400,)).fetchone()[0]
    top = c.execute(
        "SELECT kind, COUNT(*) c FROM events WHERE ts>? GROUP BY kind ORDER BY c DESC LIMIT 5",
        (int(time.time()) - 86400,)).fetchall()
    return {"users": u, "active24": a, "today": t, "total": tot,
            "avg_ms": round(avg), "top": top}


async def stats() -> dict:
    return await _run(_stats)


def _all_uids():
    return [r[0] for r in _conn.execute("SELECT uid FROM users WHERE banned=0")]


async def all_uids():
    return await _run(_all_uids)
