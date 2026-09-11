"""Portable configuration only: no registry, SQLite, network or Tk dependencies.

Safe preferences are allowlisted, never a redacted full config dump. This keeps
future credentials out by default. Registry startup state is machine-local;
history and retries are operational evidence, not portable settings.

Config classification: PREFERENCES/NOTIFICATIONS and host/name/port/groups are
portable; provider URLs are sensitive; startup registration and storage paths
are machine-bound; maintenance, Ping/TCP values, filters and running schedules
are transient. Legacy list loading and SQLite storage remain separate owners.
"""

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app_version import APP_VERSION
from maintenance import normalize_groups
from monitoring_state import normalize_target_record
from network_checks import normalize_target_key
from webhook_notifications import endpoint_is_valid

BACKUP_FORMAT_VERSION = 1  # Schema compatibility is independent of app releases.
MAX_BACKUP_BYTES = 5 * 1024 * 1024
MAX_BACKUP_TARGETS = 10000
PREFERENCES = frozenset(("theme", "state_change_alerts", "minimize_to_tray",
                         "close_to_tray", "start_hidden_on_windows_startup"))
NOTIFICATIONS = frozenset(("windows_notifications_enabled", "generic_webhook_enabled",
    "teams_webhook_enabled", "notification_timeout_seconds", "notification_retry_count",
    "notification_retry_later_enabled"))


