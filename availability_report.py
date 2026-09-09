"""UI-independent availability reporting derived from TCP Event History."""

import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional, Sequence

from event_history import EventRecord, EventHistoryStore
from monitoring_state import (
    EVENT_DOWN,
    EVENT_MAINTENANCE_ENDED,
    EVENT_MAINTENANCE_STARTED,
    EVENT_RECOVERED,
    format_duration,
)


PERIOD_TODAY = "Today"
PERIOD_7_DAYS = "7 Days"
PERIOD_30_DAYS = "30 Days"
PERIOD_CUSTOM = "Custom"
PERIODS = (PERIOD_TODAY, PERIOD_7_DAYS, PERIOD_30_DAYS, PERIOD_CUSTOM)

SUMMARY_CSV_COLUMNS = (
    "device_name", "host", "port", "groups", "period_start", "period_end",
    "availability_percent", "raw_availability_percent", "operational_availability_percent",
    "coverage_percent", "period_duration_seconds", "known_duration_seconds",
    "unknown_duration_seconds", "downtime_seconds", "outage_count",
    "planned_maintenance_seconds", "planned_downtime_seconds",
    "unplanned_downtime_seconds", "unplanned_outage_count",
    "longest_outage_seconds", "average_outage_seconds", "mttr_seconds",
    "downtime_display", "longest_outage_display", "mttr_display",
)
OUTAGE_CSV_COLUMNS = (
    "device_name", "host", "port", "down_timestamp", "recovered_timestamp",
    "status", "actual_duration_seconds", "period_overlap_seconds",
    "period_overlap_display", "maintenance_overlap_seconds",
    "maintenance_overlap_display", "unplanned_downtime_seconds",
    "unplanned_downtime_display", "classification",
)


@dataclass(frozen=True)
class ConfiguredTarget:
    device_name: str
    host: str
    port: int
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutageDetail:
    device_name: str
    host: str
    port: int
    down_at: datetime
    recovered_at: Optional[datetime]
    status: str
    actual_duration_seconds: Optional[float]
    period_overlap_seconds: float
    maintenance_overlap_seconds: float = 0.0
    unplanned_downtime_seconds: float = 0.0
    classification: str = "UNPLANNED"


@dataclass(frozen=True)
class AvailabilityRow:
    device_name: str
    host: str
    port: int
    period_start: datetime
    period_end: datetime
    availability_percent: Optional[float]
    coverage_percent: float
    period_duration_seconds: float
    known_duration_seconds: float
    unknown_duration_seconds: float
    downtime_seconds: float
    outage_count: int
    longest_outage_seconds: float
    average_outage_seconds: Optional[float]
    mttr_seconds: Optional[float]
    groups: tuple[str, ...] = ()
    operational_availability_percent: Optional[float] = None
    planned_maintenance_seconds: float = 0.0
    planned_downtime_seconds: float = 0.0
    unplanned_downtime_seconds: float = 0.0
    operational_eligible_seconds: float = 0.0
    unplanned_outage_count: int = 0

    @property
    def display_name(self) -> str:
        return self.device_name or self.host

    @property
    def raw_availability_percent(self) -> Optional[float]:
        return self.availability_percent


@dataclass(frozen=True)
class AvailabilityReport:
    period_start: datetime
    period_end: datetime
    rows: tuple[AvailabilityRow, ...]
    outages: tuple[OutageDetail, ...]


@dataclass(frozen=True)
class _TimedEvent:
    occurred_at: datetime
    record: EventRecord
    sequence: int


def _aware(value: datetime) -> datetime:
    return value.astimezone() if value.tzinfo is None else value


def parse_event_timestamp(value: str) -> Optional[datetime]:
    try:
        return _aware(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def intersect_interval(
    interval_start: datetime,
    interval_end: datetime,
    period_start: datetime,
    period_end: datetime,
) -> float:
    """Return seconds in the half-open intersection of two intervals."""
    start = max(_aware(interval_start), _aware(period_start))
    end = min(_aware(interval_end), _aware(period_end))
    return max(0.0, (end - start).total_seconds())


def report_period(
    period: str,
    *,
    now: Optional[datetime] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime]:
    """Resolve report periods using local time and half-open boundaries."""
    current = _aware(now or datetime.now().astimezone())
    if period == PERIOD_TODAY:
        return current.replace(hour=0, minute=0, second=0, microsecond=0), current
    if period == PERIOD_7_DAYS:
        return current - timedelta(days=7), current
    if period == PERIOD_30_DAYS:
        return current - timedelta(days=30), current
    if period != PERIOD_CUSTOM:
        raise ValueError("Select a valid report period.")
    try:
        start_day = date.fromisoformat(str(start_date or "").strip())
        end_day = date.fromisoformat(str(end_date or "").strip())
    except ValueError as exc:
        raise ValueError("Start Date and End Date must use YYYY-MM-DD.") from exc
    if end_day < start_day:
        raise ValueError("End Date must be on or after Start Date.")
    zone = current.tzinfo
    start = datetime.combine(start_day, time.min, tzinfo=zone)
    end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=zone)
    if end_day >= current.date():
        end = current
    if start >= end:
        raise ValueError("The selected custom range has not started.")
    return start, end


