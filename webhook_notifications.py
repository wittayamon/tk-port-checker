"""Dependency-free Generic and Microsoft Teams-compatible webhook providers."""

import json
import socket
import ssl
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib import error, parse, request

from notification_models import (
    APP_VERSION,
    DeliveryResult,
    NotificationEvent,
    PROVIDER_GENERIC,
    PROVIDER_TEAMS,
)


def endpoint_is_valid(endpoint: str) -> bool:
    try:
        parsed = parse.urlsplit(str(endpoint or "").strip())
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and bool(parsed.netloc)
        and bool(parsed.hostname)
    )


def redact_url(endpoint: str) -> str:
    """Return a diagnostic-safe endpoint description without path/query secrets."""
    try:
        parsed = parse.urlsplit(str(endpoint or "").strip())
    except ValueError:
        return "configured endpoint"
    if parsed.scheme in ("http", "https") and parsed.hostname:
        try:
            parsed_port = parsed.port
        except ValueError:
            return "configured endpoint"
        port = f":{parsed_port}" if parsed_port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}/…"
    return "configured endpoint"


def generic_webhook_payload(event: NotificationEvent) -> dict:
    return {
        "source": "MultiPortChecker",
        "event": event.event_type,
        "timestamp": event.timestamp,
        "device": event.identifier,
        "host": event.host,
        "port": event.port,
        "ping": event.ping,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "downtime_seconds": event.downtime_seconds,
    }


def teams_webhook_payload(event: NotificationEvent) -> dict:
    if event.event_type == "DOWN":
        heading = "Device Down"
    elif event.event_type == "RECOVERED":
        heading = "Device Recovered"
    else:
        heading = "Test Notification"
    facts = [
        {"title": "Device", "value": event.identifier},
        {"title": "Host", "value": event.host},
        {"title": "Port", "value": str(event.port)},
        {"title": "Ping", "value": event.ping},
        {"title": "Time", "value": event.timestamp},
    ]
    if event.event_type == "RECOVERED":
        facts.insert(4, {"title": "Downtime", "value": event.downtime_display})
    if event.test_only:
        facts.append({"title": "Status", "value": "TEST"})
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "MultiPortChecker",
                            "weight": "Bolder",
                            "size": "Medium",
                        },
                        {"type": "TextBlock", "text": heading, "wrap": True},
                        {"type": "FactSet", "facts": facts},
                    ],
                },
            }
        ],
    }


class HttpWebhookProvider:
    retryable = True

    def __init__(self, key: str, display_name: str, endpoint: str, payload_builder):
        self.key = key
        self.display_name = display_name
        self.endpoint = str(endpoint or "").strip()
        self._payload_builder = payload_builder

    def deliver(self, event: NotificationEvent, timeout: int) -> DeliveryResult:
        if not endpoint_is_valid(self.endpoint):
            return DeliveryResult(
                self.key,
                False,
                f"{self.display_name} requires a valid HTTP(S) endpoint.",
                retryable=False,
                test_only=event.test_only,
                error_category="PROVIDER_DISABLED",
                safe_summary="Provider endpoint is invalid",
            )
        body = json.dumps(
            self._payload_builder(event), ensure_ascii=False
        ).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": f"MultiPortChecker/{APP_VERSION}",
            },
        )
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                status = int(response.getcode())
            if 200 <= status < 300:
                return DeliveryResult(
                    self.key,
                    True,
                    f"{self.display_name} delivered successfully (HTTP {status}).",
                    test_only=event.test_only,
                )
            return self._http_failure(status, event)
        except error.HTTPError as exc:
            retry_after = _bounded_retry_after(exc.headers.get("Retry-After")) if exc.code == 429 else None
            return self._http_failure(exc.code, event, retry_after)
        except (TimeoutError, socket.timeout):
            return DeliveryResult(
                self.key,
                False,
                f"{self.display_name} delivery timed out.",
                retryable=True,
                test_only=event.test_only,
                error_category="TIMEOUT",
                safe_summary="Request timed out",
            )
        except ssl.SSLError:
            return DeliveryResult(
                self.key,
                False,
                f"{self.display_name} delivery failed due to TLS validation.",
                retryable=True,
                test_only=event.test_only,
                error_category="SSL",
                safe_summary="TLS connection failed",
            )
        except error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                category, summary, message = "TIMEOUT", "Request timed out", "delivery timed out"
            elif isinstance(reason, ssl.SSLError):
                category, summary, message = "SSL", "TLS connection failed", "delivery failed due to TLS validation"
            else:
                category, summary, message = "NETWORK", "Network connection failed", "delivery failed due to a network error"
            return DeliveryResult(
                self.key, False, f"{self.display_name} {message}.", retryable=True,
                test_only=event.test_only, error_category=category,
                safe_summary=summary, delayed_retryable=True,
            )
        except (OSError, ValueError):
            return DeliveryResult(
                self.key,
                False,
                f"{self.display_name} delivery failed due to a network error.",
                retryable=True,
                test_only=event.test_only,
                error_category="NETWORK",
                safe_summary="Network connection failed",
                delayed_retryable=True,
            )

    def _http_failure(self, status: int, event: NotificationEvent,
                      retry_after: int = None) -> DeliveryResult:
        status = int(status)
        retryable = status == 429 or 500 <= status <= 599
        category = "HTTP_429" if status == 429 else (
            "HTTP_5XX" if 500 <= status <= 599 else "HTTP_4XX"
        )
        return DeliveryResult(
            self.key,
            False,
            f"{self.display_name} delivery failed: HTTP {status}.",
            # Preserve v1.7 immediate retries for HTTP failures; the separate
            # delayed flag prevents permanent 4xx responses entering the queue.
            retryable=True,
            test_only=event.test_only,
            error_category=category,
            safe_summary=f"HTTP {status}",
            http_status=status,
            retry_after_seconds=retry_after,
            delayed_retryable=retryable,
        )


def _bounded_retry_after(value, *, now=None, maximum=3600):
    """Parse Retry-After seconds/date and cap untrusted delays at one hour."""
    if value is None:
        return None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(value).strip())
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            seconds = int((target - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, min(int(maximum), seconds))


class GenericWebhookProvider(HttpWebhookProvider):
    def __init__(self, endpoint: str):
        super().__init__(
            PROVIDER_GENERIC,
            "Generic Webhook",
            endpoint,
            generic_webhook_payload,
        )


class TeamsWebhookProvider(HttpWebhookProvider):
    def __init__(self, endpoint: str):
        super().__init__(
            PROVIDER_TEAMS,
            "Microsoft Teams",
            endpoint,
            teams_webhook_payload,
        )
