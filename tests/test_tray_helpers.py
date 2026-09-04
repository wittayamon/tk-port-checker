import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from windows_tray import (
    ShutdownGuard,
    TRAY_ACTION_CHECK_ALL,
    TRAY_ACTION_EVENT_HISTORY,
    TRAY_ACTION_EXIT,
    TRAY_ACTION_OPEN,
    TRAY_ACTION_START_AUTO,
    TRAY_ACTION_STOP_AUTO,
    TRAY_MENU_ACTIONS,
    WindowsTrayIcon,
    should_close_to_tray,
    tray_icon_relative_path,
    tray_menu_state,
    tray_preferences_from_config,
)


class TrayPreferenceTests(unittest.TestCase):
    def test_old_config_uses_safe_defaults(self):
        preferences = tray_preferences_from_config({"hosts": []})
        self.assertFalse(preferences.minimize_to_tray)
        self.assertTrue(preferences.close_to_tray)

    def test_explicit_tray_settings_load(self):
        preferences = tray_preferences_from_config(
            {"minimize_to_tray": True, "close_to_tray": False}
        )
        self.assertTrue(preferences.minimize_to_tray)
        self.assertFalse(preferences.close_to_tray)

    def test_tray_preferences_are_persistence_ready(self):
        preferences = tray_preferences_from_config(
            {"minimize_to_tray": True, "close_to_tray": True}
        )
        self.assertEqual(
            asdict(preferences),
            {"minimize_to_tray": True, "close_to_tray": True},
        )

    def test_malformed_optional_settings_fall_back_independently(self):
        preferences = tray_preferences_from_config(
            {"minimize_to_tray": "yes", "close_to_tray": 0}
        )
        self.assertFalse(preferences.minimize_to_tray)
        self.assertTrue(preferences.close_to_tray)

    def test_non_mapping_config_uses_defaults(self):
        preferences = tray_preferences_from_config(None)
        self.assertFalse(preferences.minimize_to_tray)
        self.assertTrue(preferences.close_to_tray)


class TrayDecisionTests(unittest.TestCase):
    def test_close_to_tray_requires_preference_and_available_icon(self):
        self.assertTrue(should_close_to_tray(True, True))
        self.assertFalse(should_close_to_tray(False, True))
        self.assertFalse(should_close_to_tray(True, False))

    def test_real_exit_never_hides_to_tray(self):
        self.assertFalse(should_close_to_tray(True, True, real_exit=True))

    def test_shutdown_guard_allows_only_one_shutdown(self):
        guard = ShutdownGuard()
        self.assertTrue(guard.begin())
        self.assertFalse(guard.begin())
        self.assertTrue(guard.started)

    def test_auto_refresh_menu_state_is_mutually_exclusive(self):
        stopped = tray_menu_state(False)
        running = tray_menu_state(True)
        self.assertTrue(stopped[TRAY_ACTION_START_AUTO])
        self.assertFalse(stopped[TRAY_ACTION_STOP_AUTO])
        self.assertFalse(running[TRAY_ACTION_START_AUTO])
        self.assertTrue(running[TRAY_ACTION_STOP_AUTO])

    def test_tray_command_ids_cover_every_action(self):
        self.assertEqual(
            set(TRAY_MENU_ACTIONS.values()),
            {
                TRAY_ACTION_OPEN,
                TRAY_ACTION_CHECK_ALL,
                TRAY_ACTION_START_AUTO,
                TRAY_ACTION_STOP_AUTO,
                TRAY_ACTION_EVENT_HISTORY,
                TRAY_ACTION_EXIT,
            },
        )

    def test_icon_path_uses_shared_application_asset(self):
        self.assertEqual(
            tray_icon_relative_path(),
            os.path.join("assets", "icon_network_transparent.ico"),
        )

    def test_non_windows_backend_fails_safely(self):
        tray = WindowsTrayIcon("missing.ico", lambda _action: None)
        with patch("windows_tray.sys.platform", "linux"):
            self.assertFalse(tray.start())
        self.assertFalse(tray.running)
        tray.stop()


if __name__ == "__main__":
    unittest.main()
