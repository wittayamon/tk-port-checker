"""Native Windows notification provider backed by the existing tray icon."""

from typing import Callable

from notification_models import DeliveryResult, NotificationEvent, PROVIDER_WINDOWS


def windows_notification_content(event: NotificationEvent) -> tuple[str, str, bool]:
    if event.event_type == "DOWN":
        return (
            "MultiPortChecker — Device Down",
            f"{event.identifier}\n{event.host}:{event.port}\nTCP service is OFFLINE",
            True,
        )
    if event.event_type == "RECOVERED":
        return (
            "MultiPortChecker — Device Recovered",
            f"{event.identifier}\n{event.host}:{event.port}\n"
            f"Recovered after {event.downtime_display}",
            False,
        )
    return (
        "MultiPortChecker Test Notification",
        "Demo-Device\nStatus: TEST\nThis is a test notification.",
        False,
    )


class WindowsNotificationProvider:
    """Adapter that queues through the existing tray message-loop boundary."""
    key = PROVIDER_WINDOWS
    display_name = "Windows Notification"
    retryable = False

    def __init__(self, notify: Callable[[str, str, bool], bool]):
        self._notify = notify

    def deliver(self, event: NotificationEvent, timeout: int) -> DeliveryResult:
        del timeout
        title, message, warning = windows_notification_content(event)
        try:
            accepted = self._notify(title, message, warning)
        except Exception:
            accepted = False
        return DeliveryResult(
            self.key,
            bool(accepted),
            (
                "Windows notification queued successfully."
                if accepted
                else "Windows notification is unavailable."
            ),
            retryable=False,
            test_only=event.test_only,
            error_category=None if accepted else "WINDOWS_NOTIFICATION",
            safe_summary=None if accepted else "Windows notification is unavailable",
        )
