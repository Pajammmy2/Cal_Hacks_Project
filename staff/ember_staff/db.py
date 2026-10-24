"""SQLite store the nonprofit controls (staff/data/ember.db). One row per client; JSON columns for profile, plan and text."""
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id TEXT PRIMARY KEY,
  profile TEXT NOT NULL,
  plan TEXT,
  plan_error TEXT,
  selected TEXT,
  text TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  attested INTEGER DEFAULT 0,
  printed_at TEXT,
  audio TEXT,
  created_at TEXT,
  updated_at TEXT
);
"""

JSON_COLS = ("profile", "plan", "selected", "text", "audio")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    con = sqlite3.connect(config.db_path(), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS:
        d[k] = json.loads(d[k]) if d.get(k) else None
    d["status"] = status(d)
    return d


def status(row):
    """Card status: none / draft / stamped / printed."""
    if not row.get("plan"):
        return "none"
    if not (row.get("reviewed_by") and row.get("reviewed_at")):
        return "draft"
    if row.get("printed_at"):
        return "printed"
    return "stamped"


def new_id():
    return "c_" + secrets.token_hex(5)


def list_clients():
    with _lock, connect() as con:
        return [_row(r) for r in con.execute("SELECT * FROM clients ORDER BY json_extract(profile,'$.name')")]


def get(cid):
    with _lock, connect() as con:
        return _row(con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone())


def upsert_profile(profile):
    cid = profile.get("id") or new_id()
    profile["id"] = cid
    t = now()
    with _lock, connect() as con:
        if con.execute("SELECT 1 FROM clients WHERE id=?", (cid,)).fetchone():
            con.execute("UPDATE clients SET profile=?, updated_at=? WHERE id=?", (json.dumps(profile), t, cid))
        else:
            con.execute("INSERT INTO clients (id, profile, created_at, updated_at) VALUES (?,?,?,?)",
                        (cid, json.dumps(profile), t, t))
    return cid


def update(cid, **fields):
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(json.dumps(v) if k in JSON_COLS and v is not None else v)
    cols.append("updated_at=?")
    vals.append(now())
    vals.append(cid)
    with _lock, connect() as con:
        con.execute(f"UPDATE clients SET {', '.join(cols)} WHERE id=?", vals)


def clear_stamp(cid):
    """Any edit, regeneration or swap after stamping clears the stamp (and the printed state)."""
    update(cid, reviewed_by=None, reviewed_at=None, attested=0, printed_at=None)


def delete(cid):
    with _lock, connect() as con:
        con.execute("DELETE FROM clients WHERE id=?", (cid,))
