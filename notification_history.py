"""Persistent, endpoint-free notification delivery history and retry state."""

import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from notification_models import NotificationEvent
from monitoring_state import format_duration


STATUS_QUEUED = "QUEUED"
STATUS_RETRYING = "RETRYING"
STATUS_DELIVERED = "DELIVERED"
STATUS_FAILED = "FAILED"
DELIVERY_STATUSES = (
    STATUS_QUEUED,
    STATUS_RETRYING,
    STATUS_DELIVERED,
    STATUS_FAILED,
)
TERMINAL_STATUSES = (STATUS_DELIVERED, STATUS_FAILED)
DEFAULT_DELIVERY_RETENTION = 20_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DeliveryRecord:
    id: int
    created_at: str
    event_timestamp: str
    event_type: str
    device_name: str
    host: str
    port: int
    ping: str
    previous_status: str
    new_status: str
    downtime_seconds: Optional[float]
    provider: str
    status: str
    attempt_count: int
    delayed_retry_count: int
    last_attempt_at: Optional[str]
    next_retry_at: Optional[str]
    delivered_at: Optional[str]
    last_error_category: Optional[str]
    last_error_summary: Optional[str]

    def to_event(self) -> NotificationEvent:
        return NotificationEvent(
            event_type=self.event_type,
            timestamp=self.event_timestamp,
            device_name=self.device_name,
            host=self.host,
            port=self.port,
            ping=self.ping,
            previous_status=self.previous_status,
            new_status=self.new_status,
            downtime_seconds=self.downtime_seconds,
            downtime_display=(format_duration(self.downtime_seconds)
                              if self.downtime_seconds is not None else "-"),
        )


_SELECT_COLUMNS = """
id, created_at, event_timestamp, event_type, device_name, host, port, ping,
previous_status, new_status, downtime_seconds, provider, status, attempt_count,
delayed_retry_count, last_attempt_at, next_retry_at, delivered_at,
last_error_category, last_error_summary
"""