def _normalize_events(events: Iterable[EventRecord]) -> list[_TimedEvent]:
    normalized = []
    for sequence, event in enumerate(events):
        if str(event.event_type).upper() not in (
            EVENT_DOWN, EVENT_RECOVERED,
            EVENT_MAINTENANCE_STARTED, EVENT_MAINTENANCE_ENDED,
        ):
            continue
        occurred_at = parse_event_timestamp(event.timestamp)
        try:
            port = int(event.port)
        except (TypeError, ValueError):
            continue
        if occurred_at is None or not str(event.host).strip():
            continue
        if port != event.port:
            event = EventRecord(
                event.timestamp, event.event_type, event.device_name, event.host,
                port, event.ping, event.previous_status, event.new_status,
                event.downtime_seconds,
            )
        normalized.append(_TimedEvent(occurred_at, event, sequence))
    normalized.sort(key=lambda item: (item.occurred_at, item.sequence))
    return normalized


def _target_key(host: str, port: int) -> tuple[str, int]:
    return str(host).strip().casefold(), int(port)


def reconstruct_state_intervals(
    events: Sequence[_TimedEvent], period_start: datetime, period_end: datetime
) -> tuple[float, float]:
    """Return known duration and known offline duration for one target."""
    state = "UNKNOWN"
    for item in events:
        if item.occurred_at >= period_start:
            break
        kind = item.record.event_type.upper()
        if kind == EVENT_DOWN:
            state = "OFFLINE"
        elif kind == EVENT_RECOVERED:
            state = "ONLINE"

    known = 0.0
    downtime = 0.0
    cursor = period_start
    for item in events:
        when = item.occurred_at
        if when < period_start:
            continue
        if when > period_end:
            break
        elapsed = max(0.0, (when - cursor).total_seconds())
        if state != "UNKNOWN":
            known += elapsed
            if state == "OFFLINE":
                downtime += elapsed
        cursor = max(cursor, when)
        kind = item.record.event_type.upper()
        if kind == EVENT_DOWN and state != "OFFLINE":
            state = "OFFLINE"
        elif kind == EVENT_RECOVERED and state != "ONLINE":
            state = "ONLINE"

    elapsed = max(0.0, (period_end - cursor).total_seconds())
    if state != "UNKNOWN":
        known += elapsed
        if state == "OFFLINE":
            downtime += elapsed
    return known, downtime


def merge_intervals(intervals):
    """Merge overlapping or touching aware datetime intervals."""
    ordered = sorted(
        ((_aware(start), _aware(end)) for start, end in intervals if _aware(start) < _aware(end)),
        key=lambda pair: pair[0],
    )
    merged = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def calculate_maintenance_overlap(interval_start, interval_end, maintenance_intervals) -> float:
    """Return unioned maintenance seconds inside one interval."""
    return sum(
        intersect_interval(interval_start, interval_end, start, end)
        for start, end in merge_intervals(maintenance_intervals)
    )


def _indexed_interval_overlap(interval_start, interval_end, merged_intervals, interval_ends) -> float:
    """Overlap against pre-merged intervals without rescanning earlier windows."""
    start, end = _aware(interval_start), _aware(interval_end)
    index = bisect_right(interval_ends, start)
    total = 0.0
    while index < len(merged_intervals) and merged_intervals[index][0] < end:
        left, right = merged_intervals[index]
        total += max(0.0, (min(end, right) - max(start, left)).total_seconds())
        index += 1
    return total


