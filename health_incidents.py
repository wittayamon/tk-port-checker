"""Persistent, secret-safe history for meaningful application-health failures.

Health incidents are deliberately separate from TCP Event History.  A stable
fingerprint deduplicates an open condition, while resolved rows provide a
bounded timeline for diagnostics and operators.  Open rows are never pruned:
losing a live failure would hide the state the watchdog is reporting.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

SEVERITIES = ("INFO", "WARNING", "ERROR")
HEALTH_INCIDENT_RETENTION = 5000
_SECRET = re.compile(r"(https?://|authorization|credential|password|secret|token|webhook|endpoint|api[_ -]?key)", re.I)


def _timestamp(value=None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")


def _safe_text(value, fallback="") -> str:
    text = str(value or "").strip()
    if _SECRET.search(text):
        return fallback or "Sensitive diagnostic detail redacted"
    return text[:500]


@dataclass(frozen=True)
class HealthIncident:
    id: int
    created_at: str
    component: str
    severity: str
    event_type: str
    summary: str
    details: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: Optional[str]
    occurrence_count: int
    recovery_action: str
    recovery_result: str
    fingerprint: str

    @property
    def status(self) -> str:
        return "RESOLVED" if self.resolved_at else "OPEN"


class HealthIncidentStore:
    """Short-lived SQLite connections make watchdog, Tk, and health reads safe."""

    def __init__(self, path: str, retention: int = HEALTH_INCIDENT_RETENTION):
        self.path = os.path.abspath(path)
        self.retention = max(1, int(retention))
        self._lock = threading.RLock()
        self.available = False
        self.last_error = None
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.path, timeout=1)

    @contextmanager
    def _connection(self):
        with closing(self._connect()) as connection:
            with connection:
                yield connection

    def _initialize(self):
        try:
            with self._lock, self._connection() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS health_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    component TEXT NOT NULL, severity TEXT NOT NULL, event_type TEXT NOT NULL,
                    summary TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL, resolved_at TEXT, occurrence_count INTEGER NOT NULL DEFAULT 1,
                    recovery_action TEXT NOT NULL DEFAULT '', recovery_result TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL)""")
                db.execute("CREATE INDEX IF NOT EXISTS idx_health_incidents_open ON health_incidents(resolved_at)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_health_incidents_component ON health_incidents(component)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_health_incidents_created ON health_incidents(created_at)")
            self.available, self.last_error = True, None
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)

    def _row(self, row):
        return HealthIncident(*row)

    def record(self, *, component, severity, event_type, summary, details="", fingerprint=None, now=None,
               recovery_action="", recovery_result="") -> Optional[HealthIncident]:
        if severity not in SEVERITIES or not self.available:
            return None
        stamp = _timestamp(now)
        component = _safe_text(component, "Unknown component")
        event_type = _safe_text(event_type, "HEALTH")
        summary = _safe_text(summary, "Health condition detected")
        details = _safe_text(details)
        fingerprint = _safe_text(fingerprint or f"{component}:{event_type}:{summary}", "health-condition")[:300]
        try:
            with self._lock, self._connection() as db:
                row = db.execute("SELECT * FROM health_incidents WHERE fingerprint = ? AND resolved_at IS NULL ORDER BY id DESC LIMIT 1", (fingerprint,)).fetchone()
                if row:
                    db.execute("UPDATE health_incidents SET last_seen_at=?, occurrence_count=occurrence_count+1, severity=?, summary=?, details=?, recovery_action=?, recovery_result=? WHERE id=?", (stamp, severity, summary, details, _safe_text(recovery_action), _safe_text(recovery_result), row[0]))
                    row = db.execute("SELECT * FROM health_incidents WHERE id=?", (row[0],)).fetchone()
                else:
                    db.execute("INSERT INTO health_incidents (created_at,component,severity,event_type,summary,details,first_seen_at,last_seen_at,occurrence_count,recovery_action,recovery_result,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (stamp, component, severity, event_type, summary, details, stamp, stamp, 1, _safe_text(recovery_action), _safe_text(recovery_result), fingerprint))
                    row = db.execute("SELECT * FROM health_incidents WHERE id=last_insert_rowid()").fetchone()
            return self._row(row)
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return None

    def resolve(self, fingerprint: str, *, recovery_action="", recovery_result="", now=None) -> Optional[HealthIncident]:
        if not self.available:
            return None
        try:
            with self._lock, self._connection() as db:
                row = db.execute("SELECT id FROM health_incidents WHERE fingerprint=? AND resolved_at IS NULL ORDER BY id DESC LIMIT 1", (fingerprint,)).fetchone()
                if not row:
                    return None
                db.execute("UPDATE health_incidents SET resolved_at=?, last_seen_at=?, recovery_action=?, recovery_result=? WHERE id=?", (_timestamp(now), _timestamp(now), _safe_text(recovery_action), _safe_text(recovery_result), row[0]))
                return self._row(db.execute("SELECT * FROM health_incidents WHERE id=?", (row[0],)).fetchone())
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)
            return None

    def list(self, *, component="All", severity="All", status="All", search="", limit=500):
        if not self.available:
            return []
        clauses, args = [], []
        if component != "All": clauses.append("component=?"); args.append(component)
        if severity != "All": clauses.append("severity=?"); args.append(severity)
        if status == "OPEN": clauses.append("resolved_at IS NULL")
        elif status == "RESOLVED": clauses.append("resolved_at IS NOT NULL")
        if search:
            clauses.append("(component LIKE ? OR summary LIKE ?)"); args.extend([f"%{search}%", f"%{search}%"])
        query = "SELECT * FROM health_incidents" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(5000, int(limit))))
        try:
            with self._lock, self._connection() as db:
                return [self._row(row) for row in db.execute(query, args).fetchall()]
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc); return []

    def clear_resolved(self) -> int:
        if not self.available: return 0
        try:
            with self._lock, self._connection() as db:
                cursor = db.execute("DELETE FROM health_incidents WHERE resolved_at IS NOT NULL")
                return cursor.rowcount
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc); return 0

    def prune(self):
        if not self.available: return
        try:
            with self._lock, self._connection() as db:
                db.execute("DELETE FROM health_incidents WHERE resolved_at IS NOT NULL AND id NOT IN (SELECT id FROM health_incidents WHERE resolved_at IS NOT NULL ORDER BY id DESC LIMIT ?)", (self.retention,))
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc)

    def summary(self) -> dict:
        if not self.available:
            return {"accessible": False, "open_count": 0, "open_warning_count": 0, "open_error_count": 0, "last_incident_at": None}
        try:
            with self._lock, self._connection() as db:
                rows = db.execute("SELECT severity, COUNT(*) FROM health_incidents WHERE resolved_at IS NULL GROUP BY severity").fetchall()
                latest = db.execute("SELECT created_at FROM health_incidents ORDER BY id DESC LIMIT 1").fetchone()
            counts = {severity: 0 for severity in SEVERITIES}; counts.update({str(k): int(v) for k, v in rows})
            return {"accessible": True, "open_count": sum(counts.values()), "open_warning_count": counts["WARNING"], "open_error_count": counts["ERROR"], "last_incident_at": latest[0] if latest else None}
        except (OSError, sqlite3.Error) as exc:
            self.last_error = str(exc); return {"accessible": False, "open_count": 0, "open_warning_count": 0, "open_error_count": 0, "last_incident_at": None}
