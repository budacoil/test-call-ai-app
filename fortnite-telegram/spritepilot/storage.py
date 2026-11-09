from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

import cv2


class Store:
    def __init__(self, root: Path):
        self.root = root
        (root / "rewards").mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "journal.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, started REAL, ended REAL, loops INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS rewards(id TEXT PRIMARY KEY, at REAL, session TEXT, match_id TEXT,
                variant TEXT, confidence REAL, full_path TEXT, crop_path TEXT, corrected INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL, level TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, at REAL, chat INTEGER, payload TEXT,
                state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, error TEXT DEFAULT '');
        """)
        self.db.commit()

    def query(self, sql, params=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.lock:
            cursor = self.db.execute(sql, params)
            self.db.commit()
            return cursor.lastrowid

    def event(self, message: str, level="info"):
        self.execute("INSERT INTO events(at,level,message) VALUES(?,?,?)", (time.time(), level, message))

    def start_session(self):
        key = uuid.uuid4().hex
        self.execute("INSERT INTO sessions(id,started) VALUES(?,?)", (key, time.time()))
        return key

    def finish_session(self, key, loops):
        if key:
            self.execute("UPDATE sessions SET ended=?,loops=? WHERE id=?", (time.time(), loops, key))

    def save_reward(self, frame, crop, variant, confidence, session, match_id):
        key = uuid.uuid4().hex
        full = self.root / "rewards" / f"{key}.jpg"
        icon = self.root / "rewards" / f"{key}-icon.png"
        written = []
        try:
            for path, picture in ((full, frame), (icon, crop)):
                ok, data = cv2.imencode(path.suffix, picture)
                if not ok:
                    raise OSError("Не удалось сохранить изображение награды")
                path.write_bytes(data.tobytes())
                written.append(path)
            self.execute("INSERT INTO rewards VALUES(?,?,?,?,?,?,?,?,0)",
                         (key, time.time(), session, match_id, variant, float(confidence), str(full), str(icon)))
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise
        return self.query("SELECT * FROM rewards WHERE id=?", (key,))[0]

    def rewards(self, session=None, limit=200):
        if session:
            return self.query("SELECT * FROM rewards WHERE session=? ORDER BY at DESC LIMIT ?", (session, limit))
        return self.query("SELECT * FROM rewards ORDER BY at DESC LIMIT ?", (limit,))

    def enqueue(self, chat: int, text: str, photo: str = "", markup=None):
        if not chat:
            return
        payload = {"text": text[:4000], "photo": photo, "markup": markup}
        return self.execute("INSERT INTO outbox(at,chat,payload) VALUES(?,?,?)", (time.time(), chat, json.dumps(payload)))

    def due(self, now=None):
        rows = self.query("SELECT * FROM outbox WHERE state='pending' AND next_try<=? ORDER BY id LIMIT 1", (now or time.time(),))
        return rows[0] if rows else None

    def delivered(self, key):
        self.execute("UPDATE outbox SET state='sent',error='' WHERE id=?", (key,))

    def retry(self, key, delay, error, permanent=False):
        self.execute("UPDATE outbox SET attempts=attempts+1,next_try=?,error=?,state=? WHERE id=?",
                     (time.time() + delay, error[:200], "failed" if permanent else "pending", key))

    def pending(self):
        return self.query("SELECT count(*) AS n FROM outbox WHERE state='pending'")[0]["n"]

    def close(self):
        with self.lock:
            self.db.close()
