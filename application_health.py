"""Secret-safe, UI-independent application health snapshots and export."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional


HEALTHY = "HEALTHY"
WARNING = "WARNING"
ERROR = "ERROR"
UNKNOWN = "UNKNOWN"
_VALID_STATUSES = {HEALTHY, WARNING, ERROR, UNKNOWN}
_SECRET_KEY_PARTS = (
    "authorization", "credential", "endpoint", "password", "secret", "token",
    "webhook", "url",
)
_INVENTORY_KEY_PARTS = ("hosts", "targets", "devices", "inventory")


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(timespec="seconds")
    return str(value)


def _safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Whitelist scalar operational facts and reject secret/inventory-shaped keys."""
    safe = {}
    for key, value in details.items():
        name = str(key)
        folded = name.casefold()
        if any(part in folded for part in _SECRET_KEY_PARTS + _INVENTORY_KEY_PARTS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[name] = value
        elif isinstance(value, datetime):
            safe[name] = _iso(value)
        elif isinstance(value, Mapping):
            safe[name] = _safe_details(value)
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            safe[name] = list(value)
    return safe


@dataclass(frozen=True)
class ComponentHealth:
    """One component's safe status; summaries must never contain secret values."""

    name: str
    status: str
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)
    last_updated: Optional[datetime] = None

    def __post_init__(self):
        if self.status not in _VALID_STATUSES:
            object.__setattr__(self, "status", UNKNOWN)
        # Component producers use controlled summaries; reject accidental raw
        # secret-shaped text as a final export boundary defense.
        folded_summary = self.summary.casefold()
        if "http://" in folded_summary or "https://" in folded_summary or any(
            f"{part}=" in folded_summary for part in _SECRET_KEY_PARTS
        ):
            object.__setattr__(self, "summary", "Sensitive diagnostic detail redacted")
        object.__setattr__(self, "details", _safe_details(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
            "last_updated": _iso(self.last_updated),
        }


def aggregate_status(components: Iterable[ComponentHealth]) -> str:
    statuses = {component.status for component in components}
    if ERROR in statuses:
        return ERROR
    if WARNING in statuses:
        return WARNING
    if HEALTHY in statuses:
        return HEALTHY
    return UNKNOWN


@dataclass(frozen=True)
class HealthSnapshot:
    """Immutable aggregate suitable for UI display, clipboard text, and JSON."""

    version: str
    generated_at: datetime
    process_started_at: datetime
    components: tuple[ComponentHealth, ...]

    @property
    def overall_status(self) -> str:
        return aggregate_status(self.components)

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, (self.generated_at - self.process_started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return {
            "application": "MultiPortChecker",
            "version": self.version,
            "generated_at": _iso(self.generated_at),
            "overall_status": self.overall_status,
            "uptime_seconds": round(self.uptime_seconds, 3),
            "components": [component.to_dict() for component in self.components],
        }

    def summary_text(self) -> str:
        lines = [
            f"MultiPortChecker {self.version}",
            f"Overall Status: {self.overall_status}",
            f"Application Uptime: {format_age(self.uptime_seconds)}",
        ]
        lines.extend(
            f"{component.name}: {component.status} - {component.summary}"
            for component in self.components
        )
        return "\n".join(lines)


def format_age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "Never"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_left = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds_left}s"
    return f"{seconds_left}s"


def application_component(*, version: str, frozen: bool) -> ComponentHealth:
    details = {
        "version": version,
        "running_mode": "frozen" if frozen else "source",
        "platform": platform.platform(),
    }
    if not frozen:
        details["python_version"] = platform.python_version()
    return ComponentHealth("Application", HEALTHY, f"Version {version}", details)


def monitoring_component(
    *, now: datetime, auto_refresh: bool, refresh_interval_seconds: int,
    last_successful_at: Optional[datetime], last_duration_ms: Optional[float],
    persistent_count: int, visible_count: int, scan_active: bool,
    last_started_at: Optional[datetime] = None,
    last_completed_at: Optional[datetime] = None,
) -> ComponentHealth:
    age = None if last_successful_at is None else max(
        0.0, (now - last_successful_at).total_seconds()
    )
    details = {
        "persistent_count": persistent_count,
        "visible_count": visible_count,
        "auto_refresh": auto_refresh,
        "scan_active": scan_active,
        "last_cycle_started_at": _iso(last_started_at),
        "last_cycle_completed_at": _iso(last_completed_at),
        "last_successful_cycle_at": _iso(last_successful_at),
        "last_cycle_duration_ms": last_duration_ms,
    }
    if not auto_refresh:
        return ComponentHealth("Monitoring", HEALTHY, "Idle (Auto Refresh disabled)", details, now)
    stale_after = max(3 * max(1, refresh_interval_seconds), 60)
    if age is None or age > stale_after:
        return ComponentHealth(
            "Monitoring", WARNING, "Auto Refresh has no recent successful cycle",
            {**details, "stale_after_seconds": stale_after}, now,
        )
    return ComponentHealth(
        "Monitoring", HEALTHY, f"Last cycle {format_age(age)} ago", details, now
    )


def store_component(name: str, store, *, delivery=False, now=None) -> ComponentHealth:
    if store is None:
        return ComponentHealth(name, UNKNOWN, "Not initialized", last_updated=now)
    try:
        summary = store.health_summary()
    except Exception:
        return ComponentHealth(name, ERROR, "Database is inaccessible", last_updated=now)
    if not summary.get("accessible"):
        return ComponentHealth(name, ERROR, "Database is inaccessible", last_updated=now)
    if delivery:
        counts = summary.get("counts", {})
        failed, retrying = int(counts.get("FAILED", 0)), int(counts.get("RETRYING", 0))
        status = WARNING if failed or retrying else HEALTHY
        text = f"{failed} failed, {retrying} retrying" if status == WARNING else "Queue history healthy"
        return ComponentHealth(name, status, text, summary, now)
    return ComponentHealth(name, HEALTHY, f"{summary.get('row_count', 0)} events", summary, now)


def notification_component(manager, *, providers_enabled=False, now=None) -> ComponentHealth:
    if manager is None:
        return ComponentHealth("Notification System", UNKNOWN, "Not initialized", last_updated=now)
    try:
        details = manager.health_summary()
    except Exception:
        return ComponentHealth("Notification System", ERROR, "Worker state unavailable", last_updated=now)
    if (not details.get("worker_alive") or not details.get("scheduler_alive")) and not details.get("shutdown_started"):
        return ComponentHealth("Notification System", ERROR, "Worker stopped unexpectedly", details, now)
    summary = f"Queue depth {details.get('queue_size', 0)}"
    if not providers_enabled:
        summary += " (providers disabled)"
    return ComponentHealth("Notification System", HEALTHY, summary, details, now)


def maintenance_component(states, *, scheduler_active: bool, now: datetime, grace_seconds=5) -> ComponentHealth:
    active = [state for state in states if getattr(state, "enabled", False)]
    timed = [state for state in active if getattr(state, "until", None) is not None]
    manual = len(active) - len(timed)
    expiries = [state.until for state in timed]
    nearest = min(expiries) if expiries else None
    overdue = [value for value in expiries if (now - value).total_seconds() > grace_seconds]
    details = {
        "active_count": len(active), "timed_count": len(timed),
        "manual_count": manual, "next_expiry": _iso(nearest),
        "scheduler_active": scheduler_active,
    }
    if overdue:
        return ComponentHealth("Maintenance", WARNING, "Expired maintenance awaits cleanup", details, now)
    if not scheduler_active:
        return ComponentHealth("Maintenance", WARNING, "Expiry scheduler is inactive", details, now)
    return ComponentHealth("Maintenance", HEALTHY, f"{len(active)} active", details, now)


def simple_component(name, *, available: Optional[bool], summary: str, details=None, now=None):
    status = UNKNOWN if available is None else (HEALTHY if available else WARNING)
    return ComponentHealth(name, status, summary, details or {}, now)


def build_snapshot(*, version: str, process_started_at: datetime, components, now=None):
    current = now or datetime.now().astimezone()
    return HealthSnapshot(version, current, process_started_at, tuple(components))


def export_diagnostics_json(path: str, snapshot: HealthSnapshot) -> None:
    """Write aggregate diagnostics only; target inventory and secrets are excluded."""
    with open(path, "w", encoding="utf-8") as output:
        json.dump(snapshot.to_dict(), output, indent=2, ensure_ascii=False)
        output.write("\n")
