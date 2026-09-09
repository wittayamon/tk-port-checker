import csv
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from monitoring_state import (
    EVENT_MAINTENANCE_ENDED,
    EVENT_MAINTENANCE_STARTED,
    StateChangeEvent,
    format_duration,
)


DEFAULT_EVENT_RETENTION = 10_000
EVENT_TYPES = ("DOWN", "RECOVERED", EVENT_MAINTENANCE_STARTED, EVENT_MAINTENANCE_ENDED)
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
    "maintenance_reason",
    "maintenance_until",
    "maintenance_end_reason",
    "suppressed_by_maintenance",
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
    maintenance_reason: str = ""
    maintenance_until: Optional[str] = None
    maintenance_end_reason: str = ""
    suppressed_by_maintenance: bool = False

    @classmethod
    def from_state_change(
        cls,
        event: StateChangeEvent,
        *,
        device_name: str,
        host: str,
        port: int,
        ping: str,
        suppressed_by_maintenance: bool = False,
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
            suppressed_by_maintenance=bool(suppressed_by_maintenance),
        )

    @classmethod
    def maintenance_event(
        cls, event_type: str, *, occurred_at: datetime, device_name: str,
        host: str, port: int, reason: str = "", until: Optional[datetime] = None,
        end_reason: str = "",
    ):
        if event_type not in (EVENT_MAINTENANCE_STARTED, EVENT_MAINTENANCE_ENDED):
            raise ValueError("Unsupported maintenance event type.")
        when = occurred_at.astimezone() if occurred_at.tzinfo is None else occurred_at
        until_text = None
        if until is not None:
            until_value = until.astimezone() if until.tzinfo is None else until
            until_text = until_value.isoformat(timespec="seconds")
        return cls(
            timestamp=when.isoformat(timespec="seconds"), event_type=event_type,
            device_name=str(device_name or "").strip(), host=str(host).strip(),
            port=int(port), ping="", previous_status="INACTIVE" if event_type == EVENT_MAINTENANCE_STARTED else "ACTIVE",
            new_status="ACTIVE" if event_type == EVENT_MAINTENANCE_STARTED else "INACTIVE",
            maintenance_reason=str(reason or "").strip(), maintenance_until=until_text,
            maintenance_end_reason=str(end_reason or "").strip(),
        )


class EventHistoryStore:
    """Small serialized SQLite store that fails safely when unavailable.

    Connections are intentionally short-lived: worker/report reads and Tk-driven
    writes can share the file without retaining a cross-thread SQLite handle.
    """

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
                existing = {
                    row[1] for row in connection.execute("PRAGMA table_info(events)")
                }
                migrations = {
                    "maintenance_reason": "TEXT NOT NULL DEFAULT ''",
                    "maintenance_until": "TEXT",
                    "maintenance_end_reason": "TEXT NOT NULL DEFAULT ''",
                    "suppressed_by_maintenance": "INTEGER NOT NULL DEFAULT 0",
                }
                # Additive migrations preserve old event databases in place;
                # maintenance metadata must never rewrite TCP history evidence.
                for name, declaration in migrations.items():
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE events ADD COLUMN {name} {declaration}"
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
                        previous_status, new_status, downtime_seconds,
                        maintenance_reason, maintenance_until,
                        maintenance_end_reason, suppressed_by_maintenance
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        event.maintenance_reason,
                        event.maintenance_until,
                        event.maintenance_end_reason,
                        int(event.suppressed_by_maintenance),
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

    def list_events(
        self, search: str = "", event_type: str = "All", *, oldest_first: bool = False
    ):
        if not self.available:
            return []
        clauses = []
        parameters = []
        search_text = str(search or "").strip()
        if search_text:
            clauses.append("(device_name LIKE ? OR host LIKE ? OR maintenance_reason LIKE ? OR maintenance_end_reason LIKE ?)")
            search_value = f"%{search_text}%"
            parameters.extend((search_value, search_value, search_value, search_value))
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
                           previous_status, new_status, downtime_seconds,
                           maintenance_reason, maintenance_until,
                           maintenance_end_reason, suppressed_by_maintenance
                    FROM events
                    """
                    + where_sql
                    + (" ORDER BY id ASC" if oldest_first else " ORDER BY id DESC"),
                    parameters,
                ).fetchall()
            return [EventRecord(*row[:-1], suppressed_by_maintenance=bool(row[-1])) for row in rows]
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return []

    def health_summary(self) -> dict:
        """Run bounded, read-only queries used by Application Diagnostics."""
        if not self.available:
            return {"accessible": False, "row_count": 0, "last_event_at": None,
                    "retention_limit": self.retention}
        try:
            with self._lock, self._connection() as connection:
                connection.execute("SELECT 1").fetchone()
                row_count, latest = connection.execute(
                    "SELECT COUNT(*), MAX(timestamp) FROM events"
                ).fetchone()
            return {"accessible": True, "row_count": int(row_count),
                    "last_event_at": latest, "retention_limit": self.retention}
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return {"accessible": False, "row_count": 0, "last_event_at": None,
                    "retention_limit": self.retention}

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
                    "maintenance_reason": event.maintenance_reason,
                    "maintenance_until": event.maintenance_until or "",
                    "maintenance_end_reason": event.maintenance_end_reason,
                    "suppressed_by_maintenance": "yes" if event.suppressed_by_maintenance else "no",
                }
            )
    return len(rows)
