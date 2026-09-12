import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from application_health import (
    ERROR, HEALTHY, UNKNOWN, WARNING, ComponentHealth, HealthSnapshot,
    aggregate_status, application_component, build_snapshot,
    export_diagnostics_json, maintenance_component, monitoring_component,
    notification_component, simple_component, store_component,
)
from event_history import EventHistoryStore
from maintenance import MaintenanceState
from notification_history import NotificationHistoryStore


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class _Store:
    def __init__(self, summary=None, failure=False):
        self.summary = summary or {"accessible": True, "row_count": 2}
        self.failure = failure
    def health_summary(self):
        if self.failure:
            raise RuntimeError
        return self.summary


class _Manager:
    def __init__(self, **values):
        self.values = {"worker_alive": True, "scheduler_alive": True,
                       "queue_size": 0, "shutdown_started": False, **values}
    def health_summary(self):
        return self.values


class ApplicationHealthTests(unittest.TestCase):
    def test_01_all_healthy(self):
        self.assertEqual(aggregate_status([ComponentHealth("A", HEALTHY, "ok")]), HEALTHY)

    def test_02_warning_aggregation(self):
        self.assertEqual(aggregate_status([ComponentHealth("A", HEALTHY, "ok"), ComponentHealth("B", WARNING, "warn")]), WARNING)

    def test_03_error_aggregation(self):
        self.assertEqual(aggregate_status([ComponentHealth("A", WARNING, "warn"), ComponentHealth("B", ERROR, "bad")]), ERROR)

    def test_04_unknown_only(self):
        self.assertEqual(aggregate_status([ComponentHealth("A", UNKNOWN, "unknown")]), UNKNOWN)

    def test_05_unknown_does_not_override_healthy(self):
        self.assertEqual(aggregate_status([ComponentHealth("A", HEALTHY, "ok"), ComponentHealth("B", UNKNOWN, "unknown")]), HEALTHY)

    def test_06_invalid_component_status_becomes_unknown(self):
        self.assertEqual(ComponentHealth("A", "BROKEN", "x").status, UNKNOWN)

    def test_07_app_uptime(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW - timedelta(seconds=90), components=[], now=NOW)
        self.assertEqual(snapshot.uptime_seconds, 90)

    def test_08_deterministic_injected_clock(self):
        self.assertEqual(build_snapshot(version="1", process_started_at=NOW, components=[], now=NOW).generated_at, NOW)

    def test_health_incident_aggregate_export_fields(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW, components=[], now=NOW,
                                  health_summary={"open_count": 2, "open_warning_count": 1,
                                                  "open_error_count": 1, "last_incident_at": "2026-09-12T12:00:00+00:00",
                                                  "watchdog_enabled": True, "auto_recovery_enabled": True})
        exported = snapshot.to_dict()["health"]
        self.assertEqual(exported["open_health_incidents"], 2)
        self.assertNotIn("targets", exported)

    def test_09_source_application_component(self):
        item = application_component(version="1", frozen=False)
        self.assertEqual(item.details["running_mode"], "source")
        self.assertIn("python_version", item.details)

    def test_10_frozen_application_component(self):
        item = application_component(version="1", frozen=True)
        self.assertEqual(item.details["running_mode"], "frozen")
        self.assertNotIn("python_version", item.details)

    def test_11_recent_auto_cycle_healthy(self):
        item = monitoring_component(now=NOW, auto_refresh=True, refresh_interval_seconds=5, last_successful_at=NOW-timedelta(seconds=10), last_duration_ms=4, persistent_count=1, visible_count=1, scan_active=False)
        self.assertEqual(item.status, HEALTHY)

    def test_12_stale_auto_cycle_warning(self):
        item = monitoring_component(now=NOW, auto_refresh=True, refresh_interval_seconds=5, last_successful_at=NOW-timedelta(seconds=61), last_duration_ms=4, persistent_count=1, visible_count=1, scan_active=False)
        self.assertEqual(item.status, WARNING)

    def test_13_long_interval_stale_threshold(self):
        item = monitoring_component(now=NOW, auto_refresh=True, refresh_interval_seconds=30, last_successful_at=NOW-timedelta(seconds=91), last_duration_ms=None, persistent_count=0, visible_count=0, scan_active=False)
        self.assertEqual(item.status, WARNING)

    def test_14_disabled_auto_refresh_is_idle_healthy(self):
        item = monitoring_component(now=NOW, auto_refresh=False, refresh_interval_seconds=5, last_successful_at=None, last_duration_ms=None, persistent_count=0, visible_count=0, scan_active=False)
        self.assertEqual(item.status, HEALTHY)

    def test_15_offline_target_count_is_not_an_input(self):
        item = monitoring_component(now=NOW, auto_refresh=False, refresh_interval_seconds=5, last_successful_at=None, last_duration_ms=None, persistent_count=5, visible_count=5, scan_active=False)
        self.assertEqual(item.status, HEALTHY)

    def test_16_event_store_healthy(self):
        self.assertEqual(store_component("Event History", _Store(), now=NOW).status, HEALTHY)

    def test_17_event_store_failure(self):
        self.assertEqual(store_component("Event History", _Store(failure=True), now=NOW).status, ERROR)

    def test_18_event_store_none_unknown(self):
        self.assertEqual(store_component("Event History", None, now=NOW).status, UNKNOWN)

    def test_19_delivery_counts_healthy(self):
        summary = {"accessible": True, "counts": {"FAILED": 0, "RETRYING": 0}}
        self.assertEqual(store_component("Delivery Retry", _Store(summary), delivery=True).status, HEALTHY)

    def test_20_failed_delivery_warning(self):
        summary = {"accessible": True, "counts": {"FAILED": 2, "RETRYING": 0}}
        self.assertEqual(store_component("Delivery Retry", _Store(summary), delivery=True).status, WARNING)

    def test_21_retrying_delivery_warning(self):
        summary = {"accessible": True, "counts": {"FAILED": 0, "RETRYING": 1}}
        self.assertEqual(store_component("Delivery Retry", _Store(summary), delivery=True).status, WARNING)

    def test_22_worker_alive(self):
        self.assertEqual(notification_component(_Manager()).status, HEALTHY)

    def test_23_worker_dead_unexpectedly(self):
        self.assertEqual(notification_component(_Manager(worker_alive=False)).status, ERROR)

    def test_24_disabled_providers_not_error(self):
        self.assertEqual(notification_component(_Manager(), providers_enabled=False).status, HEALTHY)

    def test_25_queue_depth(self):
        self.assertIn("3", notification_component(_Manager(queue_size=3)).summary)

    def test_26_active_maintenance_not_warning(self):
        state = MaintenanceState(True, NOW-timedelta(hours=1), None, "planned")
        self.assertEqual(maintenance_component([state], scheduler_active=True, now=NOW).status, HEALTHY)

    def test_27_overdue_maintenance_warning(self):
        state = MaintenanceState(True, NOW-timedelta(hours=1), NOW-timedelta(seconds=10), "planned")
        self.assertEqual(maintenance_component([state], scheduler_active=True, now=NOW).status, WARNING)

    def test_28_inactive_scheduler_warning(self):
        self.assertEqual(maintenance_component([], scheduler_active=False, now=NOW).status, WARNING)

    def test_29_tray_healthy(self):
        self.assertEqual(simple_component("System Tray", available=True, summary="Running").status, HEALTHY)

    def test_30_tray_unavailable_is_warning(self):
        self.assertEqual(simple_component("System Tray", available=False, summary="Unavailable").status, WARNING)

    def test_31_startup_source_unknown(self):
        self.assertEqual(simple_component("Windows Startup", available=None, summary="Unsupported").status, UNKNOWN)

    def test_32_snapshot_json_serialization(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW, components=[ComponentHealth("A", HEALTHY, "ok", {"time": NOW})], now=NOW)
        json.dumps(snapshot.to_dict())

    def test_33_export_has_version_and_timestamp(self):
        snapshot = build_snapshot(version="1.11", process_started_at=NOW, components=[], now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "diag.json")
            export_diagnostics_json(path, snapshot)
            with open(path, encoding="utf-8") as source:
                data = json.load(source)
        self.assertEqual(data["version"], "1.11")
        self.assertEqual(data["generated_at"], NOW.isoformat())

    def test_34_secret_keys_are_removed(self):
        details = {"webhook_url": "https://example.invalid/secret", "token": "abc", "Authorization": "Bearer abc", "password": "pw", "credentials": "x", "count": 2}
        item = ComponentHealth("A", HEALTHY, "ok", details)
        exported = json.dumps(item.to_dict())
        for secret in ("example.invalid", "Bearer", '"abc"', '"pw"'):
            self.assertNotIn(secret, exported)
        self.assertEqual(item.details["count"], 2)

    def test_35_target_inventory_is_removed(self):
        item = ComponentHealth("A", HEALTHY, "ok", {"target_count": 2, "target_hosts": ["192.0.2.1"], "device_inventory": ["Demo-PLC"]})
        self.assertIn("target_count", item.details)
        self.assertNotIn("target_hosts", item.details)
        self.assertNotIn("device_inventory", item.details)

    def test_36_unicode_safe_export(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW, components=[ComponentHealth("Config", HEALTHY, "พร้อม")], now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "diag.json")
            export_diagnostics_json(path, snapshot)
            with open(path, encoding="utf-8") as source:
                self.assertIn("พร้อม", source.read())

    def test_37_real_event_db_health(self):
        with tempfile.TemporaryDirectory() as folder:
            item = store_component("Event History", EventHistoryStore(os.path.join(folder, "events.db")))
        self.assertEqual(item.status, HEALTHY)

    def test_38_real_notification_db_health(self):
        with tempfile.TemporaryDirectory() as folder:
            item = store_component("Delivery Retry", NotificationHistoryStore(os.path.join(folder, "events.db")), delivery=True)
        self.assertEqual(item.status, HEALTHY)

    def test_39_summary_text_contains_components(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW, components=[ComponentHealth("Monitoring", HEALTHY, "Idle")], now=NOW)
        self.assertIn("Monitoring: HEALTHY", snapshot.summary_text())

    def test_40_snapshot_overall_aggregation(self):
        snapshot = build_snapshot(version="1", process_started_at=NOW, components=[ComponentHealth("A", WARNING, "warn")], now=NOW)
        self.assertEqual(snapshot.overall_status, WARNING)

    def test_41_local_health_queries_complete_under_target(self):
        with tempfile.TemporaryDirectory() as folder:
            event_store = EventHistoryStore(os.path.join(folder, "events.db"))
            delivery_store = NotificationHistoryStore(os.path.join(folder, "events.db"))
            started = time.perf_counter()
            store_component("Event History", event_store)
            store_component("Delivery Retry", delivery_store, delivery=True)
            elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
