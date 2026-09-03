from dataclasses import dataclass
from datetime import datetime
from typing import Hashable, Mapping, Optional


TCP_UNKNOWN = "UNKNOWN"
TCP_ONLINE = "ONLINE"
TCP_OFFLINE = "OFFLINE"
EVENT_DOWN = "DOWN"
EVENT_RECOVERED = "RECOVERED"


def normalize_host_record(record: Mapping) -> dict:
    """Return the backward-compatible persistent fields for one target."""
    name = str(record.get("name", "") or "").strip()
    host = str(record.get("host", "") or "").strip()
    port = record.get("port", "")
    return {"name": name, "host": host, "port": port}


def make_host_record(name: str, host: str, port) -> dict:
    """Build a host record without including runtime monitoring state."""
    return {
        "name": str(name or "").strip(),
        "host": str(host or "").strip(),
        "port": port,
    }


def alert_enabled_from_config(config: Mapping) -> bool:
    """Read the alert preference, defaulting old config files to enabled."""
    value = config.get("state_change_alerts", True)
    return value if isinstance(value, bool) else True


def format_duration(seconds: float) -> str:
    """Format a non-negative duration using compact hour/minute/second units."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_left = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds_left or not parts:
        parts.append(f"{seconds_left}s")
    return " ".join(parts)


@dataclass(frozen=True)
class StateChangeEvent:
    kind: str
    occurred_at: datetime
    downtime_seconds: Optional[float] = None


@dataclass
class _TargetState:
    status: str = TCP_UNKNOWN
    outage_started: Optional[datetime] = None


class TcpStateTracker:
    """Track TCP transitions for persistent targets without any UI dependency."""

    def __init__(self):
        self._states = {}

    def observe(
        self,
        key: Hashable,
        port_online: bool,
        *,
        persistent: bool = True,
        now: Optional[datetime] = None,
    ) -> Optional[StateChangeEvent]:
        if not persistent:
            return None

        observed_at = now or datetime.now()
        new_status = TCP_ONLINE if port_online else TCP_OFFLINE
        state = self._states.setdefault(key, _TargetState())
        previous_status = state.status

        if previous_status == TCP_UNKNOWN:
            state.status = new_status
            state.outage_started = observed_at if new_status == TCP_OFFLINE else None
            return None

        if previous_status == new_status:
            return None

        state.status = new_status
        if new_status == TCP_OFFLINE:
            state.outage_started = observed_at
            return StateChangeEvent(EVENT_DOWN, observed_at)

        downtime_seconds = None
        if state.outage_started is not None:
            downtime_seconds = max(
                0.0, (observed_at - state.outage_started).total_seconds()
            )
        state.outage_started = None
        return StateChangeEvent(EVENT_RECOVERED, observed_at, downtime_seconds)

    def forget(self, key: Hashable) -> None:
        self._states.pop(key, None)

    def clear(self) -> None:
        self._states.clear()

