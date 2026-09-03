import unittest

from network_checks import (
    build_tracert_command,
    normalize_trace_destination,
    validate_trace_max_hops,
    validate_trace_timeout,
)


class TracertCommandTests(unittest.TestCase):
    def test_builds_default_hostname_command(self):
        self.assertEqual(
            build_tracert_command("google.com"),
            ["tracert", "-d", "-h", "15", "-w", "1000", "google.com"],
        )

    def test_builds_custom_ipv4_command(self):
        self.assertEqual(
            build_tracert_command(" 192.168.1.1 ", "20", "2500"),
            ["tracert", "-d", "-h", "20", "-w", "2500", "192.168.1.1"],
        )

    def test_destination_is_one_shell_free_argument(self):
        command = build_tracert_command("example.com", 5, 500)
        self.assertEqual(command[-1], "example.com")
        self.assertEqual(len(command), 7)


class TraceValidationTests(unittest.TestCase):
    def test_valid_max_hops(self):
        self.assertEqual(validate_trace_max_hops("255"), 255)

    def test_rejects_invalid_max_hops(self):
        for value in ("", "1.5", 0, 256):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Max Hops"):
                    validate_trace_max_hops(value)

    def test_valid_timeout(self):
        self.assertEqual(validate_trace_timeout("60000"), 60000)

    def test_rejects_invalid_timeout(self):
        for value in ("", "fast", 0, 60001):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Timeout"):
                    validate_trace_timeout(value)

    def test_accepts_hostname_and_ipv4(self):
        self.assertEqual(normalize_trace_destination(" Example.COM "), "Example.COM")
        self.assertEqual(normalize_trace_destination("8.8.8.8"), "8.8.8.8")

    def test_rejects_empty_or_option_like_destination(self):
        for value in ("", "   ", "-h", "bad host"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_trace_destination(value)


if __name__ == "__main__":
    unittest.main()
