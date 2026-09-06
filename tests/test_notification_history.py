import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone

from notification_history import (
    STATUS_DELIVERED, STATUS_FAILED, STATUS_QUEUED, STATUS_RETRYING,
    NotificationHistoryStore,
)
from notification_models import NotificationEvent
from event_history import EventHistoryStore, EventRecord


NOW = datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc)


def event(kind="DOWN", name="Demo-PLC", host="192.0.2.10", seconds=0):
    return NotificationEvent(
        kind, (NOW + timedelta(seconds=seconds)).isoformat(), name, host, 443,
        "Timeout", "ONLINE" if kind == "DOWN" else "OFFLINE",
        "OFFLINE" if kind == "DOWN" else "ONLINE",
        30 if kind == "RECOVERED" else None,
    )


class NotificationHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "events.db")
        self.store = NotificationHistoryStore(self.path, retention=3)

    def insert(self, provider="generic_webhook", item=None):
        return self.store.insert_delivery(item or event(), provider, now=NOW)

    def test_delivery_table_initializes(self):
        with closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        self.assertIn("notification_deliveries", tables)

    def test_table_is_separate_from_event_history(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0], 0)

    def test_insert_creates_queued_row(self):
        row = self.store.get(self.insert())
        self.assertEqual((row.status, row.attempt_count), (STATUS_QUEUED, 0))

    def test_test_notification_is_not_inserted(self):
        self.assertIsNone(self.store.insert_delivery(NotificationEvent.test_notification(), "windows"))

    def test_attempt_increments_and_sets_time(self):
        delivery_id = self.insert()
        self.store.record_attempt(delivery_id, now=NOW)
        row = self.store.get(delivery_id)
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.last_attempt_at)

    def test_success_clears_error_and_retry(self):
        delivery_id = self.insert()
        self.store.schedule_retry(delivery_id, NOW, "HTTP_500", "HTTP 500")
        self.store.mark_delivered(delivery_id, now=NOW)
        row = self.store.get(delivery_id)
        self.assertEqual(row.status, STATUS_DELIVERED)
        self.assertIsNone(row.next_retry_at)
        self.assertIsNone(row.last_error_summary)

    def test_failure_is_terminal(self):
        delivery_id = self.insert()
        self.store.mark_failed(delivery_id, "HTTP_4XX", "HTTP 401")
        row = self.store.get(delivery_id)
        self.assertEqual((row.status, row.last_error_category), (STATUS_FAILED, "HTTP_4XX"))

    def test_schedule_retry_sets_next_time(self):
        delivery_id = self.insert()
        self.store.schedule_retry(delivery_id, NOW + timedelta(minutes=5), "HTTP_5XX", "HTTP 500")
        self.assertEqual(self.store.get(delivery_id).status, STATUS_RETRYING)

    def test_delayed_cycle_increments(self):
        delivery_id = self.insert()
        self.store.schedule_retry(delivery_id, NOW, "NETWORK", "Network connection failed")
        self.store.begin_delayed_retry(delivery_id)
        self.assertEqual(self.store.get(delivery_id).delayed_retry_count, 1)

    def test_future_retry_is_not_due(self):
        delivery_id = self.insert()
        self.store.schedule_retry(delivery_id, NOW + timedelta(seconds=1), "NETWORK", "Network connection failed")
        self.assertEqual(self.store.due_retries(NOW), [])

    def test_due_retry_is_loaded(self):
        delivery_id = self.insert()
        self.store.schedule_retry(delivery_id, NOW, "NETWORK", "Network connection failed")
        self.assertEqual([row.id for row in self.store.due_retries(NOW)], [delivery_id])

    def test_delivered_is_not_due(self):
        delivery_id = self.insert()
        self.store.mark_delivered(delivery_id, now=NOW)
        self.assertEqual(self.store.due_retries(NOW), [])

    def test_failed_is_not_due(self):
        delivery_id = self.insert()
        self.store.mark_failed(delivery_id, "HTTP_4XX", "HTTP 400")
        self.assertEqual(self.store.due_retries(NOW), [])

    def test_due_order_is_oldest_event_first(self):
        newer = self.insert(item=event(seconds=2))
        older = self.insert(item=event(seconds=1))
        for delivery_id in (newer, older):
            self.store.schedule_retry(delivery_id, NOW, "HTTP_5XX", "HTTP 500")
        self.assertEqual([row.id for row in self.store.due_retries(NOW)], [older, newer])

    def test_history_is_newest_first(self):
        first, second = self.insert(), self.insert()
        self.assertEqual([row.id for row in self.store.list_deliveries()], [second, first])

    def test_provider_filter(self):
        self.insert("windows")
        generic = self.insert("generic_webhook")
        self.assertEqual([row.id for row in self.store.list_deliveries(provider="generic_webhook")], [generic])

    def test_status_filter(self):
        delivered, failed = self.insert(), self.insert()
        self.store.mark_delivered(delivered, now=NOW)
        self.store.mark_failed(failed, "UNKNOWN", "Delivery failed")
        self.assertEqual([row.id for row in self.store.list_deliveries(status="FAILED")], [failed])

    def test_device_search_supports_unicode(self):
        delivery_id = self.insert(item=event(name="เครื่องทดสอบ"))
        self.assertEqual(self.store.list_deliveries(search="เครื่อง")[0].id, delivery_id)

    def test_host_search(self):
        delivery_id = self.insert(item=event(host="198.51.100.20"))
        self.assertEqual(self.store.list_deliveries(search="198.51")[0].id, delivery_id)

    def test_terminal_retention_is_bounded(self):
        for _ in range(5):
            delivery_id = self.insert()
            self.store.mark_delivered(delivery_id, now=NOW)
        self.assertEqual(len(self.store.list_deliveries()), 3)

    def test_active_rows_are_never_pruned(self):
        queued = self.insert()
        retrying = self.insert()
        self.store.schedule_retry(retrying, NOW, "NETWORK", "Network connection failed")
        for _ in range(5):
            terminal = self.insert()
            self.store.mark_failed(terminal, "UNKNOWN", "Delivery failed")
        ids = {row.id for row in self.store.list_deliveries()}
        self.assertTrue({queued, retrying}.issubset(ids))

    def test_clear_removes_only_terminal_rows(self):
        queued, retrying, delivered, failed = [self.insert() for _ in range(4)]
        self.store.schedule_retry(retrying, NOW, "NETWORK", "Network connection failed")
        self.store.mark_delivered(delivered, now=NOW)
        self.store.mark_failed(failed, "UNKNOWN", "Delivery failed")
        self.store.clear_terminal()
        self.assertEqual({row.id for row in self.store.list_deliveries()}, {queued, retrying})

    def test_clear_delivery_history_does_not_clear_event_history(self):
        event_store = EventHistoryStore(self.path)
        event_store.insert(EventRecord(
            NOW.isoformat(), "DOWN", "Demo-PLC", "192.0.2.10", 443,
            "Timeout", "ONLINE", "OFFLINE",
        ))
        delivery_id = self.insert()
        self.store.mark_failed(delivery_id, "HTTP_4XX", "HTTP 401")
        self.store.clear_terminal()
        self.assertEqual(len(event_store.list_events()), 1)

    def test_database_never_contains_endpoint(self):
        delivery_id = self.insert()
        self.store.mark_failed(delivery_id, "HTTP_4XX", "HTTP 401")
        with open(self.path, "rb") as database_file:
            self.assertNotIn(b"secret-token", database_file.read())

    def test_record_reconstructs_original_event(self):
        original = event("RECOVERED")
        rebuilt = self.store.get(self.store.insert_delivery(original, "teams_webhook", now=NOW)).to_event()
        self.assertEqual((rebuilt.event_type, rebuilt.timestamp, rebuilt.downtime_display),
                         ("RECOVERED", original.timestamp, "30s"))

    def test_startup_recovery_makes_webhook_due_when_enabled(self):
        delivery_id = self.insert()
        self.store.recover_interrupted(True, now=NOW)
        self.assertEqual(self.store.get(delivery_id).status, STATUS_RETRYING)

    def test_startup_recovery_fails_queued_when_disabled(self):
        delivery_id = self.insert()
        self.store.recover_interrupted(False, now=NOW)
        self.assertEqual(self.store.get(delivery_id).status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
