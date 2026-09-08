import csv
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from availability_report import ConfiguredTarget, calculate_availability, export_outages_csv, export_summary_csv
from event_history import EventHistoryStore, EventRecord, export_events_csv
from maintenance import (
    MaintenanceState, expire_maintenance, filter_operational_alerts,
    is_maintenance_active, maintenance_has_expired, normalize_maintenance,
    start_maintenance,
)
from monitoring_state import EVENT_MAINTENANCE_ENDED, EVENT_MAINTENANCE_STARTED, make_target_record, normalize_target_record
from notification_history import NotificationHistoryStore
from notification_models import NotificationEvent


ZONE = timezone(timedelta(hours=7))
START = datetime(2026, 9, 8, 0, 0, tzinfo=ZONE)
END = START + timedelta(hours=4)
TARGET = ConfiguredTarget("Demo-PLC", "192.0.2.10", 102, ("PLC", "Critical"))


def tcp(when, kind):
    return EventRecord(when.isoformat(), kind, TARGET.device_name, TARGET.host, TARGET.port, "N/A", "ONLINE" if kind == "DOWN" else "OFFLINE", "OFFLINE" if kind == "DOWN" else "ONLINE")


def maint(when, kind, *, until=None, reason="Planned maintenance", end_reason=""):
    return EventRecord.maintenance_event(kind, occurred_at=when, device_name=TARGET.device_name, host=TARGET.host, port=TARGET.port, reason=reason, until=until, end_reason=end_reason)


def report(events, start=START, end=END):
    return calculate_availability(events, start, end, [TARGET])


