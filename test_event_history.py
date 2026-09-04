import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from event_history import EventHistoryStore, EventRecord, export_events_csv
from monitoring_state import EVENT_DOWN, EVENT_RECOVERED, TcpStateTracker


class EventHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "events.db"
        self.store = EventHistoryStore(str(self.db_path), retention=3)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def event(number, event_type="DOWN", device_name="Demo-PLC"):
        return EventRecord(
            timestamp=f"2026-09-04T10:15:{number:02d}+07:00",
            event_type=event_type,
            device_name=device_name,
            host=f"192.0.2.{number}",
            port=102,
            ping="Timeout" if event_type == "DOWN" else "2 ms",
            previous_status="ONLINE" if event_type == "DOWN" else "OFFLINE",
            new_status="OFFLINE" if event_type == "DOWN" else "ONLINE",
            downtime_seconds=None if event_type == "DOWN" else 155,
        )

    def test_database_and_table_initialize_automatically(self):
        self.assertTrue(self.store.available)
        self.assertTrue(self.db_path.is_file())

    def test_unavailable_database_fails_safely(self):
        unavailable = EventHistoryStore(
            str(Path(self.temp_dir.name) / "missing" / "events.db")
        )
        self.assertFalse(unavailable.available)
        self.assertFalse(unavailable.insert(self.event(1)))
        self.assertEqual(unavailable.list_events(), [])

    def test_insert_and_newest_first_retrieval(self):
        self.assertTrue(self.store.insert(self.event(1)))
        self.assertTrue(self.store.insert(self.event(2, "RECOVERED")))
        events = self.store.list_events()
        self.assertEqual([event.timestamp for event in events], [
            "2026-09-04T10:15:02+07:00",
            "2026-09-04T10:15:01+07:00",
        ])
        self.assertEqual(events[0].downtime_seconds, 155)

    def test_filters_by_device_host_and_event_type(self):
        self.store.insert(self.event(1, "DOWN", "Demo-PLC"))
        self.store.insert(self.event(2, "RECOVERED", "Test-Server"))
        self.assertEqual(len(self.store.list_events(search="server")), 1)
        self.assertEqual(len(self.store.list_events(search="192.0.2.1")), 1)
        self.assertEqual(len(self.store.list_events(event_type="DOWN")), 1)

    def test_clear_history(self):
        self.store.insert(self.event(1))
        self.assertTrue(self.store.clear())
        self.assertEqual(self.store.list_events(), [])

    def test_retention_keeps_only_newest_rows(self):
        for number in range(1, 6):
            self.store.insert(self.event(number))
        self.assertEqual(
            [event.timestamp for event in self.store.list_events()],
            [
                "2026-09-04T10:15:05+07:00",
                "2026-09-04T10:15:04+07:00",
                "2026-09-04T10:15:03+07:00",
            ],
        )


class StateChangePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EventHistoryStore(
            str(Path(self.temp_dir.name) / "events.db")
        )
        self.tracker = TcpStateTracker()
        self.start = datetime(2026, 9, 4, 10, 15, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def persist(self, transition, ping):
        if transition is None:
            return
        self.store.insert(
            EventRecord.from_state_change(
                transition,
                device_name="Demo-PLC",
                host="192.0.2.10",
                port=102,
                ping=ping,
            )
        )

    def test_only_meaningful_persistent_transitions_create_events(self):
        self.persist(self.tracker.observe("target", True, now=self.start), "1 ms")
        self.assertEqual(self.store.list_events(), [])

        down = self.tracker.observe(
            "target", False, now=self.start + timedelta(seconds=5)
        )
        self.persist(down, "Timeout")
        self.persist(
            self.tracker.observe(
                "target", False, now=self.start + timedelta(seconds=10)
            ),
            "Timeout",
        )
        recovery = self.tracker.observe(
            "target", True, now=self.start + timedelta(seconds=160)
        )
        self.persist(recovery, "2 ms")

        events = self.store.list_events()
        self.assertEqual([event.event_type for event in events], [
            EVENT_RECOVERED,
            EVENT_DOWN,
        ])
        self.assertEqual(events[0].downtime_seconds, 155)

    def test_unknown_offline_and_transient_results_create_no_events(self):
        self.persist(self.tracker.observe("offline", False, now=self.start), "Timeout")
        self.persist(
            self.tracker.observe(
                "scan", False, persistent=False, now=self.start
            ),
            "Timeout",
        )
        self.assertEqual(self.store.list_events(), [])

    def test_ping_timeout_does_not_create_event_while_tcp_stays_online(self):
        self.tracker.observe("target", True, now=self.start)
        transition = self.tracker.observe(
            "target", True, now=self.start + timedelta(seconds=5)
        )
        self.persist(transition, "Timeout")
        self.assertEqual(self.store.list_events(), [])


class CsvExportTests(unittest.TestCase):
    def test_csv_has_bom_columns_duration_and_unicode_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.csv"
            event = EventHistoryStoreTests.event(
                1, "RECOVERED", "เซิร์ฟเวอร์ทดสอบ"
            )
            self.assertEqual(export_events_csv(str(path), [event]), 1)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(rows[0]["device_name"], "เซิร์ฟเวอร์ทดสอบ")
            self.assertEqual(rows[0]["downtime_seconds"], "155")
            self.assertEqual(rows[0]["downtime_display"], "2m 35s")


if __name__ == "__main__":
    unittest.main()