def reconstruct_maintenance_intervals(events, period_start, period_end):
    """Rebuild persisted planned-maintenance windows and clip to the report."""
    active_since = None
    intervals = []
    for item in events:
        kind = item.record.event_type.upper()
        if kind == EVENT_MAINTENANCE_STARTED:
            if active_since is None:
                active_since = item.occurred_at
        elif kind == EVENT_MAINTENANCE_ENDED and active_since is not None:
            if item.occurred_at > active_since:
                intervals.append((active_since, item.occurred_at))
            active_since = None
    if active_since is not None:
        intervals.append((active_since, period_end))
    return merge_intervals(
        (max(start, period_start), min(end, period_end))
        for start, end in intervals if end > period_start and start < period_end
    )


def reconstruct_state_segments(events, period_start, period_end):
    """Return known ONLINE/OFFLINE segments inside the report period."""
    state = "UNKNOWN"
    for item in events:
        if item.occurred_at >= period_start:
            break
        kind = item.record.event_type.upper()
        if kind == EVENT_DOWN:
            state = "OFFLINE"
        elif kind == EVENT_RECOVERED:
            state = "ONLINE"
    cursor = period_start
    segments = []
    for item in events:
        when = item.occurred_at
        if when < period_start:
            continue
        if when > period_end:
            break
        if state != "UNKNOWN" and when > cursor:
            segments.append((cursor, when, state))
        cursor = max(cursor, when)
        kind = item.record.event_type.upper()
        if kind == EVENT_DOWN:
            state = "OFFLINE"
        elif kind == EVENT_RECOVERED:
            state = "ONLINE"
    if state != "UNKNOWN" and cursor < period_end:
        segments.append((cursor, period_end, state))
    return segments


def _outages_for_target(
    events: Sequence[_TimedEvent], period_start: datetime, period_end: datetime,
    device_name: str, host: str, port: int, maintenance_intervals=(),
) -> list[OutageDetail]:
    outages = []
    maintenance_intervals = merge_intervals(maintenance_intervals)
    maintenance_ends = [end for _start, end in maintenance_intervals]
    state = "UNKNOWN"
    down_at = None
    for item in events:
        kind = item.record.event_type.upper()
        if kind == EVENT_DOWN:
            if state != "OFFLINE":
                state = "OFFLINE"
                down_at = item.occurred_at
        elif kind == EVENT_RECOVERED:
            if state == "OFFLINE" and down_at is not None:
                overlap = intersect_interval(down_at, item.occurred_at, period_start, period_end)
                if overlap > 0:
                    maintenance_overlap = _indexed_interval_overlap(
                        max(down_at, period_start), min(item.occurred_at, period_end),
                        maintenance_intervals, maintenance_ends,
                    )
                    unplanned = max(0.0, overlap - maintenance_overlap)
                    outages.append(OutageDetail(
                        device_name, host, port, down_at, item.occurred_at,
                        "RECOVERED", max(0.0, (item.occurred_at - down_at).total_seconds()),
                        overlap, maintenance_overlap, unplanned,
                        classify_outage(overlap, maintenance_overlap),
                    ))
                down_at = None
            state = "ONLINE"
    if state == "OFFLINE" and down_at is not None:
        overlap = intersect_interval(down_at, period_end, period_start, period_end)
        if overlap > 0:
            maintenance_overlap = _indexed_interval_overlap(
                max(down_at, period_start), period_end, maintenance_intervals,
                maintenance_ends,
            )
            unplanned = max(0.0, overlap - maintenance_overlap)
            outages.append(OutageDetail(
                device_name, host, port, down_at, None, "ONGOING", None, overlap,
                maintenance_overlap, unplanned,
                classify_outage(overlap, maintenance_overlap),
            ))
    return outages


def classify_outage(outage_seconds: float, maintenance_overlap_seconds: float) -> str:
    if outage_seconds <= 0 or maintenance_overlap_seconds <= 0:
        return "UNPLANNED"
    if maintenance_overlap_seconds >= outage_seconds - 0.001:
        return "PLANNED"
    return "MIXED"