class MaintenanceModeTests(unittest.TestCase):
    def test_01_old_config_defaults_maintenance_off(self):
        self.assertFalse(normalize_target_record({"host": TARGET.host, "port": 102})["maintenance"]["enabled"])

    def test_02_start_manual_maintenance(self):
        state = start_maintenance("Until manually ended", now=START)
        self.assertTrue(state.enabled); self.assertIsNone(state.until)

    def test_03_start_timed_maintenance(self):
        self.assertEqual(start_maintenance("30 minutes", now=START).until, START + timedelta(minutes=30))

    def test_04_invalid_past_end_rejected(self):
        with self.assertRaisesRegex(ValueError, "future"):
            start_maintenance("Custom End Time", custom_end=(START - timedelta(minutes=1)).isoformat(), now=START)

    def test_05_manual_end_state(self):
        state, expired, _ = expire_maintenance(MaintenanceState(), START)
        self.assertFalse(state.enabled); self.assertFalse(expired)

    def test_06_automatic_expiry(self):
        state = start_maintenance("30 minutes", now=START)
        ended, expired, when = expire_maintenance(state, START + timedelta(minutes=30))
        self.assertFalse(ended.enabled); self.assertTrue(expired); self.assertEqual(when, state.until)

    def test_07_restart_active_manual(self):
        saved = start_maintenance("Until manually ended", now=START).to_config()
        self.assertTrue(is_maintenance_active(normalize_maintenance(saved), END))

    def test_08_restart_future_expiry(self):
        saved = start_maintenance("4 hours", now=START).to_config()
        self.assertTrue(is_maintenance_active(normalize_maintenance(saved), START + timedelta(hours=1)))

    def test_09_restart_after_expired(self):
        saved = normalize_maintenance(start_maintenance("30 minutes", now=START).to_config())
        self.assertTrue(maintenance_has_expired(saved, START + timedelta(hours=1)))

    def test_10_no_duplicate_end_after_repeated_expiry(self):
        ended, expired, _ = expire_maintenance(start_maintenance("30 minutes", now=START), END)
        ended_again, duplicate, _ = expire_maintenance(ended, END)
        self.assertTrue(expired); self.assertFalse(duplicate); self.assertEqual(ended, ended_again)

    def test_11_down_during_maintenance_is_event_evidence(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN")]).rows[0]
        self.assertEqual(row.downtime_seconds, 3 * 3600)

    def test_12_recovered_during_maintenance_is_event_evidence(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]).rows[0]
        self.assertEqual(row.downtime_seconds, 3600)

    def test_13_tk_alert_suppressed(self):
        self.assertEqual(filter_operational_alerts([{"maintenance_active": True, "channel": "tk"}]), [])

    def test_14_windows_notification_suppressed(self):
        self.assertEqual(filter_operational_alerts([{"maintenance_active": True, "provider": "windows"}]), [])

    def test_15_generic_webhook_suppressed(self):
        self.assertEqual(filter_operational_alerts([{"maintenance_active": True, "provider": "generic_webhook"}]), [])

    def test_16_teams_suppressed(self):
        self.assertEqual(filter_operational_alerts([{"maintenance_active": True, "provider": "teams_webhook"}]), [])

    def test_17_no_delivery_history_row_when_not_enqueued(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NotificationHistoryStore(str(Path(folder) / "events.db"))
            filter_operational_alerts([{"maintenance_active": True}])
            self.assertEqual(store.list_deliveries(), [])

    def test_18_maintenance_start_event_recorded(self):
        self.assertEqual(maint(START, EVENT_MAINTENANCE_STARTED).event_type, EVENT_MAINTENANCE_STARTED)

    def test_19_maintenance_end_event_recorded(self):
        event = maint(END, EVENT_MAINTENANCE_ENDED, end_reason="expired")
        self.assertEqual((event.event_type, event.maintenance_end_reason), (EVENT_MAINTENANCE_ENDED, "expired"))

    def test_20_transitions_after_maintenance_are_not_suppressed(self):
        alerts = [{"maintenance_active": True}, {"maintenance_active": False, "event": "DOWN"}]
        self.assertEqual(filter_operational_alerts(alerts), [alerts[1]])

    def test_21_end_while_offline_does_not_create_down(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START, "DOWN"), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(START + timedelta(hours=2), EVENT_MAINTENANCE_ENDED)]
        self.assertEqual([event.event_type for event in events].count("DOWN"), 1)

    def test_22_pending_premaintenance_retry_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NotificationHistoryStore(str(Path(folder) / "events.db"))
            event = NotificationEvent("DOWN", START.isoformat(), "Demo-PLC", TARGET.host, 102, "N/A", "ONLINE", "OFFLINE")
            row_id = store.insert_delivery(event, "generic_webhook")
            filter_operational_alerts([{"maintenance_active": True}])
            rows = store.list_deliveries()
            self.assertEqual((rows[0].id, rows[0].status), (row_id, "QUEUED"))

    def test_23_raw_availability_unchanged_by_maintenance(self):
        base = [tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]
        planned = [base[0], maint(START, EVENT_MAINTENANCE_STARTED), *base[1:], maint(START + timedelta(hours=3), EVENT_MAINTENANCE_ENDED)]
        self.assertEqual(report(base).rows[0].availability_percent, report(planned).rows[0].availability_percent)

    def test_24_operational_availability_excludes_planned_interval(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED"), maint(START + timedelta(hours=3), EVENT_MAINTENANCE_ENDED)]
        self.assertEqual(report(events).rows[0].operational_availability_percent, 100)

    def test_25_full_outage_inside_maintenance(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED"), maint(START + timedelta(hours=3), EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual((row.planned_downtime_seconds, row.unplanned_downtime_seconds), (3600, 0))

    def test_26_full_outage_outside_maintenance(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]).rows[0]
        self.assertEqual((row.planned_downtime_seconds, row.unplanned_downtime_seconds), (0, 3600))

    def test_27_mixed_outage(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(minutes=30), "DOWN"), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(START + timedelta(hours=2), EVENT_MAINTENANCE_ENDED), tcp(START + timedelta(hours=3), "RECOVERED")]
        outage = report(events).outages[0]
        self.assertEqual((outage.maintenance_overlap_seconds, outage.unplanned_downtime_seconds, outage.classification), (3600, 5400, "MIXED"))

    def test_28_maintenance_crosses_period_start(self):
        row = report([tcp(START - timedelta(hours=2), "RECOVERED"), maint(START - timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.planned_maintenance_seconds, 3600)

    def test_29_maintenance_crosses_period_end(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(END - timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(END + timedelta(hours=1), EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.planned_maintenance_seconds, 3600)

    def test_30_maintenance_spans_whole_report(self):
        row = report([tcp(START - timedelta(hours=2), "RECOVERED"), maint(START - timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(END + timedelta(hours=1), EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.planned_maintenance_seconds, 4 * 3600)

    def test_31_ongoing_maintenance(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_STARTED)]).rows[0]
        self.assertEqual(row.planned_maintenance_seconds, 3 * 3600)

    def test_32_unknown_state_during_maintenance(self):
        row = report([maint(START, EVENT_MAINTENANCE_STARTED), maint(END, EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.known_duration_seconds, 0); self.assertIsNone(row.operational_availability_percent)

    def test_33_zero_operational_eligible_duration(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), maint(END, EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.operational_eligible_seconds, 0); self.assertIsNone(row.operational_availability_percent)

    def test_34_planned_maintenance_duration(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(START + timedelta(hours=2), EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.planned_maintenance_seconds, 3600)

    def test_35_planned_downtime(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED"), maint(END, EVENT_MAINTENANCE_ENDED)]).rows[0]
        self.assertEqual(row.planned_downtime_seconds, 3600)

    def test_36_unplanned_downtime(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]).rows[0]
        self.assertEqual(row.unplanned_downtime_seconds, 3600)

    def test_37_unplanned_outage_count(self):
        row = report([tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]).rows[0]
        self.assertEqual(row.unplanned_outage_count, 1)

    def test_38_outage_classification_planned(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED"), maint(END, EVENT_MAINTENANCE_ENDED)]
        self.assertEqual(report(events).outages[0].classification, "PLANNED")

    def test_39_outage_classification_unplanned(self):
        self.assertEqual(report([tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START + timedelta(hours=1), "DOWN")]).outages[0].classification, "UNPLANNED")

    def test_40_outage_classification_mixed(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), tcp(START, "DOWN"), maint(START + timedelta(hours=1), EVENT_MAINTENANCE_STARTED), maint(START + timedelta(hours=2), EVENT_MAINTENANCE_ENDED), tcp(START + timedelta(hours=3), "RECOVERED")]
        self.assertEqual(report(events).outages[0].classification, "MIXED")

    def test_41_outage_detail_maintenance_overlap(self):
        events = [tcp(START - timedelta(minutes=1), "RECOVERED"), maint(START, EVENT_MAINTENANCE_STARTED), tcp(START + timedelta(hours=1), "DOWN"), tcp(START + timedelta(hours=2), "RECOVERED")]
        self.assertEqual(report(events).outages[0].maintenance_overlap_seconds, 3600)

    def test_42_availability_csv_new_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.csv"; export_summary_csv(str(path), report([tcp(START - timedelta(minutes=1), "RECOVERED")]).rows)
            header = path.read_text(encoding="utf-8-sig").splitlines()[0]
            self.assertIn("operational_availability_percent", header); self.assertIn("planned_downtime_seconds", header)

    def test_43_event_csv_maintenance_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.csv"; export_events_csv(str(path), [maint(START, EVENT_MAINTENANCE_STARTED)])
            with path.open(encoding="utf-8-sig", newline="") as stream: row = next(csv.DictReader(stream))
            self.assertEqual(row["event_type"], EVENT_MAINTENANCE_STARTED)

    def test_44_device_group_and_maintenance_combination(self):
        record = make_target_record(TARGET.device_name, TARGET.host, 102, TARGET.groups, start_maintenance("1 hour", now=START).to_config())
        self.assertEqual(record["groups"], ["PLC", "Critical"]); self.assertTrue(record["maintenance"]["enabled"])

    def test_45_hidden_tray_does_not_affect_expiry_helper(self):
        _hidden = True
        self.assertTrue(expire_maintenance(start_maintenance("30 minutes", now=START), END)[1])

    def test_46_shutdown_preserves_active_maintenance_config(self):
        state = start_maintenance("Until manually ended", now=START)
        self.assertTrue(normalize_maintenance(state.to_config()).enabled)

    def test_47_relaunch_state_restoration(self):
        record = normalize_target_record(make_target_record(TARGET.device_name, TARGET.host, 102, (), start_maintenance("2 hours", now=START).to_config()))
        self.assertTrue(normalize_maintenance(record["maintenance"]).enabled)

    def test_48_malformed_maintenance_config(self):
        self.assertFalse(normalize_maintenance({"enabled": True, "started_at": "bad", "reason": []}).enabled)

    def test_49_unicode_maintenance_reason(self):
        self.assertEqual(start_maintenance("1 hour", reason="ปรับปรุงระบบ", now=START).reason, "ปรับปรุงระบบ")

    def test_50_no_secret_bearing_maintenance_fields_and_migration_performance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, event_type TEXT NOT NULL, device_name TEXT NOT NULL DEFAULT '', host TEXT NOT NULL, port INTEGER NOT NULL, ping TEXT NOT NULL, previous_status TEXT NOT NULL, new_status TEXT NOT NULL, downtime_seconds REAL)")
            connection.execute("INSERT INTO events(timestamp,event_type,device_name,host,port,ping,previous_status,new_status) VALUES (?,?,?,?,?,?,?,?)", (START.isoformat(), "DOWN", "Demo-PLC", TARGET.host, 102, "N/A", "ONLINE", "OFFLINE")); connection.commit(); connection.close()
            store = EventHistoryStore(str(path)); self.assertEqual(len(store.list_events()), 1)
            self.assertTrue(store.insert(maint(END, EVENT_MAINTENANCE_ENDED)))
            columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(events)")}
            self.assertIn("maintenance_reason", columns); self.assertNotIn("endpoint", columns)
            events = [tcp(START - timedelta(minutes=1), "RECOVERED")]
            for index in range(5000):
                moment = START + timedelta(seconds=index)
                events.extend((maint(moment, EVENT_MAINTENANCE_STARTED), maint(moment + timedelta(milliseconds=500), EVENT_MAINTENANCE_ENDED)))
            before = time.perf_counter(); report(events); self.assertLess(time.perf_counter() - before, 3.0)


if __name__ == "__main__":
    unittest.main()
