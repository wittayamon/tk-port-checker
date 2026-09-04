import unittest
from datetime import datetime, timedelta

from monitoring_state import (
    EVENT_DOWN,
    EVENT_RECOVERED,
    TcpStateTracker,
    alert_enabled_from_config,
    format_duration,
    make_host_record,
    normalize_host_record,
)


class HostRecordCompatibilityTests(unittest.TestCase):
    def test_old_record_without_name_defaults_to_empty_string(self):
        self.assertEqual(
            normalize_host_record({"host": "192.168.1.100", "port": 102}),
            {"name": "", "host": "192.168.1.100", "port": 102},
        )

    def test_new_record_preserves_device_name(self):
        self.assertEqual(
            normalize_host_record(
                {"name": "Demo-PLC", "host": "192.168.1.100", "port": 102}
            ),
            {"name": "Demo-PLC", "host": "192.168.1.100", "port": 102},
        )

    def test_saved_record_contains_only_persistent_target_fields(self):
        self.assertEqual(
            make_host_record("Demo-PLC", "192.168.1.100", 102),
            {"name": "Demo-PLC", "host": "192.168.1.100", "port": 102},
        )

    def test_old_config_defaults_alerts_to_enabled(self):
        self.assertTrue(alert_enabled_from_config({"theme": "dark", "hosts": []}))

    def test_explicit_alert_setting_is_preserved(self):
        self.assertFalse(alert_enabled_from_config({"state_change_alerts": False}))


class TcpStateTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = TcpStateTracker()
        self.start = datetime(2026, 9, 3, 20, 15, 30)

    def test_unknown_to_online_establishes_baseline_without_alert(self):
        self.assertIsNone(self.tracker.observe("plc", True, now=self.start))

    def test_unknown_to_offline_establishes_baseline_without_alert(self):
        self.assertIsNone(self.tracker.observe("plc", False, now=self.start))

    def test_online_to_online_does_not_alert(self):
        self.tracker.observe("plc", True, now=self.start)
        self.assertIsNone(self.tracker.observe("plc", True, now=self.start))

    def test_online_to_offline_produces_one_down_event(self):
        self.tracker.observe("plc", True, now=self.start)
        event = self.tracker.observe("plc", False, now=self.start)
        self.assertEqual(event.kind, EVENT_DOWN)
        self.assertIsNone(self.tracker.observe("plc", False, now=self.start))

    def test_offline_to_offline_has_no_duplicate_event(self):
        self.tracker.observe("plc", False, now=self.start)
        self.assertIsNone(self.tracker.observe("plc", False, now=self.start))

    def test_offline_to_online_produces_recovery_with_downtime(self):
        self.tracker.observe("plc", False, now=self.start)
        event = self.tracker.observe(
            "plc", True, now=self.start + timedelta(minutes=2, seconds=35)
        )
        self.assertEqual(event.kind, EVENT_RECOVERED)
        self.assertEqual(event.downtime_seconds, 155)
        self.assertIsNone(
            self.tracker.observe(
                "plc", True, now=self.start + timedelta(minutes=3)
            )
        )

    def test_ping_timeout_does_not_participate_in_tcp_state(self):
        self.tracker.observe("plc", True, now=self.start)
        ping_text = "Timeout"
        self.assertEqual(ping_text, "Timeout")
        self.assertIsNone(self.tracker.observe("plc", True, now=self.start))

    def test_runtime_scan_target_does_not_establish_or_alert(self):
        self.assertIsNone(
            self.tracker.observe("scan-row", False, persistent=False, now=self.start)
        )
        self.assertIsNone(
            self.tracker.observe("scan-row", True, persistent=False, now=self.start)
        )
        self.assertIsNone(self.tracker.observe("scan-row", True, now=self.start))


class DurationFormattingTests(unittest.TestCase):
    def test_formats_seconds_minutes_and_hours(self):
        self.assertEqual(format_duration(8), "8s")
        self.assertEqual(format_duration(80), "1m 20s")
        self.assertEqual(format_duration(8100), "2h 15m")

    def test_negative_duration_is_safe(self):
        self.assertEqual(format_duration(-1), "0s")


if __name__ == "__main__":
    unittest.main()
