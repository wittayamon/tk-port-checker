import csv
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from availability_report import (
    ConfiguredTarget, PERIOD_7_DAYS, PERIOD_30_DAYS, PERIOD_CUSTOM, PERIOD_TODAY,
    build_availability_report, calculate_availability, export_outages_csv,
    export_summary_csv, filter_outages, filter_report_rows, intersect_interval,
    report_period, sort_report_rows,
)
from event_history import EventHistoryStore, EventRecord
from notification_history import NotificationHistoryStore


ZONE = timezone(timedelta(hours=7))
START = datetime(2026, 9, 7, 0, 0, tzinfo=ZONE)
END = START + timedelta(hours=24)


def event(when, kind, name="Demo-PLC", host="192.0.2.10", port=102):
    return EventRecord(
        timestamp=when.isoformat(timespec="seconds"), event_type=kind,
        device_name=name, host=host, port=port, ping="N/A",
        previous_status="ONLINE" if kind == "DOWN" else "OFFLINE",
        new_status="OFFLINE" if kind == "DOWN" else "ONLINE",
        downtime_seconds=None,
    )


def row_for(events, start=START, end=END, targets=()):
    return calculate_availability(events, start, end, targets).rows[0]


class PeriodTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 7, 15, 30, tzinfo=ZONE)

    def test_today_is_local_midnight_to_now(self):
        start, end = report_period(PERIOD_TODAY, now=self.now)
        self.assertEqual(start, self.now.replace(hour=0, minute=0))
        self.assertEqual(end, self.now)

    def test_seven_days_is_rolling_168_hours(self):
        start, end = report_period(PERIOD_7_DAYS, now=self.now)
        self.assertEqual(end - start, timedelta(days=7))

    def test_thirty_days_is_rolling_720_hours(self):
        start, end = report_period(PERIOD_30_DAYS, now=self.now)
        self.assertEqual(end - start, timedelta(days=30))

    def test_custom_whole_historical_dates(self):
        start, end = report_period(PERIOD_CUSTOM, now=self.now, start_date="2026-09-01", end_date="2026-09-02")
        self.assertEqual(end - start, timedelta(days=2))

    def test_custom_today_is_capped_at_injected_now(self):
        start, end = report_period(PERIOD_CUSTOM, now=self.now, start_date="2026-09-07", end_date="2026-09-07")
        self.assertEqual((start, end), (self.now.replace(hour=0, minute=0), self.now))

    def test_custom_bad_format_rejected(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            report_period(PERIOD_CUSTOM, now=self.now, start_date="09/01/2026", end_date="2026-09-02")

    def test_custom_end_before_start_rejected(self):
        with self.assertRaisesRegex(ValueError, "on or after"):
            report_period(PERIOD_CUSTOM, now=self.now, start_date="2026-09-03", end_date="2026-09-02")

    def test_future_custom_range_rejected(self):
        with self.assertRaisesRegex(ValueError, "has not started"):
            report_period(PERIOD_CUSTOM, now=self.now, start_date="2026-09-08", end_date="2026-09-08")


class IntervalTests(unittest.TestCase):
    def test_interval_intersection(self):
        self.assertEqual(intersect_interval(START - timedelta(minutes=10), START + timedelta(minutes=20), START, END), 1200)

    def test_non_intersecting_interval(self):
        self.assertEqual(intersect_interval(START - timedelta(hours=2), START - timedelta(hours=1), START, END), 0)

    def test_invalid_identical_report_boundaries_rejected(self):
        with self.assertRaises(ValueError):
            calculate_availability([], START, START)


class AvailabilityCalculationTests(unittest.TestCase):
    def test_no_events_configured_target_is_unknown(self):
        row = row_for([], targets=[ConfiguredTarget("Demo-PLC", "192.0.2.10", 102)])
        self.assertIsNone(row.availability_percent)
        self.assertEqual(row.coverage_percent, 0)
        self.assertEqual(row.period_duration_seconds, 86400)
        self.assertEqual(row.unknown_duration_seconds, 86400)

    def test_no_events_and_no_configured_targets_has_no_rows(self):
        self.assertEqual(calculate_availability([], START, END).rows, ())

    def test_prior_recovered_makes_full_period_online(self):
        row = row_for([event(START - timedelta(hours=1), "RECOVERED")])
        self.assertEqual(row.availability_percent, 100)
        self.assertEqual(row.coverage_percent, 100)
        self.assertEqual(row.known_duration_seconds, 86400)

    def test_one_completed_outage_metrics(self):
        events = [event(START - timedelta(hours=1), "RECOVERED"), event(START + timedelta(hours=1), "DOWN"), event(START + timedelta(hours=2), "RECOVERED")]
        row = row_for(events)
        self.assertAlmostEqual(row.availability_percent, 95.833333, places=5)
        self.assertEqual(row.downtime_seconds, 3600)
        self.assertEqual(row.outage_count, 1)
        self.assertEqual(row.longest_outage_seconds, 3600)
        self.assertEqual(row.average_outage_seconds, 3600)
        self.assertEqual(row.mttr_seconds, 3600)

    def test_multiple_outages(self):
        events = [event(START - timedelta(minutes=1), "RECOVERED"), event(START + timedelta(hours=1), "DOWN"), event(START + timedelta(hours=2), "RECOVERED"), event(START + timedelta(hours=4), "DOWN"), event(START + timedelta(hours=6), "RECOVERED")]
        row = row_for(events)
        self.assertEqual(row.downtime_seconds, 10800)
        self.assertEqual(row.outage_count, 2)
        self.assertEqual(row.longest_outage_seconds, 7200)
        self.assertEqual(row.average_outage_seconds, 5400)
        self.assertEqual(row.mttr_seconds, 5400)

    def test_outage_crossing_period_start_is_clipped(self):
        report = calculate_availability([event(START - timedelta(minutes=10), "DOWN"), event(START + timedelta(minutes=20), "RECOVERED")], START, END)
        self.assertEqual(report.rows[0].downtime_seconds, 1200)
        self.assertEqual(report.outages[0].actual_duration_seconds, 1800)

    def test_outage_crossing_period_end_is_clipped(self):
        report = calculate_availability([event(START - timedelta(minutes=1), "RECOVERED"), event(END - timedelta(minutes=10), "DOWN"), event(END + timedelta(minutes=20), "RECOVERED")], START, END)
        self.assertEqual(report.rows[0].downtime_seconds, 600)
        self.assertEqual(report.outages[0].status, "RECOVERED")
        self.assertIsNone(report.rows[0].mttr_seconds)

    def test_outage_crossing_both_boundaries(self):
        report = calculate_availability([event(START - timedelta(hours=1), "DOWN"), event(END + timedelta(hours=1), "RECOVERED")], START, END)
        self.assertEqual(report.rows[0].downtime_seconds, 86400)
        self.assertEqual(report.rows[0].availability_percent, 0)

    def test_ongoing_outage_uses_report_end(self):
        report = calculate_availability([event(START - timedelta(hours=1), "RECOVERED"), event(START + timedelta(hours=10), "DOWN")], START, END)
        self.assertEqual(report.rows[0].downtime_seconds, 50400)
        self.assertEqual(report.outages[0].status, "ONGOING")
        self.assertIsNone(report.outages[0].recovered_at)
        self.assertIsNone(report.rows[0].mttr_seconds)

    def test_prior_down_establishes_offline_at_start(self):
        row = row_for([event(START - timedelta(hours=1), "DOWN")])
        self.assertEqual(row.coverage_percent, 100)
        self.assertEqual(row.downtime_seconds, 86400)

    def test_first_down_leaves_earlier_period_unknown(self):
        row = row_for([event(START + timedelta(hours=12), "DOWN")])
        self.assertEqual(row.known_duration_seconds, 43200)
        self.assertEqual(row.unknown_duration_seconds, 43200)
        self.assertEqual(row.coverage_percent, 50)
        self.assertEqual(row.availability_percent, 0)

    def test_first_recovered_leaves_earlier_period_unknown(self):
        row = row_for([event(START + timedelta(hours=12), "RECOVERED")])
        self.assertEqual(row.coverage_percent, 50)
        self.assertEqual(row.availability_percent, 100)

    def test_event_exactly_at_start_applies_immediately(self):
        row = row_for([event(START, "RECOVERED")])
        self.assertEqual(row.known_duration_seconds, 86400)

    def test_down_exactly_at_end_adds_no_outage(self):
        row = row_for([event(START - timedelta(minutes=1), "RECOVERED"), event(END, "DOWN")])
        self.assertEqual(row.outage_count, 0)
        self.assertEqual(row.downtime_seconds, 0)

    def test_recovery_exactly_at_end_completes_outage(self):
        row = row_for([event(START, "DOWN"), event(END, "RECOVERED")])
        self.assertEqual(row.outage_count, 1)
        self.assertEqual(row.mttr_seconds, 86400)

    def test_duplicate_down_does_not_start_second_outage(self):
        row = row_for([event(START, "DOWN"), event(START + timedelta(hours=1), "DOWN"), event(START + timedelta(hours=2), "RECOVERED")])
        self.assertEqual(row.outage_count, 1)
        self.assertEqual(row.downtime_seconds, 7200)

    def test_duplicate_recovered_is_idempotent(self):
        row = row_for([event(START, "RECOVERED"), event(START + timedelta(hours=1), "RECOVERED")])
        self.assertEqual(row.availability_percent, 100)
        self.assertEqual(row.outage_count, 0)

    def test_recovered_while_unknown_establishes_online(self):
        row = row_for([event(START + timedelta(hours=6), "RECOVERED")])
        self.assertEqual(row.unknown_duration_seconds, 21600)

    def test_malformed_timestamp_is_ignored(self):
        bad = EventRecord("bad", "DOWN", "Demo", "192.0.2.1", 80, "N/A", "ONLINE", "OFFLINE")
        row = row_for([bad], targets=[ConfiguredTarget("Demo", "192.0.2.1", 80)])
        self.assertIsNone(row.availability_percent)

    def test_same_host_different_ports_are_separate(self):
        report = calculate_availability([event(START, "RECOVERED", port=80), event(START, "RECOVERED", port=443)], START, END)
        self.assertEqual({row.port for row in report.rows}, {80, 443})

    def test_device_name_falls_back_to_host(self):
        row = row_for([event(START, "RECOVERED", name="")])
        self.assertEqual(row.display_name, "192.0.2.10")

    def test_newest_nonempty_device_name_wins(self):
        row = row_for([event(START, "RECOVERED", name="Demo-PLC"), event(START + timedelta(hours=1), "DOWN", name="Gateway-01")])
        self.assertEqual(row.device_name, "Gateway-01")

    def test_empty_newest_name_preserves_previous_name(self):
        row = row_for([event(START, "RECOVERED", name="Demo-PLC"), event(START + timedelta(hours=1), "DOWN", name="")])
        self.assertEqual(row.device_name, "Demo-PLC")

    def test_unicode_device_name_is_preserved(self):
        row = row_for([event(START, "RECOVERED", name="อุปกรณ์ทดสอบ")])
        self.assertEqual(row.device_name, "อุปกรณ์ทดสอบ")

    def test_current_configured_name_overrides_historical_name(self):
        row = row_for(
            [event(START, "RECOVERED", name="Demo-PLC")],
            targets=[ConfiguredTarget("Gateway-01", "192.0.2.10", 102)],
        )
        self.assertEqual(row.device_name, "Gateway-01")

    def test_future_only_historical_target_is_not_included(self):
        report = calculate_availability([event(END + timedelta(hours=1), "DOWN")], START, END)
        self.assertEqual(report.rows, ())

    def test_future_event_does_not_change_period_coverage(self):
        row = row_for([event(START, "RECOVERED"), event(END + timedelta(hours=1), "DOWN")])
        self.assertEqual(row.coverage_percent, 100)
        self.assertEqual(row.downtime_seconds, 0)

    def test_outage_entirely_before_range_is_not_counted(self):
        row = row_for([event(START - timedelta(hours=2), "DOWN"), event(START - timedelta(hours=1), "RECOVERED")])
        self.assertEqual(row.outage_count, 0)
        self.assertEqual(row.availability_percent, 100)

    def test_unrecognized_event_type_is_ignored(self):
        unknown = event(START, "RECOVERED")
        unknown = EventRecord(unknown.timestamp, "NOTICE", unknown.device_name, unknown.host, unknown.port, unknown.ping, "UNKNOWN", "UNKNOWN")
        row = row_for([unknown], targets=[ConfiguredTarget("Demo-PLC", "192.0.2.10", 102)])
        self.assertIsNone(row.availability_percent)


class FilterSortExportTests(unittest.TestCase):
    def setUp(self):
        self.report = calculate_availability([
            event(START, "RECOVERED", name="Demo-PLC", host="192.0.2.10", port=102),
            event(START, "RECOVERED", name="Test-Server", host="198.51.100.20", port=443),
            event(START + timedelta(hours=1), "DOWN", name="Test-Server", host="198.51.100.20", port=443),
        ], START, END)

    def test_search_filters_device_case_insensitively(self):
        self.assertEqual(filter_report_rows(self.report.rows, "server")[0].port, 443)

    def test_search_filters_host(self):
        self.assertEqual(len(filter_report_rows(self.report.rows, "192.0.2")), 1)

    def test_outage_search_filter(self):
        self.assertEqual(len(filter_outages(self.report.outages, "Test-Server")), 1)

    def test_sorting_helpers(self):
        self.assertEqual(sort_report_rows(self.report.rows, "downtime", True)[0].port, 443)
        self.assertEqual(sort_report_rows(self.report.rows, "outages", True)[0].outage_count, 1)

    def test_summary_csv_has_bom_and_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.csv"
            self.assertEqual(export_summary_csv(str(path), self.report.rows), 2)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertIn("coverage_percent", row)
            self.assertIn("mttr_display", row)

    def test_outage_csv_has_bom_and_no_notification_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "outages.csv"
            self.assertEqual(export_outages_csv(str(path), self.report.outages), 1)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            header = path.read_text(encoding="utf-8-sig").splitlines()[0]
            self.assertNotIn("provider", header)
            self.assertIn("period_overlap_seconds", header)


class StorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "events.db"
        self.events = EventHistoryStore(str(self.path))
        self.notifications = NotificationHistoryStore(str(self.path))

    def tearDown(self):
        self.folder.cleanup()

    def test_report_does_not_change_event_history(self):
        self.events.insert(event(START, "RECOVERED"))
        before = self.events.list_events()
        build_availability_report(self.events, START, END)
        self.assertEqual(self.events.list_events(), before)

    def test_report_does_not_change_notification_history(self):
        connection = sqlite3.connect(self.path)
        try:
            before = connection.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0]
        finally:
            connection.close()
        build_availability_report(self.events, START, END)
        connection = sqlite3.connect(self.path)
        try:
            after = connection.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(after, before)

    def test_clearing_event_history_removes_report_evidence(self):
        self.events.insert(event(START, "RECOVERED"))
        self.assertEqual(len(build_availability_report(self.events, START, END).rows), 1)
        self.events.clear()
        self.assertEqual(build_availability_report(self.events, START, END).rows, ())

    def test_large_retained_fixture_performance_sanity(self):
        items = []
        base = START - timedelta(days=30)
        for index in range(10_000):
            items.append(event(base + timedelta(minutes=index), "DOWN" if index % 2 == 0 else "RECOVERED", host=f"192.0.2.{index % 50 + 1}", port=1000 + index % 4))
        started = time.perf_counter()
        report = calculate_availability(items, START - timedelta(days=7), START)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertGreater(len(report.rows), 1)


if __name__ == "__main__":
    unittest.main()
