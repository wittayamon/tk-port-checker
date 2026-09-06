import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from notification_history import STATUS_DELIVERED, STATUS_FAILED, STATUS_RETRYING, NotificationHistoryStore
from notification_manager import DELAYED_RETRY_DELAYS, NotificationManager, delayed_retry_seconds
from notification_models import (
    DeliveryResult, NotificationEvent, NotificationSettings,
    PROVIDER_GENERIC, PROVIDER_TEAMS, PROVIDER_WINDOWS,
    notification_settings_from_config,
)
from tests.test_webhook_notifications import LocalWebhookServer, RecordingHandler
from webhook_notifications import GenericWebhookProvider


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc)
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class FakeProvider:
    def __init__(self, key, results, endpoint_marker="", retryable=True):
        self.key = key
        self.display_name = key
        self.retryable = retryable
        self.results = list(results)
        self.calls = []
        self.endpoint_marker = endpoint_marker
    def deliver(self, event, timeout):
        self.calls.append((event, timeout, self.endpoint_marker))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


def result(success=False, category="NETWORK", retryable=True, delayed=True, summary=None):
    return DeliveryResult(
        PROVIDER_GENERIC, success, "Delivered" if success else "Failed",
        retryable=retryable, error_category=None if success else category,
        safe_summary=None if success else (summary or "Network connection failed"),
        delayed_retryable=delayed,
    )


