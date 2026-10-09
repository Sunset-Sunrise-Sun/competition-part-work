import json
import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        return connection

    def save(self, report: dict):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)",
                       (report["session_id"], json.dumps(report, ensure_ascii=False)))

    def list(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM sessions ORDER BY rowid DESC LIMIT 50")]

    def clear(self):
        with self.connect() as db:
            db.execute("DELETE FROM sessions")
