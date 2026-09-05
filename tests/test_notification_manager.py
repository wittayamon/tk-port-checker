import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from event_history import EventHistoryStore
from monitoring_state import TcpStateTracker
from notification_manager import NotificationManager
from notification_models import (
    DeliveryResult,
    NotificationEvent,
    NotificationSettings,
    PROVIDER_GENERIC,
    PROVIDER_TEAMS,
    PROVIDER_WINDOWS,
    notification_settings_from_config,
)


class FakeProvider:
    def __init__(self, key, results=None, *, retryable=False, raises=False):
        self.key = key
        self.display_name = key
        self.retryable = retryable
        self.results = list(results or [True])
        self.raises = raises
        self.events = []

    def deliver(self, event, timeout):
        self.events.append((event, timeout))
        if self.raises:
            raise RuntimeError("provider failed")
        success = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return DeliveryResult(
            self.key,
            success,
            "delivered" if success else "delivery failed",
            retryable=self.retryable,
            test_only=event.test_only,
        )


def down_event(name="Demo-PLC"):
    return NotificationEvent(
        "DOWN",
        "2026-09-05T20:30:00+07:00",
        name,
        "192.0.2.10",
        102,
        "Timeout",
        "ONLINE",
        "OFFLINE",
    )


class NotificationSettingsCompatibilityTests(unittest.TestCase):
    def test_v16_config_defaults_all_new_providers_to_disabled(self):
        settings = notification_settings_from_config({"theme": "dark", "hosts": []})
        self.assertFalse(settings.windows_notifications_enabled)
        self.assertFalse(settings.generic_webhook_enabled)
        self.assertFalse(settings.teams_webhook_enabled)
        self.assertEqual(settings.timeout_seconds, 5)
        self.assertEqual(settings.retry_count, 2)

    def test_explicit_settings_round_trip(self):
        original = NotificationSettings(
            True, True, "https://example.invalid/generic", True,
            "https://example.invalid/teams", 8, 3
        )
        self.assertEqual(notification_settings_from_config(original.to_config()), original)

    def test_malformed_timeout_retry_and_booleans_use_safe_defaults(self):
        settings = notification_settings_from_config(
            {
                "windows_notifications_enabled": "yes",
                "generic_webhook_enabled": 1,
                "notification_timeout_seconds": 99,
                "notification_retry_count": -1,
            }
        )
        self.assertEqual(settings, NotificationSettings())


class NotificationTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = TcpStateTracker()
        self.start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    def observe(self, online, *, persistent=True, seconds=0):
        return self.tracker.observe(
            "target", online, persistent=persistent,
            now=self.start + timedelta(seconds=seconds)
        )

    def test_unknown_online_and_unknown_offline_do_not_make_notification_events(self):
        self.assertIsNone(self.observe(True))
        other = TcpStateTracker()
        self.assertIsNone(other.observe("target", False, now=self.start))

    def test_down_is_single_and_repeated_offline_is_suppressed(self):
        self.observe(True)
        change = self.observe(False, seconds=1)
        event = NotificationEvent.from_state_change(
            change, device_name="Demo-PLC", host="192.0.2.10", port=102,
            ping="Timeout"
        )
        self.assertEqual(event.event_type, "DOWN")
        self.assertIsNone(self.observe(False, seconds=2))

    def test_recovery_includes_downtime(self):
        self.observe(True)
        self.observe(False, seconds=5)
        change = self.observe(True, seconds=80)
        event = NotificationEvent.from_state_change(
            change, device_name="", host="192.0.2.10", port=102, ping="2 ms"
        )
        self.assertEqual(event.event_type, "RECOVERED")
        self.assertEqual(event.downtime_seconds, 75)
        self.assertEqual(event.downtime_display, "1m 15s")
        self.assertEqual(event.identifier, "192.0.2.10")

    def test_ping_only_and_transient_scan_results_do_not_create_transition(self):
        self.observe(True)
        self.assertIsNone(self.observe(True, seconds=2))
        transient = TcpStateTracker()
        self.assertIsNone(
            transient.observe("scan", False, persistent=False, now=self.start)
        )


