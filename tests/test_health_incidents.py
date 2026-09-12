import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from health_incidents import HealthIncidentStore


class HealthIncidentStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.store = HealthIncidentStore(self.directory.name + "/events.db", retention=3)
        self.now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)

    def test_create_warning_and_error(self):
        self.assertEqual(self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", now=self.now).status, "OPEN")
        self.assertEqual(self.store.record(component="Notification", severity="ERROR", event_type="STOPPED", summary="Worker stopped", now=self.now).severity, "ERROR")

    def test_fingerprint_dedupes_and_updates(self):
        first = self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", fingerprint="m:stale", now=self.now)
        second = self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", fingerprint="m:stale", now=self.now + timedelta(seconds=2))
        self.assertEqual(first.id, second.id); self.assertEqual(second.occurrence_count, 2); self.assertNotEqual(first.last_seen_at, second.last_seen_at)

    def test_resolve_then_recur_new_row(self):
        first = self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", fingerprint="m:stale", now=self.now)
        resolved = self.store.resolve("m:stale", recovery_action="recheck", recovery_result="Recovered", now=self.now + timedelta(minutes=1))
        self.assertEqual(resolved.status, "RESOLVED")
        second = self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", fingerprint="m:stale", now=self.now + timedelta(minutes=2))
        self.assertNotEqual(first.id, second.id)

    def test_filters_search_and_clear_only_resolved(self):
        self.store.record(component="Monitoring", severity="WARNING", event_type="STALE", summary="Cycle stale", fingerprint="m", now=self.now)
        self.store.record(component="Tray", severity="ERROR", event_type="STOPPED", summary="Tray stopped", fingerprint="t", now=self.now)
        self.store.resolve("t", now=self.now)
        self.assertEqual(len(self.store.list(component="Monitoring")), 1)
        self.assertEqual(len(self.store.list(status="OPEN")), 1)
        self.assertEqual(len(self.store.list(search="Tray")), 1)
        self.assertEqual(self.store.clear_resolved(), 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_open_rows_never_pruned_and_retention_resolved(self):
        self.store.record(component="Open", severity="WARNING", event_type="A", summary="Open", fingerprint="open", now=self.now)
        for index in range(5):
            fp = f"resolved-{index}"; self.store.record(component="Old", severity="INFO", event_type="A", summary=str(index), fingerprint=fp, now=self.now); self.store.resolve(fp, now=self.now)
        self.store.prune()
        rows = self.store.list(); self.assertTrue(any(row.fingerprint == "open" for row in rows)); self.assertLessEqual(len([r for r in rows if r.status == "RESOLVED"]), 3)

    def test_safe_text_excludes_secrets(self):
        row = self.store.record(component="Demo", severity="WARNING", event_type="SAFE", summary="https://secret.invalid/token", details="Authorization: hidden", now=self.now)
        self.assertNotIn("https://", row.summary); self.assertNotIn("Authorization", row.details)

    def test_unicode_and_summary(self):
        row = self.store.record(component="อุปกรณ์", severity="INFO", event_type="NOTICE", summary="สถานะปกติ", now=self.now)
        self.assertEqual(self.store.list()[0].summary, "สถานะปกติ"); self.assertEqual(self.store.summary()["open_count"], 1)

    def test_schema_migrates_existing_events_db(self):
        from event_history import EventHistoryStore
        EventHistoryStore(self.directory.name + "/events.db")
        migrated = HealthIncidentStore(self.directory.name + "/events.db")
        self.assertTrue(migrated.available)

    def test_latest_summary(self):
        self.store.record(component="Demo", severity="ERROR", event_type="FAIL", summary="Failure", now=self.now)
        summary = self.store.summary(); self.assertEqual(summary["open_error_count"], 1); self.assertIsNotNone(summary["last_incident_at"])
