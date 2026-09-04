import csv
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from monitoring_state import StateChangeEvent, format_duration


DEFAULT_EVENT_RETENTION = 10_000
EVENT_TYPES = ("DOWN", "RECOVERED")
CSV_COLUMNS = (
    "timestamp",
    "event_type",
    "device_name",
    "host",
    "port",
    "ping",
    "previous_status",
    "new_status",
    "downtime_seconds",
    "downtime_display",
)


@dataclass(frozen=True)
class EventRecord:
    timestamp: str
    event_type: str
    device_name: str
    host: str
    port: int
    ping: str
    previous_status: str
    new_status: str
    downtime_seconds: Optional[float] = None

    @classmethod
    def from_state_change(
        cls,
        event: StateChangeEvent,
        *,
        device_name: str,
        host: str,
        port: int,
        ping: str,
    ):
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.astimezone()
        return cls(
            timestamp=occurred_at.isoformat(timespec="seconds"),
            event_type=event.kind,
            device_name=str(device_name or "").strip(),
            host=str(host).strip(),
            port=int(port),
            ping=str(ping),
            previous_status=event.previous_status,
            new_status=event.new_status,
            downtime_seconds=event.downtime_seconds,
        )


class EventHistoryStore:
    """Small serialized SQLite store that fails safely when unavailable."""

    def __init__(self, path: str, retention: int = DEFAULT_EVENT_RETENTION):
        self.path = os.path.abspath(path)
        self.retention = max(1, int(retention))
        self._lock = threading.RLock()
        self.available = False
        self.last_error = None
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @contextmanager
    def _connection(self):
        with closing(self._connect()) as connection:
            with connection:
                yield connection

    def _initialize(self) -> None:
        try:
            with self._lock, self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        device_name TEXT NOT NULL DEFAULT '',
                        host TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        ping TEXT NOT NULL,
                        previous_status TEXT NOT NULL,
                        new_status TEXT NOT NULL,
                        downtime_seconds REAL
                    )
                    """
                )
            self.available = True
            self.last_error = None
        except (OSError, sqlite3.Error) as exc:
            self.available = False
            self.last_error = str(exc)

    def insert(self, event: EventRecord) -> bool:
        if not self.available:
            return False
        try:
            with self._lock, self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO events (
                        timestamp, event_type, device_name, host, port, ping,
                        previous_status, new_status, downtime_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.timestamp,
                        event.event_type,
                        event.device_name,
                        event.host,
                        event.port,
                        event.ping,
                        event.previous_status,
                        event.new_status,
                        event.downtime_seconds,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM events
                    WHERE id NOT IN (
                        SELECT id FROM events ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self.retention,),
                )
            return True
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return False

    def list_events(self, search: str = "", event_type: str = "All"):
        if not self.available:
            return []
        clauses = []
        parameters = []
        search_text = str(search or "").strip()
        if search_text:
            clauses.append("(device_name LIKE ? OR host LIKE ?)")
            search_value = f"%{search_text}%"
            parameters.extend((search_value, search_value))
        normalized_type = str(event_type or "All").upper()
        if normalized_type in EVENT_TYPES:
            clauses.append("event_type = ?")
            parameters.append(normalized_type)
        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._lock, self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT timestamp, event_type, device_name, host, port, ping,
                           previous_status, new_status, downtime_seconds
                    FROM events
                    """
                    + where_sql
                    + " ORDER BY id DESC",
                    parameters,
                ).fetchall()
            return [EventRecord(*row) for row in rows]
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return []

    def clear(self) -> bool:
        if not self.available:
            return False
        try:
            with self._lock, self._connection() as connection:
                connection.execute("DELETE FROM events")
            return True
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return False


def export_events_csv(path: str, events: Iterable[EventRecord]) -> int:
    """Write the supplied filtered events in Excel-friendly UTF-8 CSV format."""
    rows = list(events)
    with open(path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for event in rows:
            writer.writerow(
                {
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "device_name": event.device_name,
                    "host": event.host,
                    "port": event.port,
                    "ping": event.ping,
                    "previous_status": event.previous_status,
                    "new_status": event.new_status,
                    "downtime_seconds": (
                        "" if event.downtime_seconds is None else event.downtime_seconds
                    ),
                    "downtime_display": (
                        ""
                        if event.downtime_seconds is None
                        else format_duration(event.downtime_seconds)
                    ),
                }
            )
    return len(rows)
