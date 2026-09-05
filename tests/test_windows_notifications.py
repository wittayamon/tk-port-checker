import unittest

from notification_models import NotificationEvent
from windows_notifications import (
    WindowsNotificationProvider,
    windows_notification_content,
)


def event(kind="DOWN"):
    recovered = kind == "RECOVERED"
    return NotificationEvent(
        kind,
        "2026-09-05T20:30:00+07:00",
        "Demo-PLC",
        "192.0.2.10",
        102,
        "2 ms" if recovered else "Timeout",
        "OFFLINE" if recovered else "ONLINE",
        "ONLINE" if recovered else "OFFLINE",
        155 if recovered else None,
        "2m 35s" if recovered else "-",
    )


class WindowsNotificationContentTests(unittest.TestCase):
    def test_down_content(self):
        title, body, warning = windows_notification_content(event())
        self.assertIn("Device Down", title)
        self.assertIn("Demo-PLC", body)
        self.assertIn("192.0.2.10:102", body)
        self.assertIn("OFFLINE", body)
        self.assertTrue(warning)

    def test_recovered_content_includes_downtime(self):
        title, body, warning = windows_notification_content(event("RECOVERED"))
        self.assertIn("Device Recovered", title)
        self.assertIn("2m 35s", body)
        self.assertFalse(warning)

    def test_test_content_is_obviously_test_only(self):
        title, body, warning = windows_notification_content(
            NotificationEvent.test_notification()
        )
        self.assertIn("Test Notification", title)
        self.assertIn("TEST", body)
        self.assertFalse(warning)


class WindowsNotificationProviderTests(unittest.TestCase):
    def test_provider_queues_native_notification(self):
        calls = []
        provider = WindowsNotificationProvider(
            lambda title, body, warning: calls.append(
                (title, body, warning)
            ) or True
        )
        result = provider.deliver(event(), 5)
        self.assertTrue(result.success)
        self.assertEqual(len(calls), 1)

    def test_provider_failure_is_contained(self):
        provider = WindowsNotificationProvider(
            lambda _title, _body, _warning: (_ for _ in ()).throw(
                RuntimeError("native failure")
            )
        )
        result = provider.deliver(event(), 5)
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)


if __name__ == "__main__":
    unittest.main()