def calculate_availability(
    events: Iterable[EventRecord],
    period_start: datetime,
    period_end: datetime,
    configured_targets: Iterable[ConfiguredTarget] = (),
) -> AvailabilityReport:
    """Build availability rows without mutating either history store.

    UNKNOWN intervals never enter the raw or operational denominator. Raw
    availability remains TCP-only; maintenance subtraction is applied solely to
    operational eligibility after known state segments are reconstructed.
    """
    start, end = _aware(period_start), _aware(period_end)
    if start >= end:
        raise ValueError("Report end must be after report start.")
    normalized = _normalize_events(events)
    grouped: dict[tuple[str, int], list[_TimedEvent]] = {}
    names: dict[tuple[str, int], str] = {}
    configured_names: dict[tuple[str, int], str] = {}
    configured_groups: dict[tuple[str, int], tuple[str, ...]] = {}
    display_hosts: dict[tuple[str, int], str] = {}
    configured_keys = set()
    for target in configured_targets:
        try:
            key = _target_key(target.host, target.port)
        except (TypeError, ValueError):
            continue
        if not key[0]:
            continue
        configured_keys.add(key)
        display_hosts[key] = str(target.host).strip()
        if str(target.device_name or "").strip():
            configured_names[key] = str(target.device_name).strip()
        configured_groups[key] = tuple(target.groups)
    for item in normalized:
        key = _target_key(item.record.host, item.record.port)
        grouped.setdefault(key, []).append(item)
        display_hosts[key] = str(item.record.host).strip()
        if str(item.record.device_name or "").strip():
            names[key] = str(item.record.device_name).strip()
    names.update(configured_names)

    # Historical targets appear only when evidence exists at or before period end.
    keys = configured_keys | {
        key for key, items in grouped.items()
        if any(item.occurred_at <= end for item in items)
    }
    period_seconds = (end - start).total_seconds()
    rows = []
    all_outages = []
    for key in keys:
        target_events = grouped.get(key, [])
        host, port = display_hosts[key], key[1]
        name = names.get(key, "")
        state_segments = reconstruct_state_segments(target_events, start, end)
        known = sum((segment_end - segment_start).total_seconds() for segment_start, segment_end, _state in state_segments)
        downtime = sum((segment_end - segment_start).total_seconds() for segment_start, segment_end, state in state_segments if state == "OFFLINE")
        unknown = max(0.0, period_seconds - known)
        availability = None if known <= 0 else max(0.0, (known - downtime) / known * 100.0)
        coverage = known / period_seconds * 100.0
        maintenance_intervals = reconstruct_maintenance_intervals(target_events, start, end)
        maintenance_ends = [interval_end for _interval_start, interval_end in maintenance_intervals]
        planned_maintenance = sum((right - left).total_seconds() for left, right in maintenance_intervals)
        known_in_maintenance = sum(
            _indexed_interval_overlap(left, right, maintenance_intervals, maintenance_ends)
            for left, right, _state in state_segments
        )
        planned_downtime = sum(
            _indexed_interval_overlap(left, right, maintenance_intervals, maintenance_ends)
            for left, right, state in state_segments if state == "OFFLINE"
        )
        unplanned_downtime = max(0.0, downtime - planned_downtime)
        eligible = max(0.0, known - known_in_maintenance)
        operational = None if eligible <= 0 else max(0.0, (eligible - unplanned_downtime) / eligible * 100.0)
        outages = _outages_for_target(target_events, start, end, name, host, port, maintenance_intervals)
        overlaps = [outage.period_overlap_seconds for outage in outages]
        completed = [
            outage.actual_duration_seconds for outage in outages
            if outage.recovered_at is not None and outage.recovered_at <= end
            and outage.actual_duration_seconds is not None
        ]
        count = len(outages)
        rows.append(AvailabilityRow(
            name, host, port, start, end, availability, coverage, period_seconds, known, unknown,
            downtime, count, max(overlaps, default=0.0),
            (sum(overlaps) / count) if count else None,
            (sum(completed) / len(completed)) if completed else None,
            configured_groups.get(key, ()), operational, planned_maintenance,
            planned_downtime, unplanned_downtime, eligible,
            sum(1 for outage in outages if outage.unplanned_downtime_seconds > 0),
        ))
        all_outages.extend(outages)
    rows.sort(key=lambda row: (row.display_name.casefold(), row.host.casefold(), row.port))
    all_outages.sort(key=lambda outage: outage.down_at, reverse=True)
    return AvailabilityReport(start, end, tuple(rows), tuple(all_outages))


def build_availability_report(
    store: EventHistoryStore,
    period_start: datetime,
    period_end: datetime,
    configured_targets: Iterable[ConfiguredTarget] = (),
) -> AvailabilityReport:
    """Read the retained Event History snapshot and calculate a report."""
    return calculate_availability(
        store.list_events(oldest_first=True), period_start, period_end, configured_targets
    )


