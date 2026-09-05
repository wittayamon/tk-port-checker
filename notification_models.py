"""UI-independent notification event and configuration models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

from monitoring_state import StateChangeEvent, format_duration


APP_VERSION = "1.7.0"
PROVIDER_WINDOWS = "windows"
PROVIDER_GENERIC = "generic_webhook"
PROVIDER_TEAMS = "teams_webhook"


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    success: bool
    message: str
    retryable: bool = False
    test_only: bool = False


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    timestamp: str
    device_name: str
    host: str
    port: int
    ping: str
    previous_status: str
    new_status: str
    downtime_seconds: Optional[float] = None
    downtime_display: str = "-"
    test_only: bool = False

    @property
    def identifier(self) -> str:
        return self.device_name or self.host

    @classmethod
    def from_state_change(
        cls,
        state_change: StateChangeEvent,
        *,
        device_name: str,
        host: str,
        port: int,
        ping: str,
    ) -> "NotificationEvent":
        downtime = state_change.downtime_seconds
        return cls(
            event_type=state_change.kind,
            timestamp=state_change.occurred_at.isoformat(),
            device_name=str(device_name or "").strip(),
            host=str(host),
            port=int(port),
            ping=str(ping),
            previous_status=state_change.previous_status,
            new_status=state_change.new_status,
            downtime_seconds=downtime,
            downtime_display=(format_duration(downtime) if downtime is not None else "-"),
        )

    @classmethod
    def test_notification(cls) -> "NotificationEvent":
        return cls(
            event_type="TEST",
            timestamp=datetime.now().astimezone().isoformat(),
            device_name="Demo-Device",
            host="192.0.2.10",
            port=443,
            ping="N/A",
            previous_status="TEST",
            new_status="TEST",
            test_only=True,
        )


@dataclass(frozen=True)
class NotificationSettings:
    windows_notifications_enabled: bool = False
    generic_webhook_enabled: bool = False
    generic_webhook_url: str = ""
    teams_webhook_enabled: bool = False
    teams_webhook_url: str = ""
    timeout_seconds: int = 5
    retry_count: int = 2

    def to_config(self) -> dict:
        return {
            "windows_notifications_enabled": self.windows_notifications_enabled,
            "generic_webhook_enabled": self.generic_webhook_enabled,
            "generic_webhook_url": self.generic_webhook_url,
            "teams_webhook_enabled": self.teams_webhook_enabled,
            "teams_webhook_url": self.teams_webhook_url,
            "notification_timeout_seconds": self.timeout_seconds,
            "notification_retry_count": self.retry_count,
        }

    def enabled_providers(self) -> tuple[str, ...]:
        providers = []
        if self.windows_notifications_enabled:
            providers.append(PROVIDER_WINDOWS)
        if self.generic_webhook_enabled:
            providers.append(PROVIDER_GENERIC)
        if self.teams_webhook_enabled:
            providers.append(PROVIDER_TEAMS)
        return tuple(providers)


def _optional_bool(config: Mapping, key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    return value if isinstance(value, bool) else default


def _bounded_int(config: Mapping, key: str, default: int, minimum: int, maximum: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


def notification_settings_from_config(config: Mapping) -> NotificationSettings:
    """Read v1.7 settings while safely accepting v1.6 or malformed config."""
    if not isinstance(config, Mapping):
        return NotificationSettings()
    return NotificationSettings(
        windows_notifications_enabled=_optional_bool(
            config, "windows_notifications_enabled"
        ),
        generic_webhook_enabled=_optional_bool(config, "generic_webhook_enabled"),
        generic_webhook_url=str(config.get("generic_webhook_url", "") or "").strip(),
        teams_webhook_enabled=_optional_bool(config, "teams_webhook_enabled"),
        teams_webhook_url=str(config.get("teams_webhook_url", "") or "").strip(),
        timeout_seconds=_bounded_int(
            config, "notification_timeout_seconds", 5, 1, 30
        ),
        retry_count=_bounded_int(config, "notification_retry_count", 2, 0, 5),
    )