class NotificationManagerTests(unittest.TestCase):
    def make_manager(self, results=None):
        manager = NotificationManager(
            None if results is None else results.append,
            retry_delays=(0, 0),
        )
        self.addCleanup(manager.shutdown)
        return manager

    def test_disabled_provider_receives_nothing(self):
        provider = FakeProvider(PROVIDER_WINDOWS)
        manager = self.make_manager()
        manager.configure(NotificationSettings(), {PROVIDER_WINDOWS: provider})
        self.assertEqual(manager.enqueue(down_event()), 0)
        self.assertEqual(provider.events, [])

    def test_enabled_provider_receives_event_while_ui_can_be_hidden(self):
        provider = FakeProvider(PROVIDER_WINDOWS)
        manager = self.make_manager()
        manager.configure(
            NotificationSettings(windows_notifications_enabled=True),
            {PROVIDER_WINDOWS: provider},
        )
        self.assertEqual(manager.enqueue(down_event()), 1)
        self.assertTrue(manager.wait_until_idle())
        self.assertEqual(provider.events[0][0].event_type, "DOWN")

    def test_one_failing_provider_does_not_block_another(self):
        failed = FakeProvider(PROVIDER_WINDOWS, raises=True)
        working = FakeProvider(PROVIDER_GENERIC)
        manager = self.make_manager()
        manager.configure(
            NotificationSettings(
                windows_notifications_enabled=True,
                generic_webhook_enabled=True,
            ),
            {PROVIDER_WINDOWS: failed, PROVIDER_GENERIC: working},
        )
        self.assertEqual(manager.enqueue(down_event()), 2)
        self.assertTrue(manager.wait_until_idle())
        self.assertEqual(len(failed.events), 1)
        self.assertEqual(len(working.events), 1)

    def test_retry_count_means_retries_after_initial_attempt(self):
        provider = FakeProvider(
            PROVIDER_GENERIC, [False, False, True], retryable=True
        )
        manager = self.make_manager()
        manager.configure(
            NotificationSettings(generic_webhook_enabled=True, retry_count=2),
            {PROVIDER_GENERIC: provider},
        )
        manager.enqueue(down_event())
        self.assertTrue(manager.wait_until_idle())
        self.assertEqual(len(provider.events), 3)

    def test_retry_stops_at_configured_limit(self):
        provider = FakeProvider(PROVIDER_GENERIC, [False], retryable=True)
        manager = self.make_manager()
        manager.configure(
            NotificationSettings(generic_webhook_enabled=True, retry_count=1),
            {PROVIDER_GENERIC: provider},
        )
        manager.enqueue(down_event())
        self.assertTrue(manager.wait_until_idle())
        self.assertEqual(len(provider.events), 2)

    def test_test_notification_does_not_touch_tracker_or_history(self):
        provider = FakeProvider(PROVIDER_WINDOWS)
        manager = self.make_manager()
        tracker = TcpStateTracker()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = EventHistoryStore(f"{temp_dir}/events.db")
            self.assertTrue(manager.enqueue_test(provider, retries=0))
            self.assertTrue(manager.wait_until_idle())
            self.assertEqual(store.list_events(), [])
        self.assertTrue(provider.events[0][0].test_only)
        self.assertIsNone(tracker.observe("target", True, now=self.start_time()))

    @staticmethod
    def start_time():
        return datetime(2026, 9, 5, tzinfo=timezone.utc)

    def test_shutdown_stops_worker_and_is_idempotent(self):
        manager = NotificationManager(retry_delays=(0, 0))
        self.assertTrue(manager.shutdown(timeout=2))
        self.assertFalse(manager.worker_alive)
        self.assertFalse(manager.shutdown())
        self.assertEqual(manager.enqueue(down_event()), 0)


if __name__ == "__main__":
    unittest.main()