def filter_report_rows(rows: Iterable[AvailabilityRow], search: str = "", group: str = "All Groups") -> list[AvailabilityRow]:
    needle = str(search or "").strip().casefold()
    selected = str(group or "All Groups").casefold()
    return [
        row for row in rows
        if (not needle or needle in row.display_name.casefold() or needle in row.host.casefold())
        and (selected == "all groups" or any(item.casefold() == selected for item in row.groups))
    ]


def filter_outages(outages: Iterable[OutageDetail], search: str = "") -> list[OutageDetail]:
    needle = str(search or "").strip().casefold()
    if not needle:
        return list(outages)
    return [row for row in outages if needle in (row.device_name or row.host).casefold() or needle in row.host.casefold()]


def sort_report_rows(rows: Iterable[AvailabilityRow], column: str, reverse: bool = False) -> list[AvailabilityRow]:
    keys = {
        "device": lambda row: (row.display_name.casefold(), row.host.casefold(), row.port),
        "availability": lambda row: (-1.0 if row.availability_percent is None else row.availability_percent),
        "operational": lambda row: (-1.0 if row.operational_availability_percent is None else row.operational_availability_percent),
        "downtime": lambda row: row.downtime_seconds,
        "unplanned": lambda row: row.unplanned_downtime_seconds,
        "outages": lambda row: row.outage_count,
    }
    if column not in keys:
        raise ValueError("Unsupported report sort column.")
    return sorted(rows, key=keys[column], reverse=reverse)


def _number(value: Optional[float]):
    return "" if value is None else f"{value:.3f}".rstrip("0").rstrip(".")


def export_summary_csv(path: str, rows: Iterable[AvailabilityRow]) -> int:
    data = list(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=SUMMARY_CSV_COLUMNS)
        writer.writeheader()
        for row in data:
            writer.writerow({
                "device_name": row.device_name, "host": row.host, "port": row.port,
                "groups": ", ".join(row.groups),
                "period_start": row.period_start.isoformat(timespec="seconds"),
                "period_end": row.period_end.isoformat(timespec="seconds"),
                "availability_percent": _number(row.availability_percent),
                "raw_availability_percent": _number(row.availability_percent),
                "operational_availability_percent": _number(row.operational_availability_percent),
                "coverage_percent": _number(row.coverage_percent),
                "period_duration_seconds": _number(row.period_duration_seconds),
                "known_duration_seconds": _number(row.known_duration_seconds),
                "unknown_duration_seconds": _number(row.unknown_duration_seconds),
                "downtime_seconds": _number(row.downtime_seconds),
                "outage_count": row.outage_count,
                "planned_maintenance_seconds": _number(row.planned_maintenance_seconds),
                "planned_downtime_seconds": _number(row.planned_downtime_seconds),
                "unplanned_downtime_seconds": _number(row.unplanned_downtime_seconds),
                "unplanned_outage_count": row.unplanned_outage_count,
                "longest_outage_seconds": _number(row.longest_outage_seconds),
                "average_outage_seconds": _number(row.average_outage_seconds),
                "mttr_seconds": _number(row.mttr_seconds),
                "downtime_display": format_duration(row.downtime_seconds),
                "longest_outage_display": format_duration(row.longest_outage_seconds),
                "mttr_display": "-" if row.mttr_seconds is None else format_duration(row.mttr_seconds),
            })
    return len(data)


def export_outages_csv(path: str, outages: Iterable[OutageDetail]) -> int:
    data = list(outages)
    with open(path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTAGE_CSV_COLUMNS)
        writer.writeheader()
        for row in data:
            writer.writerow({
                "device_name": row.device_name, "host": row.host, "port": row.port,
                "down_timestamp": row.down_at.isoformat(timespec="seconds"),
                "recovered_timestamp": "" if row.recovered_at is None else row.recovered_at.isoformat(timespec="seconds"),
                "status": row.status,
                "actual_duration_seconds": _number(row.actual_duration_seconds),
                "period_overlap_seconds": _number(row.period_overlap_seconds),
                "period_overlap_display": format_duration(row.period_overlap_seconds),
                "maintenance_overlap_seconds": _number(row.maintenance_overlap_seconds),
                "maintenance_overlap_display": format_duration(row.maintenance_overlap_seconds),
                "unplanned_downtime_seconds": _number(row.unplanned_downtime_seconds),
                "unplanned_downtime_display": format_duration(row.unplanned_downtime_seconds),
                "classification": row.classification,
            })
    return len(data)