class BackupError(ValueError):
    """Messages are fixed summaries: never echo untrusted contents or endpoints."""


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise BackupError("Invalid or oversized text field.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise BackupError("Invalid Unicode text.") from None
    if any(ord(c) < 32 for c in value):
        raise BackupError("Control characters are not allowed.")
    return value.strip()


def _target(value):
    if not isinstance(value, dict):
        raise BackupError("Invalid target object.")
    host = _text(value.get("host"), 253)
    port = value.get("port")
    if not host or type(port) is not int or not 1 <= port <= 65535:
        raise BackupError("Invalid target host or port.")
    name = _text(value.get("name", ""), 200)
    groups = value.get("groups", [])
    if isinstance(groups, str):
        groups = _text(groups, 330).split(",")
    if not isinstance(groups, list) or len(groups) > 10:
        raise BackupError("Invalid group list.")
    groups = [_text(group, 32) for group in groups]
    try:
        groups = normalize_groups(groups, strict=True)
    except ValueError:
        raise BackupError("Invalid target groups.") from None
    # Maintenance is time-sensitive. Never import an active window or its reason.
    return normalize_target_record(dict(host=host, port=port, name=name, groups=groups))


def _settings(value):
    if not isinstance(value, dict):
        raise BackupError("Settings must be an object.")
    result = {}
    for key in PREFERENCES | NOTIFICATIONS:
        if key not in value:
            continue
        item = value[key]
        if key == "theme":
            valid = isinstance(item, str) and item in ("dark", "light")
        elif key in ("notification_timeout_seconds", "notification_retry_count"):
            low, high = (1, 30) if key.endswith("seconds") else (0, 5)
            valid = type(item) is int and low <= item <= high
        else:
            valid = type(item) is bool
        if not valid:
            raise BackupError("Invalid application or notification preference.")
        result[key] = item
    return result


@dataclass
class ParsedBackup:
    payload: dict
    warnings: list[str]
    invalid: int = 0
    duplicates: int = 0


def validate_backup(payload):
    if not isinstance(payload, dict) or payload.get("format") != "MultiPortCheckerBackup":
        raise BackupError("Not a MultiPortChecker settings backup.")
    if type(payload.get("backup_version")) is not int or payload["backup_version"] != BACKUP_FORMAT_VERSION:
        raise BackupError("Unsupported backup format version.")
    version = _text(payload.get("app_version", "Unknown"), 64)
    created = _text(payload.get("created_at", "Unknown"), 64)
    settings = _settings(payload.get("settings", {}))
    targets = payload.get("targets", [])
    if not isinstance(targets, list) or len(targets) > MAX_BACKUP_TARGETS:
        raise BackupError("Invalid target list or more than 10,000 targets.")
    warnings, clean, seen = [], [], set()
    invalid = duplicates = 0
    unknown = bool(set(payload) - {"format", "backup_version", "app_version", "created_at", "settings", "targets", "secrets_included"})
    unknown |= bool(set(payload.get("settings", {})) - PREFERENCES - NOTIFICATIONS)
    for entry in targets:
        try:
            target = _target(entry)
        except BackupError:
            invalid += 1
            continue
        unknown |= bool(set(entry) - {"host", "port", "name", "groups", "maintenance"})
        key = normalize_target_key(target["host"], target["port"])
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        clean.append(target)
    if unknown:
        warnings.append("Some settings from a newer version were ignored.")
    if invalid:
        warnings.append(f"{invalid} invalid target(s) skipped.")
    if duplicates:
        warnings.append(f"{duplicates} duplicate target(s) skipped; first occurrence wins.")
    return ParsedBackup(dict(format="MultiPortCheckerBackup", backup_version=1,
        app_version=version, created_at=created, secrets_included=False,
        settings=settings, targets=clean), warnings, invalid, duplicates)


def build_backup(config, *, now=None):
    # Treeview and legacy host lists can represent ports as decimal strings.
    # Canonical backup records use integers without loosening untrusted imports.
    records = []
    for record in config.get("hosts", []):
        item = dict(record)
        if isinstance(item.get("port"), str) and item["port"].isascii() and item["port"].isdigit():
            item["port"] = int(item["port"])
        records.append(item)
    payload = dict(format="MultiPortCheckerBackup", backup_version=BACKUP_FORMAT_VERSION,
        app_version=APP_VERSION, created_at=(now or datetime.now(timezone.utc)).isoformat(),
        secrets_included=False, settings=_settings(config), targets=records)
    parsed = validate_backup(payload)
    if parsed.invalid or parsed.duplicates:
        raise BackupError("Current targets must be valid and unique before backup.")
    if len(json.dumps(parsed.payload, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_BACKUP_BYTES:
        raise BackupError("Backup exceeds the 5 MiB limit.")
    return parsed.payload


def read_backup(path):
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_BACKUP_BYTES + 1)
        if len(raw) > MAX_BACKUP_BYTES:
            raise BackupError("Backup exceeds the 5 MiB limit.")
        payload = json.loads(raw.decode("utf-8-sig"))
    except BackupError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise BackupError("Backup is not valid UTF-8 JSON.") from None
    return validate_backup(payload)


def atomic_write_json(path, payload):
    """Same-directory temporary file keeps os.replace on the same filesystem.

Failure before replacement leaves the previous config intact, including on Windows.
"""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".mpc-", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class RestorePlan:
    config: dict
    counts: dict
    warnings: list[str]
    replace_confirmation_required: bool


def plan_restore(current, backup, *, targets=True, preferences=True,
                 notifications=True, mode="merge"):
    if mode not in ("merge", "replace"):
        raise BackupError("Invalid restore mode.")
    parsed = validate_backup(backup.payload if isinstance(backup, ParsedBackup) else backup)
    result = copy.deepcopy(current)
    counts = dict(new=0, matching=0, names=0, groups=0)
    warnings = list(backup.warnings if isinstance(backup, ParsedBackup) else parsed.warnings)
    if targets:
        # Host + Port is identity; labels and groups must never split history.
        local = {normalize_target_key(t["host"], int(t["port"])): t for t in current.get("hosts", [])}
        merged = copy.deepcopy(local) if mode == "merge" else {}
        for incoming in parsed.payload["targets"]:
            item = copy.deepcopy(incoming)
            key = normalize_target_key(item["host"], item["port"])
            old = local.get(key)
            if old is not None:
                counts["matching"] += 1
                counts["names"] += old.get("name", "") != item["name"]
                counts["groups"] += old.get("groups", []) != item["groups"]
                if mode == "merge":
                    item["maintenance"] = copy.deepcopy(old.get("maintenance", item["maintenance"]))
            else:
                counts["new"] += 1
            merged[key] = item
        result["hosts"] = list(merged.values())
    selected = (PREFERENCES if preferences else frozenset()) | (NOTIFICATIONS if notifications else frozenset())
    result.update({k: v for k, v in parsed.payload["settings"].items() if k in selected})
    if notifications:
        # Absent portable secrets never erase local endpoints. Enable only with
        # a valid destination endpoint; importing never touches registry state.
        for provider in ("generic_webhook", "teams_webhook"):
            if result.get(provider + "_enabled") and not endpoint_is_valid(result.get(provider + "_url", "")):
                result[provider + "_enabled"] = False
                warnings.append(f"{provider} disabled: no valid local endpoint.")
    return RestorePlan(result, counts, warnings, targets and mode == "replace")


def save_restore(config_path, current, plan, *, replace_confirmed=False):
    """Plan/validate -> safety backup -> atomic write -> caller applies on Tk.

No live state is touched before persistence succeeds. Runtime backups use the
config directory, never PyInstaller's read-only _MEIPASS extraction directory.
"""
    if plan.replace_confirmation_required and not replace_confirmed:
        raise BackupError("Replace requires explicit confirmation.")
    build_backup(plan.config)
    safety = build_backup(current)
    directory = Path(config_path).parent / "backups"
    directory.mkdir(exist_ok=True)
    path = directory / (datetime.now().strftime("Before-Import-%Y%m%d-%H%M%S-%f") + ".mpcbackup.json")
    atomic_write_json(path, safety)  # Failure here aborts before touching config.
    atomic_write_json(config_path, plan.config)
    return path
