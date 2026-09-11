import copy
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import settings_backup as backup
from app_version import APP_VERSION
from maintenance import MANUAL_DURATION, start_maintenance


NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


def target(**values):
    return dict(host="192.0.2.10", port=443, name="Demo-PLC", groups=["Demo"], **values)


def config():
    return dict(hosts=[target()], theme="dark", state_change_alerts=True,
        minimize_to_tray=True, close_to_tray=False, start_hidden_on_windows_startup=True,
        windows_notifications_enabled=True, generic_webhook_enabled=True,
        generic_webhook_url="https://example.invalid/demo", teams_webhook_enabled=True,
        teams_webhook_url="https://example.invalid/teams", notification_timeout_seconds=8,
        notification_retry_count=3, notification_retry_later_enabled=True)


class BackupFormatTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.payload = backup.build_backup(self.config, now=NOW)

    def test_format(self):
        self.assertEqual(self.payload["format"], "MultiPortCheckerBackup")

    def test_format_version(self):
        self.assertEqual(self.payload["backup_version"], backup.BACKUP_FORMAT_VERSION)

    def test_app_version(self):
        self.assertEqual(self.payload["app_version"], APP_VERSION)

    def test_timestamp(self):
        self.assertEqual(self.payload["created_at"], NOW.isoformat())

    def test_secret_metadata(self):
        self.assertIs(self.payload["secrets_included"], False)

    def test_safe_preferences(self):
        for key in backup.PREFERENCES | backup.NOTIFICATIONS:
            self.assertEqual(self.payload["settings"][key], self.config[key])

    def test_target_identity(self):
        self.assertEqual(self.payload["targets"][0]["host"], "192.0.2.10")
        self.assertEqual(self.payload["targets"][0]["port"], 443)

    def test_target_metadata(self):
        self.assertEqual(self.payload["targets"][0]["name"], "Demo-PLC")
        self.assertEqual(self.payload["targets"][0]["groups"], ["Demo"])

    def test_legacy_decimal_port_export(self):
        self.config["hosts"][0]["port"] = "443"
        self.assertEqual(backup.build_backup(self.config)["targets"][0]["port"], 443)

    def test_maintenance_reset(self):
        self.config["hosts"][0]["maintenance"] = start_maintenance(MANUAL_DURATION, reason="Demo work", now=NOW).to_config()
        state = backup.build_backup(self.config)["targets"][0]["maintenance"]
        self.assertEqual(state, dict(enabled=False, started_at=None, until=None, reason=""))

    def test_unicode_roundtrip(self):
        self.config["hosts"][0].update(name="อุปกรณ์ทดสอบ", groups=["ทดสอบ"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.json"
            payload = backup.build_backup(self.config)
            backup.atomic_write_json(path, payload)
            self.assertIn("ทดสอบ", path.read_text(encoding="utf-8"))
            self.assertEqual(backup.read_backup(path).payload, payload)

    def test_invalid_export_stops(self):
        self.config["hosts"][0]["port"] = 0
        with self.assertRaises(backup.BackupError):
            backup.build_backup(self.config)

    def test_duplicate_export_stops(self):
        self.config["hosts"] *= 2
        with self.assertRaises(backup.BackupError):
            backup.build_backup(self.config)

    def test_no_mutation(self):
        original = copy.deepcopy(self.config)
        backup.build_backup(self.config)
        self.assertEqual(self.config, original)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.current = config()
        self.payload = backup.build_backup(self.current, now=NOW)

    def test_valid(self):
        self.assertEqual(backup.validate_backup(self.payload).payload, self.payload)

    def test_optional_fields_missing(self):
        value = backup.validate_backup(dict(format="MultiPortCheckerBackup", backup_version=1))
        self.assertEqual(value.payload["settings"], {})
        self.assertEqual(value.payload["targets"], [])

    def test_unknown_fields(self):
        self.payload["future"] = {"nested": [1, 2]}
        self.payload["settings"]["token"] = "fictional-placeholder"
        parsed = backup.validate_backup(self.payload)
        self.assertEqual(len(parsed.warnings), 1)
        self.assertNotIn("token", parsed.payload["settings"])

    def test_unknown_target_field(self):
        self.payload["targets"][0]["future"] = True
        self.assertTrue(backup.validate_backup(self.payload).warnings)

    def test_newer_app_same_format(self):
        self.payload["app_version"] = "99.0.0"
        self.assertEqual(len(backup.validate_backup(self.payload).payload["targets"]), 1)

    def test_older_app_same_format(self):
        self.payload["app_version"] = "1.7.0"
        self.assertEqual(len(backup.validate_backup(self.payload).payload["targets"]), 1)

    def test_duplicates_first_wins(self):
        other = dict(self.payload["targets"][0], name="Device-01")
        self.payload["targets"].append(other)
        parsed = backup.validate_backup(self.payload)
        self.assertEqual(parsed.duplicates, 1)
        self.assertEqual(parsed.payload["targets"][0]["name"], "Demo-PLC")

    def test_identity_casefold(self):
        self.payload["targets"] = [dict(target(), host="EXAMPLE.COM"), dict(target(), host="example.com")]
        self.assertEqual(backup.validate_backup(self.payload).duplicates, 1)

    def test_ports_distinct(self):
        self.payload["targets"].append(dict(target(), port=80))
        self.assertEqual(len(backup.validate_backup(self.payload).payload["targets"]), 2)

    def test_maximum_target_count_accepted(self):
        self.payload["targets"] = [dict(target(), port=i + 1) for i in range(10000)]
        self.assertEqual(len(backup.validate_backup(self.payload).payload["targets"]), 10000)

    def test_normalized_groups(self):
        self.payload["targets"][0]["groups"] = [" Demo ", "demo", "", "ทดสอบ"]
        self.assertEqual(backup.validate_backup(self.payload).payload["targets"][0]["groups"], ["Demo", "ทดสอบ"])

    def test_comma_groups(self):
        self.payload["targets"][0]["groups"] = " Demo, demo,Other "
        self.assertEqual(backup.validate_backup(self.payload).payload["targets"][0]["groups"], ["Demo", "Other"])

    def test_group_boundaries(self):
        self.payload["targets"][0]["groups"] = [str(i) * 32 for i in range(10)]
        self.assertEqual(backup.validate_backup(self.payload).invalid, 0)

    def test_merge_add(self):
        self.payload["targets"][0]["host"] = "192.0.2.20"
        plan = backup.plan_restore(self.current, self.payload)
        self.assertEqual(len(plan.config["hosts"]), 2)
        self.assertEqual(plan.counts["new"], 1)

    def test_merge_metadata_conflicts(self):
        self.payload["targets"][0].update(name="Device-01", groups=["Other"])
        plan = backup.plan_restore(self.current, self.payload)
        self.assertEqual(plan.counts, dict(new=0, matching=1, names=1, groups=1))
        self.assertEqual(plan.config["hosts"][0]["name"], "Device-01")

    def test_merge_preserves_maintenance(self):
        state = start_maintenance(MANUAL_DURATION, reason="Demo work", now=NOW).to_config()
        self.current["hosts"][0]["maintenance"] = state
        self.assertEqual(backup.plan_restore(self.current, self.payload).config["hosts"][0]["maintenance"], state)

    def test_new_maintenance_disabled(self):
        self.payload["targets"][0]["maintenance"] = start_maintenance(MANUAL_DURATION, reason="Demo work", now=NOW).to_config()
        self.assertFalse(backup.plan_restore(dict(hosts=[]), self.payload).config["hosts"][0]["maintenance"]["enabled"])

    def test_replace(self):
        self.current["hosts"].append(dict(target(), host="192.0.2.30"))
        plan = backup.plan_restore(self.current, self.payload, mode="replace")
        self.assertEqual(len(plan.config["hosts"]), 1)
        self.assertTrue(plan.replace_confirmation_required)

    def test_replace_maintenance_reset(self):
        self.current["hosts"][0]["maintenance"] = start_maintenance(MANUAL_DURATION, reason="Demo work", now=NOW).to_config()
        self.assertFalse(backup.plan_restore(self.current, self.payload, mode="replace").config["hosts"][0]["maintenance"]["enabled"])

    def test_selective_no_targets(self):
        self.payload["targets"] = []
        plan = backup.plan_restore(self.current, self.payload, targets=False, mode="replace")
        self.assertEqual(plan.config["hosts"], self.current["hosts"])
        self.assertFalse(plan.replace_confirmation_required)

    def test_selective_no_preferences(self):
        self.payload["settings"]["theme"] = "light"
        self.assertEqual(backup.plan_restore(self.current, self.payload, preferences=False).config["theme"], "dark")

    def test_selective_no_notifications(self):
        self.payload["settings"]["notification_retry_count"] = 0
        self.assertEqual(backup.plan_restore(self.current, self.payload, notifications=False).config["notification_retry_count"], 3)

    def test_preserve_local_endpoints(self):
        planned = backup.plan_restore(self.current, self.payload).config
        for provider in ("generic_webhook", "teams_webhook"):
            self.assertEqual(planned[provider + "_url"], self.current[provider + "_url"])
            self.assertTrue(planned[provider + "_enabled"])

    def test_missing_endpoints_disabled(self):
        plan = backup.plan_restore(dict(hosts=[]), self.payload)
        for provider in ("generic_webhook", "teams_webhook"):
            self.assertNotIn(provider + "_url", plan.config)
            self.assertFalse(plan.config[provider + "_enabled"])
        self.assertEqual(len(plan.warnings), 2)

    def test_invalid_endpoint_disabled_not_erased(self):
        self.current["generic_webhook_url"] = "invalid"
        plan = backup.plan_restore(self.current, self.payload)
        self.assertFalse(plan.config["generic_webhook_enabled"])
        self.assertEqual(plan.config["generic_webhook_url"], "invalid")

    def test_plan_does_not_mutate(self):
        old = copy.deepcopy(self.current)
        backup.plan_restore(self.current, self.payload)
        self.assertEqual(old, self.current)

    def test_warning_survives_planning(self):
        self.payload["unknown"] = True
        parsed = backup.validate_backup(self.payload)
        self.assertEqual(backup.plan_restore(self.current, parsed).warnings, parsed.warnings)


class FileSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "mpc_config.json"
        self.current = config()
        self.payload = backup.build_backup(self.current, now=NOW)
        backup.atomic_write_json(self.path, self.current)
        self.original = self.path.read_bytes()

    def test_oversized_file(self):
        self.path.write_bytes(b" " * (backup.MAX_BACKUP_BYTES + 1))
        with self.assertRaisesRegex(backup.BackupError, "5 MiB"):
            backup.read_backup(self.path)

    def test_malformed_json_safe_message(self):
        self.path.write_text('{"fictional-private-value":', encoding="utf-8")
        with self.assertRaises(backup.BackupError) as error:
            backup.read_backup(self.path)
        self.assertNotIn("fictional-private-value", str(error.exception))

    def test_malformed_encoding(self):
        self.path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(backup.BackupError):
            backup.read_backup(self.path)

    def test_excessive_json_depth(self):
        self.path.write_text("[" * 2000 + "]" * 2000)
        with self.assertRaises(backup.BackupError):
            backup.read_backup(self.path)

    def test_excessive_integer_digits(self):
        self.path.write_text('{"number":' + '9' * 5000 + '}')
        with self.assertRaises(backup.BackupError):
            backup.read_backup(self.path)

    def test_utf8_bom(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8-sig")
        self.assertEqual(backup.read_backup(self.path).payload, self.payload)

    def test_path_payload_ignored(self):
        self.payload["output_path"] = "../../never-created.json"
        self.payload["settings"]["config_path"] = "../../never-created.json"
        planned = backup.plan_restore(self.current, self.payload).config
        self.assertNotIn("output_path", planned)
        self.assertNotIn("config_path", planned)

    def test_path_label_is_data(self):
        self.payload["targets"][0]["name"] = "../../Demo-PLC"
        planned = backup.plan_restore(self.current, self.payload).config
        self.assertEqual(planned["hosts"][0]["name"], "../../Demo-PLC")
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_atomic_replace_failure(self):
        with patch.object(backup.os, "replace", side_effect=OSError):
            with self.assertRaises(OSError):
                backup.atomic_write_json(self.path, dict(theme="light"))
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_serialization_failure(self):
        with self.assertRaises(TypeError):
            backup.atomic_write_json(self.path, dict(value=object()))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_safety_backup(self):
        plan = backup.plan_restore(self.current, self.payload)
        safety = backup.save_restore(self.path, self.current, plan)
        self.assertEqual(safety.parent, self.path.parent / "backups")
        self.assertFalse(backup.read_backup(safety).payload["secrets_included"])
        self.assertNotIn("generic_webhook_url", safety.read_text())

    def test_safety_backup_failure_aborts(self):
        plan = backup.plan_restore(self.current, self.payload)
        with patch.object(backup, "atomic_write_json", side_effect=OSError) as write:
            with self.assertRaises(OSError):
                backup.save_restore(self.path, self.current, plan)
        self.assertEqual(write.call_count, 1)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_config_save_failure_keeps_disk_and_model(self):
        self.payload["settings"]["theme"] = "light"
        plan = backup.plan_restore(self.current, self.payload)
        original_replace = backup.os.replace
        def replace(source, destination):
            if Path(destination) == self.path:
                raise OSError
            original_replace(source, destination)
        with patch.object(backup.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                backup.save_restore(self.path, self.current, plan)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.current["theme"], "dark")
        self.assertEqual(len(list((self.path.parent / "backups").glob("*.json"))), 1)

    def test_replace_confirmation_required(self):
        plan = backup.plan_restore(self.current, self.payload, mode="replace")
        with self.assertRaises(backup.BackupError):
            backup.save_restore(self.path, self.current, plan)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_replace_confirmed(self):
        plan = backup.plan_restore(self.current, self.payload, mode="replace")
        backup.save_restore(self.path, self.current, plan, replace_confirmed=True)
        self.assertEqual(json.loads(self.path.read_text()), plan.config)

    def test_safety_backup_unique(self):
        plan = backup.plan_restore(self.current, self.payload)
        self.assertNotEqual(backup.save_restore(self.path, self.current, plan), backup.save_restore(self.path, self.current, plan))


# Table-driven boundary cases each have a distinct unittest name for reporting.
def add_cases(cls, prefix, cases, check):
    for name, value in cases.items():
        def test(self, value=value):
            check(self, value)
        setattr(cls, f"test_{prefix}_{name}", test)


def bad_target(self, change):
    self.payload["targets"][0].update(change)
    parsed = backup.validate_backup(self.payload)
    self.assertEqual(parsed.invalid, 1)
    self.assertEqual(parsed.payload["targets"], [])


add_cases(ImportTests, "invalid_target", {
    "empty_host": dict(host=" "), "host_type": dict(host=[]),
    "host_size": dict(host="x" * 254), "port_zero": dict(port=0),
    "port_large": dict(port=65536), "port_bool": dict(port=True),
    "port_float": dict(port=80.0), "port_string": dict(port="443"),
    "name_size": dict(name="x" * 201), "name_object": dict(name={}),
    "group_size": dict(groups=["x" * 33]), "group_count": dict(groups=["x"] * 11),
    "groups_object": dict(groups={}), "group_object": dict(groups=[{}]),
    "unicode_surrogate": dict(name="\ud800"), "control": dict(host="demo\n")}, bad_target)


def invalid_payload(self, change):
    self.payload.update(change)
    with self.assertRaises(backup.BackupError):
        backup.validate_backup(self.payload)


add_cases(ImportTests, "invalid_payload", {
    "marker": dict(format="Other"), "future_format": dict(backup_version=2),
    "old_unsupported": dict(backup_version=0), "version_bool": dict(backup_version=True),
    "settings_list": dict(settings=[]), "targets_object": dict(targets={}),
    "too_many_targets": dict(targets=[{}] * 10001), "app_object": dict(app_version={}),
    "created_size": dict(created_at="x" * 65), "theme_object": dict(settings=dict(theme={})),
    "bool_string": dict(settings=dict(close_to_tray="yes")),
    "timeout": dict(settings=dict(notification_timeout_seconds=31)),
    "retry": dict(settings=dict(notification_retry_count=-1))}, invalid_payload)


def excluded(self, key):
    self.config[key] = "fictional-excluded-value"
    self.config["hosts"][0][key] = "fictional-excluded-value"
    serialized = json.dumps(backup.build_backup(self.config))
    self.assertNotIn(key, serialized)
    self.assertNotIn("fictional-excluded-value", serialized)


add_cases(BackupFormatTests, "excluded", {key: key for key in (
    "generic_webhook_url", "teams_webhook_url", "Authorization", "token", "password",
    "credentials", "api_key", "cookies", "private_key", "events.db", "event_history",
    "notification_history", "retry_queue", "startup_registry", "ping", "status")}, excluded)


if __name__ == "__main__":
    unittest.main()
