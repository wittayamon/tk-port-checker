import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from availability_report import ConfiguredTarget, calculate_availability, export_summary_csv, filter_report_rows
from event_history import EventRecord
from maintenance import MAX_GROUP_LENGTH, MAX_GROUPS, current_group_list, group_matches, normalize_groups
from monitoring_state import make_target_record, normalize_target_record


ZONE = timezone(timedelta(hours=7))
START = datetime(2026, 9, 8, tzinfo=ZONE)
END = START + timedelta(hours=1)


def recovered():
    return EventRecord((START - timedelta(minutes=1)).isoformat(), "RECOVERED", "Demo-PLC", "192.0.2.10", 102, "1 ms", "OFFLINE", "ONLINE")


class DeviceGroupTests(unittest.TestCase):
    def test_01_old_target_defaults_groups_empty(self):
        self.assertEqual(normalize_target_record({"host": "192.0.2.10", "port": 102})["groups"], [])

    def test_02_one_group(self):
        self.assertEqual(normalize_groups("PLC"), ["PLC"])

    def test_03_multiple_groups(self):
        self.assertEqual(normalize_groups("PLC, Critical"), ["PLC", "Critical"])

    def test_04_whitespace_trimmed(self):
        self.assertEqual(normalize_groups("  PLC , Critical  "), ["PLC", "Critical"])

    def test_05_duplicate_removed(self):
        self.assertEqual(normalize_groups("PLC,PLC"), ["PLC"])

    def test_06_case_insensitive_duplicate_preserves_first_form(self):
        self.assertEqual(normalize_groups("PLC, plc, Plc"), ["PLC"])

    def test_07_empty_tags_removed(self):
        self.assertEqual(normalize_groups("PLC, , ,Critical,"), ["PLC", "Critical"])

    def test_08_max_length_validation(self):
        with self.assertRaises(ValueError):
            normalize_groups("X" * (MAX_GROUP_LENGTH + 1), strict=True)

    def test_09_max_group_count_validation(self):
        with self.assertRaises(ValueError):
            normalize_groups([f"Group-{n}" for n in range(MAX_GROUPS + 1)], strict=True)

    def test_10_unicode_group(self):
        self.assertEqual(normalize_groups("ทดสอบ, Network"), ["ทดสอบ", "Network"])

    def test_11_all_groups_filter(self):
        self.assertTrue(group_matches(["PLC"], "All Groups"))

    def test_12_one_group_filter_case_insensitive(self):
        self.assertTrue(group_matches(["Critical"], "critical"))

    def test_13_different_targets_same_group(self):
        records = [{"groups": ["Network"]}, {"groups": ["network"]}]
        self.assertEqual(current_group_list(records), ["Network"])

    def test_14_transient_scan_excluded_from_supplied_persistent_records(self):
        persistent = [{"groups": ["PLC"]}]
        transient = {"groups": ["Scan"]}
        self.assertEqual(current_group_list(persistent), ["PLC"])
        self.assertNotIn("Scan", current_group_list(persistent))
        self.assertEqual(transient["groups"], ["Scan"])

    def test_15_group_edit_persistence(self):
        record = make_target_record("Demo-PLC", "192.0.2.10", 102, ["PLC", "Critical"])
        self.assertEqual(normalize_target_record(record)["groups"], ["PLC", "Critical"])

    def test_16_group_removal(self):
        record = make_target_record("Demo-PLC", "192.0.2.10", 102, [])
        self.assertEqual(record["groups"], [])

    def test_17_current_group_list_rebuild_sorted(self):
        records = [{"groups": ["Server", "Critical"]}, {"groups": ["PLC"]}]
        self.assertEqual(current_group_list(records), ["Critical", "PLC", "Server"])

    def test_18_availability_group_filter_uses_current_config(self):
        targets = [ConfiguredTarget("Demo-PLC", "192.0.2.10", 102, ("PLC",)), ConfiguredTarget("Gateway-01", "192.0.2.20", 443, ("Network",))]
        report = calculate_availability([recovered()], START, END, targets)
        self.assertEqual([row.host for row in filter_report_rows(report.rows, group="plc")], ["192.0.2.10"])

    def test_19_csv_group_export(self):
        row = calculate_availability([recovered()], START, END, [ConfiguredTarget("Demo-PLC", "192.0.2.10", 102, ("PLC", "Critical"))]).rows[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.csv"
            export_summary_csv(str(path), [row])
            with path.open(encoding="utf-8-sig", newline="") as stream:
                data = next(csv.DictReader(stream))
            self.assertEqual(data["groups"], "PLC, Critical")

    def test_20_public_safe_group_fixture(self):
        record = make_target_record("Test-Server", "198.51.100.20", 443, ["Lab"])
        self.assertEqual((record["name"], record["host"]), ("Test-Server", "198.51.100.20"))


if __name__ == "__main__":
    unittest.main()