class NotificationHistoryStore:
    """Serialized SQLite access for delivery audit rows and durable retry state.

    The schema deliberately excludes provider endpoints, headers, payload bodies,
    and credentials, so both history and diagnostics remain secret-safe.
    """

    def __init__(self, path: str, retention: int = DEFAULT_DELIVERY_RETENTION):
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

    def _initialize(self):
        try:
            with self._lock, self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notification_deliveries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        event_timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        device_name TEXT NOT NULL DEFAULT '',
                        host TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        ping TEXT NOT NULL,
                        previous_status TEXT NOT NULL,
                        new_status TEXT NOT NULL,
                        downtime_seconds REAL,
                        provider TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        delayed_retry_count INTEGER NOT NULL DEFAULT 0,
                        last_attempt_at TEXT,
                        next_retry_at TEXT,
                        delivered_at TEXT,
                        last_error_category TEXT,
                        last_error_summary TEXT
                    )
                    """
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS idx_notification_due
                    ON notification_deliveries(status, next_retry_at, provider, event_timestamp)"""
                )
            self.available = True
            self.last_error = None
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)

    def _write(self, sql, parameters=()) -> bool:
        if not self.available:
            return False
        try:
            with self._lock, self._connection() as connection:
                connection.execute(sql, parameters)
            return True
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return False

    def insert_delivery(self, event: NotificationEvent, provider: str, *, now=None):
        if event.test_only or not self.available:
            return None
        created_at = timestamp_text(now or utc_now())
        try:
            with self._lock, self._connection() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO notification_deliveries (
                        created_at, event_timestamp, event_type, device_name, host,
                        port, ping, previous_status, new_status, downtime_seconds,
                        provider, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (created_at, event.timestamp, event.event_type, event.device_name,
                     event.host, event.port, event.ping, event.previous_status,
                     event.new_status, event.downtime_seconds, provider, STATUS_QUEUED),
                )
                delivery_id = cursor.lastrowid
            self.prune_terminal()
            return delivery_id
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return None

    def record_attempt(self, delivery_id: int, *, now=None) -> bool:
        return self._write(
            """UPDATE notification_deliveries
               SET attempt_count = attempt_count + 1, last_attempt_at = ?
               WHERE id = ? AND status IN (?, ?)""",
            (timestamp_text(now or utc_now()), delivery_id, STATUS_QUEUED, STATUS_RETRYING),
        )

    def mark_delivered(self, delivery_id: int, *, now=None) -> bool:
        delivered_at = timestamp_text(now or utc_now())
        updated = self._write(
            """UPDATE notification_deliveries SET status = ?, delivered_at = ?,
               next_retry_at = NULL, last_error_category = NULL,
               last_error_summary = NULL WHERE id = ?""",
            (STATUS_DELIVERED, delivered_at, delivery_id),
        )
        if updated:
            self.prune_terminal()
        return updated

    def mark_failed(self, delivery_id: int, category: str, summary: str) -> bool:
        updated = self._write(
            """UPDATE notification_deliveries SET status = ?, next_retry_at = NULL,
               last_error_category = ?, last_error_summary = ? WHERE id = ?""",
            (STATUS_FAILED, category, summary, delivery_id),
        )
        if updated:
            self.prune_terminal()
        return updated

    def schedule_retry(self, delivery_id: int, next_retry_at: datetime,
                       category: str, summary: str) -> bool:
        return self._write(
            """UPDATE notification_deliveries SET status = ?, next_retry_at = ?,
               last_error_category = ?, last_error_summary = ? WHERE id = ?""",
            (STATUS_RETRYING, timestamp_text(next_retry_at), category, summary, delivery_id),
        )

    def begin_delayed_retry(self, delivery_id: int) -> bool:
        return self._write(
            """UPDATE notification_deliveries SET delayed_retry_count = delayed_retry_count + 1
               WHERE id = ? AND status = ?""",
            (delivery_id, STATUS_RETRYING),
        )

    def mark_queued(self, delivery_id: int) -> bool:
        return self._write(
            """UPDATE notification_deliveries SET status = ?, next_retry_at = NULL
               WHERE id = ? AND status = ?""",
            (STATUS_QUEUED, delivery_id, STATUS_FAILED),
        )

    def get(self, delivery_id: int):
        if not self.available:
            return None
        try:
            with self._lock, self._connection() as connection:
                row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM notification_deliveries WHERE id = ?",
                    (delivery_id,),
                ).fetchone()
            return DeliveryRecord(*row) if row else None
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return None

    def list_deliveries(self, search="", provider="All", status="All"):
        if not self.available:
            return []
        clauses, parameters = [], []
        if str(search or "").strip():
            clauses.append("(device_name LIKE ? OR host LIKE ?)")
            value = f"%{str(search).strip()}%"
            parameters.extend((value, value))
        normalized_provider = str(provider or "All").strip().lower()
        if normalized_provider != "all":
            clauses.append("provider = ?")
            parameters.append(normalized_provider)
        normalized_status = str(status or "All").strip().upper()
        if normalized_status in DELIVERY_STATUSES:
            clauses.append("status = ?")
            parameters.append(normalized_status)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        try:
            with self._lock, self._connection() as connection:
                rows = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM notification_deliveries{where_sql} ORDER BY id DESC",
                    parameters,
                ).fetchall()
            return [DeliveryRecord(*row) for row in rows]
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return []

    def health_summary(self) -> dict:
        """Return status counts/latest delivery using read-only aggregate queries."""
        empty = {status: 0 for status in DELIVERY_STATUSES}
        if not self.available:
            return {"accessible": False, "counts": empty,
                    "last_delivery_at": None, "last_delivery_status": None,
                    "retention_limit": self.retention}
        try:
            with self._lock, self._connection() as connection:
                connection.execute("SELECT 1").fetchone()
                rows = connection.execute(
                    "SELECT status, COUNT(*) FROM notification_deliveries GROUP BY status"
                ).fetchall()
                latest_row = connection.execute(
                    "SELECT status, COALESCE(delivered_at, last_attempt_at, created_at) "
                    "FROM notification_deliveries ORDER BY id DESC LIMIT 1"
                ).fetchone()
                latest = latest_row[1] if latest_row else None
                latest_status = latest_row[0] if latest_row else None
            counts = dict(empty)
            counts.update({str(status): int(count) for status, count in rows})
            return {"accessible": True, "counts": counts,
                    "last_delivery_at": latest, "last_delivery_status": latest_status,
                    "retention_limit": self.retention}
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return {"accessible": False, "counts": empty,
                    "last_delivery_at": None, "last_delivery_status": None,
                    "retention_limit": self.retention}

    def due_retries(self, now=None, limit: int = 100):
        if not self.available:
            return []
        cutoff = timestamp_text(now or utc_now())
        try:
            with self._lock, self._connection() as connection:
                rows = connection.execute(
                    f"""SELECT {_SELECT_COLUMNS} FROM notification_deliveries
                    WHERE status = ? AND next_retry_at IS NOT NULL AND next_retry_at <= ?
                    ORDER BY event_timestamp ASC, id ASC LIMIT ?""",
                    (STATUS_RETRYING, cutoff, max(1, int(limit))),
                ).fetchall()
            return [DeliveryRecord(*row) for row in rows]
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return []

    def failed_deliveries(self):
        return [row for row in self.list_deliveries(status=STATUS_FAILED)]

    def clear_terminal(self) -> bool:
        return self._write(
            "DELETE FROM notification_deliveries WHERE status IN (?, ?)",
            TERMINAL_STATUSES,
        )

    def recover_interrupted(self, retry_later_enabled: bool, *, now=None) -> bool:
        """Make pre-crash QUEUED rows terminal or startup-retryable, never stuck."""
        if not self.available:
            return False
        due = timestamp_text(now or utc_now())
        try:
            with self._lock, self._connection() as connection:
                if retry_later_enabled:
                    connection.execute(
                        """UPDATE notification_deliveries SET status = ?, next_retry_at = ?,
                           last_error_category = ?, last_error_summary = ?
                           WHERE status = ? AND provider IN (?, ?)""",
                        (STATUS_RETRYING, due, "NETWORK", "Delivery interrupted before completion",
                         STATUS_QUEUED, "generic_webhook", "teams_webhook"),
                    )
                connection.execute(
                    """UPDATE notification_deliveries SET status = ?, next_retry_at = NULL,
                       last_error_category = ?, last_error_summary = ? WHERE status = ?""",
                    (STATUS_FAILED, "UNKNOWN", "Delivery interrupted before completion", STATUS_QUEUED),
                )
            return True
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return False

    def prune_terminal(self) -> bool:
        return self._write(
            """DELETE FROM notification_deliveries
               WHERE status IN (?, ?) AND id NOT IN (
                   SELECT id FROM notification_deliveries
                   WHERE status IN (?, ?) ORDER BY id DESC LIMIT ?
               )""",
            TERMINAL_STATUSES + TERMINAL_STATUSES + (self.retention,),
        )
