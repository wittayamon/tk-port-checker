"""UI-independent target group and planned-maintenance helpers."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional


MAX_GROUP_LENGTH = 32
MAX_GROUPS = 10
MAX_MAINTENANCE_REASON = 200
MANUAL_DURATION = "Until manually ended"
DURATION_OPTIONS = (
    MANUAL_DURATION,
    "30 minutes",
    "1 hour",
    "2 hours",
    "4 hours",
    "Custom End Time",
)
_DURATION_MINUTES = {
    "30 minutes": 30,
    "1 hour": 60,
    "2 hours": 120,
    "4 hours": 240,
}


def normalize_groups(value, *, strict: bool = False) -> list[str]:
    """Normalize a comma string or iterable, preserving the first clean casing."""
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = ()
    groups = []
    seen = set()
    for candidate in candidates:
        group = str(candidate or "").strip()
        if not group:
            continue
        if len(group) > MAX_GROUP_LENGTH:
            if strict:
                raise ValueError(f"Each group must be {MAX_GROUP_LENGTH} characters or fewer.")
            continue
        folded = group.casefold()
        if folded in seen:
            continue
        if len(groups) >= MAX_GROUPS:
            if strict:
                raise ValueError(f"A target may have at most {MAX_GROUPS} groups.")
            break
        seen.add(folded)
        groups.append(group)
    return groups


def group_matches(groups: Iterable[str], selected: str) -> bool:
    selected_text = str(selected or "").strip()
    if not selected_text or selected_text.casefold() == "all groups":
        return True
    wanted = selected_text.casefold()
    return any(str(group).strip().casefold() == wanted for group in groups)


def current_group_list(records: Iterable[Mapping]) -> list[str]:
    display = {}
    for record in records:
        for group in normalize_groups(record.get("groups", [])):
            display.setdefault(group.casefold(), group)
    return sorted(display.values(), key=str.casefold)


def parse_local_timestamp(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def timestamp_text(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    aware = value.astimezone() if value.tzinfo is None else value
    return aware.isoformat(timespec="seconds")


@dataclass(frozen=True)
class MaintenanceState:
    enabled: bool = False
    started_at: Optional[datetime] = None
    until: Optional[datetime] = None
    reason: str = ""

    def to_config(self) -> dict:
        return {
            "enabled": self.enabled,
            "started_at": timestamp_text(self.started_at),
            "until": timestamp_text(self.until),
            "reason": self.reason,
        }


def normalize_maintenance(value) -> MaintenanceState:
    """Load old or malformed configuration without raising."""
    if not isinstance(value, Mapping) or value.get("enabled") is not True:
        return MaintenanceState()
    started = parse_local_timestamp(value.get("started_at"))
    until = parse_local_timestamp(value.get("until"))
    reason = str(value.get("reason", "") or "").strip()[:MAX_MAINTENANCE_REASON]
    if started is None or (until is not None and until <= started):
        return MaintenanceState()
    return MaintenanceState(True, started, until, reason)


def start_maintenance(
    duration: str,
    *,
    reason: str = "",
    custom_end: str = "",
    now: Optional[datetime] = None,
) -> MaintenanceState:
    started = now or datetime.now().astimezone()
    started = started.astimezone() if started.tzinfo is None else started
    clean_reason = str(reason or "").strip()
    if len(clean_reason) > MAX_MAINTENANCE_REASON:
        raise ValueError(f"Reason must be {MAX_MAINTENANCE_REASON} characters or fewer.")
    if duration == MANUAL_DURATION:
        until = None
    elif duration in _DURATION_MINUTES:
        until = started + timedelta(minutes=_DURATION_MINUTES[duration])
    elif duration == "Custom End Time":
        until = parse_local_timestamp(custom_end)
        if until is None:
            raise ValueError("Custom End Time must use YYYY-MM-DD HH:MM.")
        if until <= started:
            raise ValueError("Custom End Time must be in the future.")
    else:
        raise ValueError("Select a valid maintenance duration.")
    return MaintenanceState(True, started, until, clean_reason)


def is_maintenance_active(state: MaintenanceState, now: Optional[datetime] = None) -> bool:
    if not state.enabled or state.started_at is None:
        return False
    current = now or datetime.now().astimezone()
    current = current.astimezone() if current.tzinfo is None else current
    return state.until is None or current < state.until


def maintenance_has_expired(state: MaintenanceState, now: Optional[datetime] = None) -> bool:
    if not state.enabled or state.until is None:
        return False
    current = now or datetime.now().astimezone()
    current = current.astimezone() if current.tzinfo is None else current
    return current >= state.until


def expire_maintenance(state: MaintenanceState, now: Optional[datetime] = None):
    """Return (new state, expired, event time); repeated calls are idempotent.

    Persisting the disabled replacement before the next scheduler tick prevents
    restart/timer races from emitting duplicate MAINTENANCE_ENDED evidence.
    """
    if not maintenance_has_expired(state, now):
        return state, False, None
    return MaintenanceState(), True, state.until


def filter_operational_alerts(alerts):
    """Suppress maintenance transitions before any UI/provider enqueue path."""
    return [alert for alert in alerts if not alert.get("maintenance_active", False)]
