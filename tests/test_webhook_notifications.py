import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from notification_manager import NotificationManager
from notification_models import NotificationEvent, NotificationSettings, PROVIDER_GENERIC
from webhook_notifications import (
    GenericWebhookProvider,
    TeamsWebhookProvider,
    endpoint_is_valid,
    generic_webhook_payload,
    redact_url,
    teams_webhook_payload,
)


def event(kind="DOWN", name="อุปกรณ์ทดสอบ"):
    recovered = kind == "RECOVERED"
    return NotificationEvent(
        kind,
        "2026-09-05T20:30:00+07:00",
        name,
        "192.0.2.10",
        102,
        "2 ms" if recovered else "Timeout",
        "OFFLINE" if recovered else "ONLINE",
        "ONLINE" if recovered else "OFFLINE",
        155 if recovered else None,
        "2m 35s" if recovered else "-",
    )


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []
    statuses = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append((self.headers, body))
        status = type(self).statuses.pop(0) if type(self).statuses else 200
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, _format, *args):
        del args


class LocalWebhookServer:
    def __enter__(self):
        RecordingHandler.requests = []
        RecordingHandler.statuses = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/notification"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class WebhookPayloadTests(unittest.TestCase):
    def test_generic_payload_contains_transition_and_unicode(self):
        payload = generic_webhook_payload(event())
        self.assertEqual(payload["source"], "MultiPortChecker")
        self.assertEqual(payload["event"], "DOWN")
        self.assertEqual(payload["device"], "อุปกรณ์ทดสอบ")
        self.assertEqual(payload["new_status"], "OFFLINE")
        self.assertIsNone(payload["downtime_seconds"])

    def test_recovered_payload_contains_downtime(self):
        payload = generic_webhook_payload(event("RECOVERED"))
        self.assertEqual(payload["event"], "RECOVERED")
        self.assertEqual(payload["downtime_seconds"], 155)

    def test_teams_payload_is_adaptive_card_with_visible_fields(self):
        payload = teams_webhook_payload(event("RECOVERED", "Demo-PLC"))
        self.assertEqual(payload["type"], "message")
        attachment = payload["attachments"][0]
        self.assertEqual(
            attachment["contentType"],
            "application/vnd.microsoft.card.adaptive",
        )
        encoded = json.dumps(payload)
        self.assertIn("Demo-PLC", encoded)
        self.assertIn("2m 35s", encoded)
        self.assertIn("Device Recovered", encoded)

    def test_test_payload_is_clearly_test_only(self):
        payload = teams_webhook_payload(NotificationEvent.test_notification())
        encoded = json.dumps(payload)
        self.assertIn("Test Notification", encoded)
        self.assertIn("TEST", encoded)

    def test_endpoint_validation_and_redaction(self):
        endpoint = "https://example.invalid/workflow/fictional-token?key=fictional"
        self.assertTrue(endpoint_is_valid(endpoint))
        self.assertEqual(redact_url(endpoint), "https://example.invalid/…")
        self.assertNotIn("fictional-token", redact_url(endpoint))
        self.assertFalse(endpoint_is_valid("ftp://example.com/hook"))
        self.assertFalse(endpoint_is_valid("https://example.invalid:bad/hook"))


class WebhookDeliveryTests(unittest.TestCase):
    def test_generic_webhook_posts_utf8_json_and_user_agent(self):
        with LocalWebhookServer() as server:
            result = GenericWebhookProvider(server.url).deliver(event(), 2)
        self.assertTrue(result.success)
        headers, body = RecordingHandler.requests[0]
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertTrue(headers["User-Agent"].startswith("MultiPortChecker/"))
        self.assertEqual(json.loads(body.decode("utf-8"))["device"], "อุปกรณ์ทดสอบ")

    def test_teams_webhook_posts_adaptive_card(self):
        with LocalWebhookServer() as server:
            result = TeamsWebhookProvider(server.url).deliver(
                event("RECOVERED", "Demo-PLC"), 2
            )
        self.assertTrue(result.success)
        payload = json.loads(RecordingHandler.requests[0][1].decode("utf-8"))
        self.assertEqual(payload["type"], "message")

    def test_http_non_2xx_is_retryable_and_redacted(self):
        with LocalWebhookServer() as server:
            RecordingHandler.statuses = [401]
            result = GenericWebhookProvider(server.url + "?token=hidden").deliver(
                event(), 2
            )
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertIn("HTTP 401", result.message)
        self.assertNotIn("token", result.message)
        self.assertNotIn(server.url, result.message)

    def test_timeout_is_contained_and_endpoint_is_not_exposed(self):
        endpoint = "https://example.invalid/hook/fictional-token"
        with patch(
            "webhook_notifications.request.urlopen", side_effect=socket.timeout()
        ):
            result = GenericWebhookProvider(endpoint).deliver(event(), 1)
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertIn("timed out", result.message)
        self.assertNotIn(endpoint, result.message)

    def test_invalid_endpoint_fails_without_network_access(self):
        with patch("webhook_notifications.request.urlopen") as urlopen:
            result = GenericWebhookProvider("not-a-url").deliver(event(), 1)
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        urlopen.assert_not_called()

    def test_local_server_retry_reaches_controlled_success(self):
        results = []
        with LocalWebhookServer() as server:
            RecordingHandler.statuses = [500, 429, 204]
            provider = GenericWebhookProvider(server.url)
            manager = NotificationManager(results.append, retry_delays=(0, 0))
            try:
                manager.configure(
                    NotificationSettings(
                        generic_webhook_enabled=True,
                        retry_count=2,
                        timeout_seconds=2,
                    ),
                    {PROVIDER_GENERIC: provider},
                )
                self.assertEqual(manager.enqueue(event()), 1)
                self.assertTrue(manager.wait_until_idle())
            finally:
                manager.shutdown(2)
        self.assertEqual(len(RecordingHandler.requests), 3)
        self.assertTrue(any(result.success for result in results))


if __name__ == "__main__":
    unittest.main()
