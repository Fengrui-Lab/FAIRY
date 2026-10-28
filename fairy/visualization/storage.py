"""Local workbench records. Display snapshots are never restoration checkpoints."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def detached(value: Any) -> Any:
    return json.loads(encode(value))


class RunStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / "workbench.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, descriptor TEXT NOT NULL, tools TEXT NOT NULL,
                layout TEXT NOT NULL, status TEXT NOT NULL,
                audit_accessed INTEGER NOT NULL DEFAULT 0, audit_assisted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS frames (
                run_id TEXT NOT NULL, revision INTEGER NOT NULL,
                public TEXT NOT NULL, audit TEXT NOT NULL, command_id TEXT,
                PRIMARY KEY(run_id,revision)
            );
            CREATE TABLE IF NOT EXISTS commands (
                run_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(run_id,id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                run_id TEXT NOT NULL, observation_id TEXT NOT NULL,
                first_revision INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(run_id,observation_id)
            );
        """)
        self.db.commit()
        self._migrate_observations()
        self.recover()

    def _migrate_observations(self) -> None:
        """Upgrade existing display histories without reconstructing any state."""
        with self.lock, self.db:
            if self.db.execute("PRAGMA user_version").fetchone()[0] >= 1:
                return
            cursor = self.db.execute("SELECT run_id,revision,public FROM frames ORDER BY run_id,revision")
            for run_id, revision, raw in cursor:
                for observation in json.loads(raw).get("observations", []):
                    self._insert_observation(run_id, revision, observation)
            self.db.execute("PRAGMA user_version=1")

    def _insert_observation(self, run_id: str, revision: int, observation: dict) -> None:
        observation_id = observation.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("Observation records require a stable observation_id")
        record = {**observation, "revision": revision}
        self.db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?)",
                        (run_id, observation_id, revision, encode(record)))

    def recover(self) -> None:
        """Never replay commands whose execution outcome was not committed."""
        with self.lock, self.db:
            rows = self.db.execute("SELECT id,descriptor FROM runs WHERE status='active'").fetchall()
            for run_id, raw in rows:
                descriptor = json.loads(raw)
                descriptor["status"] = "interrupted"
                self.db.execute("UPDATE runs SET status=?,descriptor=? WHERE id=?",
                                ("interrupted", encode(descriptor), run_id))
            rows = self.db.execute("SELECT run_id,id,record FROM commands WHERE status IN ('queued','running')").fetchall()
            for run_id, command_id, raw in rows:
                record = json.loads(raw)
                record.update(status="interrupted", result={"ok": False, "data": None,
                    "error": {"code": "interrupted", "message": "执行中断，结果不确定；不会自动重放。", "partial_effects": "unknown"}})
                self.db.execute("UPDATE commands SET status=?,record=? WHERE run_id=? AND id=?",
                                ("interrupted", encode(record), run_id, command_id))

    def create(self, descriptor: dict, tools: list, layout: dict) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO runs(id,descriptor,tools,layout,status) VALUES (?,?,?,?,?)",
                            (descriptor["run_id"], encode(descriptor), encode(tools), encode(layout), descriptor["status"]))

    def run(self, run_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT descriptor,tools,layout,status,audit_accessed,audit_assisted FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return dict(descriptor=json.loads(row[0]), tools=json.loads(row[1]), layout=json.loads(row[2]),
                    status=row[3], audit_accessed=bool(row[4]), audit_assisted=bool(row[5]))

    def list_runs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT descriptor,status,audit_accessed,audit_assisted FROM runs ORDER BY rowid DESC").fetchall()
        return [{**json.loads(raw), "status": status, "audit_accessed": bool(accessed), "audit_assisted": bool(assisted)}
                for raw, status, accessed, assisted in rows]

    def status(self, run_id: str, status: str) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT descriptor FROM runs WHERE id=?", (run_id,)).fetchone()
            if row:
                descriptor = json.loads(row[0])
                descriptor["status"] = status
                self.db.execute("UPDATE runs SET status=?,descriptor=? WHERE id=?", (status, encode(descriptor), run_id))

    def flags(self, run_id: str, *, accessed: bool = False, assisted: bool = False) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET audit_accessed=MAX(audit_accessed,?),audit_assisted=MAX(audit_assisted,?) WHERE id=?",
                            (int(accessed), int(assisted), run_id))

    def save_layout(self, run_id: str, layout: dict) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET layout=? WHERE id=?", (encode(layout), run_id))

    def frame(self, run_id: str, revision: int | None = None, *, audit: bool = False) -> dict | None:
        field = "audit" if audit else "public"
        with self.lock:
            if revision is None:
                row = self.db.execute(f"SELECT {field} FROM frames WHERE run_id=? ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
            else:
                row = self.db.execute(f"SELECT {field} FROM frames WHERE run_id=? AND revision=?", (run_id, revision)).fetchone()
        return json.loads(row[0]) if row else None

    def save_frame(self, public: dict, audit: dict, command_id: str | None = None,
                   completed_command: dict | None = None) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO frames VALUES (?,?,?,?,?)", (public["run_id"], public["revision"], encode(public), encode(audit), command_id))
            for observation in public.get("observations", []):
                self._insert_observation(public["run_id"], public["revision"], observation)
            if completed_command is not None:
                self.db.execute("UPDATE commands SET status=?,record=? WHERE run_id=? AND id=?",
                                (completed_command["status"], encode(completed_command), completed_command["run_id"], completed_command["command_id"]))

    def history(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT public,command_id FROM frames WHERE run_id=? ORDER BY revision", (run_id,)).fetchall()
        return [{"revision": (p := json.loads(raw))["revision"], "sim_time": p["sim_time"],
                 "sim_datetime": p["sim_datetime"], "command_id": command_id} for raw, command_id in rows]

    def observations(self, run_id: str, revision: int | None = None) -> list[dict]:
        with self.lock:
            if revision is None:
                rows = self.db.execute("SELECT record FROM observations WHERE run_id=? ORDER BY first_revision,rowid", (run_id,)).fetchall()
            else:
                rows = self.db.execute("SELECT record FROM observations WHERE run_id=? AND first_revision<=? ORDER BY first_revision,rowid", (run_id, revision)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def command(self, run_id: str, command_id: str) -> tuple[str, dict] | None:
        with self.lock:
            row = self.db.execute("SELECT payload,record FROM commands WHERE run_id=? AND id=?", (run_id, command_id)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save_command(self, record: dict, payload: str | None = None) -> None:
        with self.lock, self.db:
            if payload is not None:
                self.db.execute("INSERT INTO commands VALUES (?,?,?,?,?)",
                                (record["run_id"], record["command_id"], payload, record["status"], encode(record)))
            else:
                self.db.execute("UPDATE commands SET status=?,record=? WHERE run_id=? AND id=?",
                                (record["status"], encode(record), record["run_id"], record["command_id"]))

    def add_event(self, run_id: str, event: dict) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(run_id,record) VALUES (?,?)", (run_id, encode(event)))

    def events(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id,record FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{**json.loads(raw), "event_id": event_id} for event_id, raw in rows]

    def close(self) -> None:
        with self.lock:
            self.db.close()
