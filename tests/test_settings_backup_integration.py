"""Exercise real Tk restore callbacks against isolated config and SQLite paths."""

import ast
import copy
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from settings_backup import BackupError, build_backup, validate_backup
import settings_backup_ui


class SettingsRestoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source_path = Path(__file__).resolve().parents[1] / "multi_port_checker.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        # Only the runtime directory and mainloop are replaced. Production restore,
        # widgets, tracker, notification manager and storage code run unchanged.
        for node in module.body:
            if isinstance(node, ast.FunctionDef) and node.name == "get_app_dir":
                node.body = [ast.Return(ast.Constant(cls.directory.name))]
        module.body = [node for node in module.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "mainloop")]
        ast.fix_missing_locations(module)
        cls.app = dict(__file__=str(source_path), __name__="isolated_backup_test")
        exec(compile(module, str(source_path), "exec"), cls.app)
        cls.app["root"].withdraw()
        cls.addClassCleanup(cls.app["shutdown_application"])
        cls.defaults = cls.app["snapshot_config"]()

    def setUp(self):
        self.app["apply_restored_config"](dict(self.defaults, hosts=[]))
        self.app["insert_persistent_target"](dict(host="192.0.2.10", port=443, name="Demo-PLC", groups=["Demo"]))
        self.app["save_config"]()
        self.current = self.app["snapshot_config"]()
        self.payload = build_backup(self.current)
        self.selection = dict(targets=True, preferences=True, notifications=True, mode="merge")

    def restore(self):
        return self.app["restore_settings_backup"](validate_backup(self.payload), self.selection, self.selection["mode"] == "replace")

    def test_merge_keeps_row_and_baseline(self):
        item = self.app["all_persistent_items"]()[0]
        tracker = self.app["tcp_state_tracker"]
        tracker.observe(item, True)
        self.payload["targets"][0]["name"] = "Device-01"
        self.restore()
        self.assertEqual(self.app["all_persistent_items"](), [item])
        self.assertEqual(tracker.observe(item, False).kind, "DOWN")

    def test_new_row_unknown_baseline(self):
        self.payload["targets"][0]["host"] = "192.0.2.20"
        self.restore()
        item = self.app["all_persistent_items"]()[-1]
        self.assertIsNone(self.app["tcp_state_tracker"].observe(item, False))

    def test_no_history_or_delivery_from_import(self):
        events = self.app["get_event_history_store"]()
        notifications = self.app["get_notification_history_store"]()
        now = datetime.now(timezone.utc)
        events.insert(self.app["EventRecord"](now.isoformat(), "DOWN", "Demo-PLC", "192.0.2.10", 443, "N/A", "ONLINE", "OFFLINE"))
        event = self.app["NotificationEvent"]("DOWN", now.isoformat(), "Demo-PLC", "192.0.2.10", 443, "N/A", "ONLINE", "OFFLINE")
        queued = notifications.insert_delivery(event, "generic_webhook")
        retrying = notifications.insert_delivery(event, "generic_webhook")
        failed = notifications.insert_delivery(event, "generic_webhook")
        notifications.schedule_retry(retrying, now + timedelta(days=1), "TIMEOUT", "Timed out")
        notifications.mark_failed(failed, "HTTP_CLIENT", "Delivery failed")
        retained_rows = [notifications.get(i) for i in (queued, retrying, failed)]
        before_events = events.health_summary()["row_count"]
        before_notifications = notifications.health_summary()
        with patch.object(self.app["notification_manager"], "enqueue") as enqueue:
            self.restore()
        enqueue.assert_not_called()
        self.assertEqual(events.health_summary()["row_count"], before_events)
        self.assertEqual(notifications.health_summary(), before_notifications)
        self.assertEqual([notifications.get(i) for i in (queued, retrying, failed)], retained_rows)

    def test_startup_registration_never_called(self):
        with patch.dict(self.app, enable_startup=unittest.mock.Mock(), disable_startup=unittest.mock.Mock()):
            self.payload["settings"]["start_hidden_on_windows_startup"] = True
            self.restore()
            self.app["enable_startup"].assert_not_called()
            self.app["disable_startup"].assert_not_called()

    def test_preferences_apply_live(self):
        self.payload["settings"].update(theme="dark", minimize_to_tray=True, close_to_tray=True)
        self.restore()
        self.assertEqual(self.app["current_theme"], "dark")
        self.assertTrue(self.app["minimize_to_tray_var"].get())
        self.assertTrue(self.app["close_to_tray_var"].get())

    def test_restored_config_reloads(self):
        self.payload["settings"]["theme"] = "dark"
        self.restore()
        restored = self.app["snapshot_config"]()
        self.app["apply_restored_config"](dict(self.defaults, hosts=[]))
        self.app["load_config"]()
        self.assertEqual(self.app["snapshot_config"](), restored)

    def test_legacy_config_generations_load(self):
        path = Path(self.app["get_config_path"]())
        for minor in (7, 8, 9, 10, 11):
            with self.subTest(version=f"1.{minor}"):
                legacy = dict(theme="light", hosts=[dict(host="192.0.2.10", port=443)])
                if minor >= 7:
                    legacy["generic_webhook_enabled"] = False
                if minor >= 8:
                    legacy["notification_retry_later_enabled"] = False
                if minor >= 10:
                    legacy["hosts"][0]["groups"] = ["Demo"]
                if minor >= 11:
                    legacy["start_hidden_on_windows_startup"] = False
                path.write_text(json.dumps(legacy))
                self.app["apply_restored_config"](dict(self.defaults, hosts=[]))
                self.app["load_config"]()
                self.assertEqual(len(self.app["configured_target_records"]()), 1)
                self.assertEqual(self.app["configured_target_records"]()[0]["host"], "192.0.2.10")

    def test_busy_check_rejected(self):
        with patch.dict(self.app, check_in_progress=True):
            with self.assertRaises(BackupError):
                self.restore()
        self.assertEqual(self.app["snapshot_config"](), self.current)

    def test_busy_scan_rejected(self):
        with patch.dict(self.app, scan_running=True):
            with self.assertRaises(BackupError):
                self.restore()

    def test_disk_failure_does_not_change_live_state(self):
        with patch.dict(self.app, save_restore=unittest.mock.Mock(side_effect=OSError)):
            with self.assertRaises(OSError):
                self.restore()
        self.assertEqual(self.app["snapshot_config"](), self.current)

    def test_ui_failure_rolls_back_disk_rows_and_tracker(self):
        path = Path(self.app["get_config_path"]())
        item = self.app["all_persistent_items"]()[0]
        self.app["tcp_state_tracker"].observe(item, True)
        original = self.app["apply_restored_config"]
        calls = 0
        def fail_once(config, **kwargs):
            nonlocal calls
            calls += 1
            original(config, **kwargs)
            if calls == 1:
                raise tk.TclError("simulated failure")
        self.payload["targets"] = []
        self.selection["mode"] = "replace"
        self.app["apply_restored_config"] = fail_once
        try:
            with self.assertRaisesRegex(BackupError, "previous settings restored"):
                self.restore()
        finally:
            self.app["apply_restored_config"] = original
        self.assertEqual(self.app["snapshot_config"](), self.current)
        self.assertEqual(json.loads(path.read_text()), self.current)
        self.assertEqual(self.app["tcp_state_tracker"].observe(item, False).kind, "DOWN")

    def test_backup_window_reused(self):
        window = self.app["open_settings_backup"]()
        try:
            self.assertIs(self.app["open_settings_backup"](), window)
            self.app["root"].update_idletasks()
        finally:
            window.close()

    def test_replace_removes_only_configured_targets(self):
        self.payload["targets"] = []
        self.selection["mode"] = "replace"
        self.restore()
        self.assertEqual(self.app["configured_target_records"](), [])

    def test_export_dialog_writes_portable_json(self):
        path = Path(self.directory.name) / "export.json"
        window = self.app["open_settings_backup"]()
        try:
            with patch.object(settings_backup_ui.filedialog, "asksaveasfilename", return_value=str(path)), patch.object(settings_backup_ui.messagebox, "showinfo") as info:
                window.export()
            self.assertEqual(json.loads(path.read_text())["format"], "MultiPortCheckerBackup")
            info.assert_called_once()
        finally:
            window.close()

    def test_preview_merge_and_confirmed_replace(self):
        path = Path(self.directory.name) / "preview.json"
        path.write_text(json.dumps(self.payload), encoding="utf-8")
        window = self.app["open_settings_backup"]()
        try:
            for replace in (False, True):
                with patch.object(settings_backup_ui.filedialog, "askopenfilename", return_value=str(path)):
                    window.preview()
                dialog = next(w for w in window.window.winfo_children() if isinstance(w, tk.Toplevel))
                if replace:
                    next(w for w in dialog.winfo_children() if isinstance(w, tk.Radiobutton) and w.cget("text") == "Replace").invoke()
                with patch.object(settings_backup_ui.messagebox, "askyesno", return_value=True) as confirm, patch.object(settings_backup_ui.messagebox, "showinfo") as info:
                    next(w for w in dialog.winfo_children() if w.winfo_class() == "TButton" and w.cget("text") == "Import").invoke()
                self.assertEqual(confirm.call_args.args[0], "Confirm Replace" if replace else "Confirm Import")
                info.assert_called_once()
                self.assertFalse(dialog.winfo_exists())
        finally:
            window.close()

    def test_invalid_and_future_preview_rejected(self):
        window = self.app["open_settings_backup"]()
        path = Path(self.directory.name) / "invalid.json"
        try:
            for value in ("{", json.dumps(dict(self.payload, backup_version=2))):
                path.write_text(value)
                with patch.object(settings_backup_ui.filedialog, "askopenfilename", return_value=str(path)), patch.object(settings_backup_ui.messagebox, "showerror") as error:
                    window.preview()
                error.assert_called_once()
        finally:
            window.close()

    def test_existing_windows_still_open_and_close(self):
        for name in ("open_application_settings", "open_health_diagnostics", "open_event_history", "open_availability_report", "open_notification_history", "open_notification_settings"):
            with self.subTest(window=name):
                window = self.app[name]()
                self.app["root"].update_idletasks()
                if window is not None:
                    window.close()


if __name__ == "__main__":
    unittest.main()
