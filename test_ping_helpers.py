import subprocess
import unittest
from unittest.mock import patch

import network_checks
from network_checks import parse_ping_latency, ping_host



class ParsePingLatencyTests(unittest.TestCase):
    def test_standard_windows_latency(self):
        self.assertEqual(parse_ping_latency(b"Reply: time=7ms TTL=117"), "7 ms")

    def test_less_than_one_millisecond(self):
        self.assertEqual(parse_ping_latency(b"Reply: time<1ms TTL=128"), "<1 ms")

    def test_localized_label_and_decimal_comma(self):
        self.assertEqual(parse_ping_latency("localized text = 7,5 ms TTL=64"), "7.5 ms")

    def test_unparseable_output(self):
        self.assertIsNone(parse_ping_latency("successful response without latency"))


class PingHostTests(unittest.TestCase):
    @patch.object(network_checks.subprocess, "run")
    def test_success_without_latency_is_online(self, run):
        run.return_value = subprocess.CompletedProcess(["ping"], 0, stdout=b"success")
        self.assertEqual(ping_host("example.test"), "Online")

    @patch.object(network_checks.subprocess, "run")
    def test_nonzero_return_code_is_timeout(self, run):
        run.return_value = subprocess.CompletedProcess(["ping"], 1, stdout=b"request timed out")
        self.assertEqual(ping_host("example.test"), "Timeout")

    @patch.object(network_checks.subprocess, "run", side_effect=FileNotFoundError)
    def test_missing_ping_executable_is_timeout(self, _run):
        self.assertEqual(ping_host("example.test"), "Timeout")

    @patch.object(network_checks.subprocess, "run", side_effect=subprocess.TimeoutExpired("ping", 3))
    def test_process_timeout_is_timeout(self, _run):
        self.assertEqual(ping_host("example.test"), "Timeout")


class CombinedCheckTests(unittest.TestCase):
    @patch.object(network_checks, "check_single_host_port", return_value=True)
    @patch.object(network_checks, "ping_host", return_value="Timeout")
    def test_ping_timeout_does_not_force_tcp_offline(self, _ping, _tcp):
        self.assertEqual(network_checks.check_target("example.test", 443), ("Timeout", True))


if __name__ == "__main__":
    unittest.main()
