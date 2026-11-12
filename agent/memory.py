"""Short-lived SQLite state for one tutor session."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class SessionState:
    session_id: str
    chosen_exercise: str | None
    current_step: int | None
    attempts: int
    last_answer: str | None
    last_confidence: float | None
    placement_confirmed: bool
    turns: tuple[dict, ...]
    created_at: str
    updated_at: str


class SessionStore:
    _fields = {
        "chosen_exercise",
        "current_step",
        "attempts",
        "last_answer",
        "last_confidence",
        "placement_confirmed",
    }

    def __init__(self, db_url: str) -> None:
        path = db_url.removeprefix("sqlite:///")
        self.path = None if path in {":memory:", ""} else Path(path)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection_target = self.path
        else:
            connection_target = ":memory:"
        self.connection = sqlite3.connect(
            connection_target, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                chosen_exercise TEXT,
                current_step INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_answer TEXT,
                last_confidence REAL,
                placement_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                duration_ms REAL,
                success INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            """
        )
        session_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        if "placement_confirmed" not in session_columns:
            self.connection.execute(
                "ALTER TABLE sessions ADD COLUMN placement_confirmed "
                "INTEGER NOT NULL DEFAULT 0"
            )
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(tool_calls)")
        }
        for name, definition in (
            ("details", "TEXT NOT NULL DEFAULT ''"),
            ("duration_ms", "REAL"),
            ("success", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE tool_calls ADD COLUMN {name} {definition}"
                )
        self.connection.commit()

    def create(self, session_id: str) -> SessionState:
        now = _now()
        with self._lock:
            self.connection.execute(
                "INSERT INTO sessions(session_id, created_at, updated_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            self.connection.commit()
        return self.get(session_id)  # type: ignore[return-value]

    def get(self, session_id: str) -> SessionState | None:
        row = self.connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        turns = self.connection.execute(
            "SELECT role, text FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT 6",
            (session_id,),
        ).fetchall()
        return SessionState(
            session_id=row["session_id"],
            chosen_exercise=row["chosen_exercise"],
            current_step=row["current_step"],
            attempts=row["attempts"],
            last_answer=row["last_answer"],
            last_confidence=row["last_confidence"],
            placement_confirmed=bool(row["placement_confirmed"]),
            turns=tuple(dict(turn) for turn in reversed(turns)),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update(self, session_id: str, **fields: object) -> SessionState:
        unknown = set(fields) - self._fields
        if unknown:
            raise ValueError("Unknown session fields: " + ", ".join(sorted(unknown)))
        if not fields:
            state = self.get(session_id)
            if state is None:
                raise KeyError(session_id)
            return state
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._lock:
            cursor = self.connection.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                tuple(fields.values()) + (session_id,),
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)
            self.connection.commit()
        return self.get(session_id)  # type: ignore[return-value]

    def append_turn(self, session_id: str, role: str, text: str) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO turns(session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, text, _now()),
            )
            self.connection.execute(
                """
                DELETE FROM turns WHERE session_id = ? AND id NOT IN
                (SELECT id FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT 6)
                """,
                (session_id, session_id),
            )
            self.connection.commit()

    def append_tool_call(
        self,
        session_id: str,
        name: str,
        *,
        details: str = "",
        duration_ms: float | None = None,
        success: bool = True,
    ) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO tool_calls(
                    session_id, name, details, duration_ms, success, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, name, details, duration_ms, int(success), _now()),
            )
            self.connection.commit()

    def state_block(self, session_id: str) -> str:
        state = self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        return (
            f"exercise={state.chosen_exercise or 'none'}; "
            f"step={state.current_step if state.current_step is not None else 'none'}; "
            f"attempts={state.attempts}; answer={state.last_answer or 'none'}; "
            f"confidence={state.last_confidence if state.last_confidence is not None else 'none'}; "
            f"placement={'confirmed' if state.placement_confirmed else 'pending'}"
        )

    def delete(self, session_id: str) -> None:
        with self._lock:
            self.connection.execute(
                "DELETE FROM turns WHERE session_id = ?", (session_id,)
            )
            self.connection.execute(
                "DELETE FROM tool_calls WHERE session_id = ?", (session_id,)
            )
            self.connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            self.connection.commit()

    def prune(self, max_age_hours: float = 24) -> int:
        """Delete sessions idle longer than max_age_hours, with their rows."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).isoformat()
        with self._lock:
            expired = [
                row["session_id"]
                for row in self.connection.execute(
                    "SELECT session_id FROM sessions WHERE updated_at < ?", (cutoff,)
                )
            ]
            if not expired:
                return 0
            placeholders = ", ".join("?" for _ in expired)
            for table in ("turns", "tool_calls", "sessions"):
                self.connection.execute(
                    f"DELETE FROM {table} WHERE session_id IN ({placeholders})",
                    expired,
                )
            self.connection.commit()
        return len(expired)

    def close(self) -> None:
        with self._lock:
            self.connection.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