def event(kind="DOWN", seconds=0, name="Demo-PLC"):
    return NotificationEvent(
        kind, (datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat(),
        name, "192.0.2.10", 443, "Timeout",
        "ONLINE" if kind == "DOWN" else "OFFLINE",
        "OFFLINE" if kind == "DOWN" else "ONLINE",
        60 if kind == "RECOVERED" else None,
    )


class NotificationRetryQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = NotificationHistoryStore(os.path.join(self.temp.name, "events.db"))
        self.clock = Clock()
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.shutdown(2)

    def manager(self, provider, *, retry_later=False, retries=2, delayed=(300, 900, 3600)):
        manager = NotificationManager(
            history_store=self.store, retry_delays=(0, 0),
            delayed_retry_delays=delayed, clock=self.clock, scheduler_interval=999,
        )
        self.managers.append(manager)
        settings = NotificationSettings(
            generic_webhook_enabled=provider.key == PROVIDER_GENERIC,
            teams_webhook_enabled=provider.key == PROVIDER_TEAMS,
            windows_notifications_enabled=provider.key == PROVIDER_WINDOWS,
            retry_count=retries, retry_later_enabled=retry_later,
        )
        manager.configure(settings, {provider.key: provider})
        return manager

    def only(self):
        rows = self.store.list_deliveries()
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_disabled_provider_creates_no_row(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(True)])
        manager = NotificationManager(history_store=self.store, retry_delays=(0, 0))
        self.managers.append(manager)
        manager.configure(NotificationSettings(), {PROVIDER_GENERIC: provider})
        self.assertEqual(manager.enqueue(event()), 0)
        self.assertEqual(self.store.list_deliveries(), [])

    def test_successful_initial_delivery(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(True)])
        manager = self.manager(provider)
        manager.enqueue(event()); self.assertTrue(manager.wait_until_idle())
        self.assertEqual(self.only().status, STATUS_DELIVERED)

    def test_immediate_retries_increment_attempt_count(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(), result(), result(True)])
        manager = self.manager(provider)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().attempt_count, 3)

    def test_exhausted_retry_with_retry_later_disabled_fails(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_FAILED)

    def test_exhausted_retry_with_retry_later_enabled_schedules(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        row = self.only()
        self.assertEqual(row.status, STATUS_RETRYING)
        self.assertIsNotNone(row.next_retry_at)

    def _assert_permanent(self, code):
        provider = FakeProvider(PROVIDER_GENERIC, [result(category="HTTP_4XX", delayed=False, summary=f"HTTP {code}")])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_FAILED)

    def test_http_400_is_not_delayed(self): self._assert_permanent(400)
    def test_http_401_is_not_delayed(self): self._assert_permanent(401)
    def test_http_403_is_not_delayed(self): self._assert_permanent(403)
    def test_http_404_is_not_delayed(self): self._assert_permanent(404)

    def test_http_429_is_delayed(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(category="HTTP_429")])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_RETRYING)

    def test_http_500_is_delayed(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(category="HTTP_5XX")])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_RETRYING)

    def test_timeout_is_delayed(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(category="TIMEOUT")])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_RETRYING)

    def test_network_failure_is_delayed(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(category="NETWORK")])
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_RETRYING)

    def test_schedule_constants_are_5_15_60_minutes(self):
        self.assertEqual(DELAYED_RETRY_DELAYS, (300, 900, 3600))

    def test_retry_after_is_bounded_and_not_shorter_than_schedule(self):
        self.assertEqual(delayed_retry_seconds(0, 10), 300)
        self.assertEqual(delayed_retry_seconds(0, 99999), 3600)

    def test_delayed_success_becomes_delivered(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(), result(), result(), result(True)])
        manager = self.manager(provider, retry_later=True, retries=2)
        manager.enqueue(event()); manager.wait_until_idle()
        self.clock.advance(300)
        self.assertEqual(manager.process_due_retries(), 1)
        manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_DELIVERED)

    def test_delayed_retry_maximum_is_three_cycles(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True, retries=0, delayed=(1, 1, 1))
        manager.enqueue(event()); manager.wait_until_idle()
        for _ in range(3):
            self.clock.advance(1); manager.process_due_retries(); manager.wait_until_idle()
        row = self.only()
        self.assertEqual((row.status, row.delayed_retry_count), (STATUS_FAILED, 3))

    def test_restart_loads_due_retry_and_uses_current_provider(self):
        old = FakeProvider(PROVIDER_GENERIC, [result()], endpoint_marker="old")
        first = self.manager(old, retry_later=True, retries=0)
        first.enqueue(event()); first.wait_until_idle(); first.shutdown(2)
        new = FakeProvider(PROVIDER_GENERIC, [result(True)], endpoint_marker="current")
        second = self.manager(new, retry_later=True, retries=0)
        self.clock.advance(300)
        second.process_due_retries(); second.wait_until_idle()
        self.assertEqual(new.calls[0][2], "current")
        self.assertEqual(self.only().status, STATUS_DELIVERED)

    def test_restart_does_not_load_future_retry_early(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True, retries=0)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(manager.process_due_retries(), 0)

    def test_duplicate_due_job_is_not_queued_twice(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True, retries=0)
        manager.enqueue(event()); manager.wait_until_idle(); self.clock.advance(300)
        self.assertEqual(manager.process_due_retries(), 1)
        self.assertEqual(manager.process_due_retries(), 0)

    def test_manual_retry_failed_row(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(), result(True)])
        manager = self.manager(provider, retries=0)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertTrue(manager.retry_selected(self.only().id)); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_DELIVERED)

    def test_manual_retry_disabled_provider_is_blocked(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retries=0)
        manager.enqueue(event()); manager.wait_until_idle()
        manager.configure(NotificationSettings(), {PROVIDER_GENERIC: provider})
        self.assertFalse(manager.retry_selected(self.only().id))

    def test_retry_all_failed(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(), result(), result(True)])
        manager = self.manager(provider, retries=0)
        manager.enqueue(event()); manager.wait_until_idle()
        manager.enqueue(event(seconds=1)); manager.wait_until_idle()
        self.assertEqual(manager.retry_all_failed(), 2); manager.wait_until_idle()
        self.assertTrue(all(row.status == STATUS_DELIVERED for row in self.store.list_deliveries()))

    def test_windows_delivery_is_stored_without_delayed_retry(self):
        failure = DeliveryResult(PROVIDER_WINDOWS, False, "Unavailable", retryable=False,
                                 error_category="WINDOWS_NOTIFICATION",
                                 safe_summary="Windows notification is unavailable")
        provider = FakeProvider(PROVIDER_WINDOWS, [failure], retryable=False)
        manager = self.manager(provider, retry_later=True)
        manager.enqueue(event()); manager.wait_until_idle()
        self.assertEqual(self.only().status, STATUS_FAILED)

    def test_test_notification_creates_no_delivery_row(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result(True)])
        manager = self.manager(provider)
        manager.enqueue_test(provider, retries=0); manager.wait_until_idle()
        self.assertEqual(self.store.list_deliveries(), [])

    def test_down_and_recovered_are_independent_rows(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True, retries=0)
        manager.enqueue(event("DOWN")); manager.wait_until_idle()
        manager.enqueue(event("RECOVERED", seconds=30)); manager.wait_until_idle()
        self.assertEqual({row.event_type for row in self.store.list_deliveries()}, {"DOWN", "RECOVERED"})

    def test_safe_summary_not_raw_message_is_persisted(self):
        unsafe = DeliveryResult(PROVIDER_GENERIC, False,
                                "POST https://example.invalid/secret-token failed",
                                retryable=False, error_category="HTTP_4XX",
                                safe_summary="HTTP 401", delayed_retryable=False)
        provider = FakeProvider(PROVIDER_GENERIC, [unsafe])
        manager = self.manager(provider, retries=0)
        manager.enqueue(event()); manager.wait_until_idle()
        row = self.only()
        self.assertEqual(row.last_error_summary, "HTTP 401")
        with open(self.store.path, "rb") as database_file:
            self.assertNotIn("secret-token", database_file.read().decode("latin1"))

    def test_v17_config_defaults_retry_later_false(self):
        self.assertFalse(notification_settings_from_config({"notification_retry_count": 2}).retry_later_enabled)

    def test_malformed_retry_later_setting_is_safe(self):
        self.assertFalse(notification_settings_from_config({"notification_retry_later_enabled": "yes"}).retry_later_enabled)

    def test_shutdown_preserves_retryable_active_state(self):
        provider = FakeProvider(PROVIDER_GENERIC, [result()])
        manager = self.manager(provider, retry_later=True, retries=0)
        manager.enqueue(event()); manager.wait_until_idle(); manager.shutdown(2)
        self.assertEqual(self.only().status, STATUS_RETRYING)

    def test_localhost_outage_restart_and_eventual_success(self):
        with LocalWebhookServer() as server:
            RecordingHandler.statuses = [500]
            provider = GenericWebhookProvider(server.url)
            first = self.manager(provider, retry_later=True, retries=0)
            first.enqueue(event("DOWN")); first.wait_until_idle()
            self.assertEqual(self.only().status, STATUS_RETRYING)
            first.shutdown(2)

            RecordingHandler.statuses = [204]
            second = self.manager(GenericWebhookProvider(server.url), retry_later=True, retries=0)
            self.clock.advance(300)
            second.process_due_retries(); second.wait_until_idle()
            self.assertEqual(self.only().status, STATUS_DELIVERED)
        self.assertEqual(len(RecordingHandler.requests), 2)


if __name__ == "__main__":
    unittest.main()
