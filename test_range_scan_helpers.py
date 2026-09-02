import unittest

from network_checks import IPv4ScanPlan, normalize_target_key, validate_ipv4_range


class IPv4RangeValidationTests(unittest.TestCase):
    def test_inclusive_ipv4_range(self):
        self.assertEqual(
            validate_ipv4_range("192.168.1.1", "192.168.1.3"),
            ["192.168.1.1", "192.168.1.2", "192.168.1.3"],
        )

    def test_rejects_invalid_ipv4(self):
        with self.assertRaisesRegex(ValueError, "valid IPv4"):
            validate_ipv4_range("192.168.1.999", "192.168.1.3")

    def test_rejects_start_greater_than_end(self):
        with self.assertRaisesRegex(ValueError, "lower than Start IP"):
            validate_ipv4_range("192.168.1.10", "192.168.1.1")

    def test_rejects_excessive_range(self):
        with self.assertRaisesRegex(ValueError, "maximum is 4"):
            validate_ipv4_range("10.0.0.1", "10.0.0.5", maximum=4)


class TargetKeyTests(unittest.TestCase):
    def test_hostname_case_and_whitespace_do_not_create_duplicates(self):
        self.assertEqual(
            normalize_target_key(" Example.COM ", 443),
            normalize_target_key("example.com", "443"),
        )


class IPv4ScanPlanTests(unittest.TestCase):
    def test_batches_advance_without_rescheduling_addresses(self):
        plan = IPv4ScanPlan.from_range("192.168.1.1", "192.168.1.3")
        self.assertEqual(plan.take(2), ["192.168.1.1", "192.168.1.2"])
        self.assertEqual(plan.take(2), ["192.168.1.3"])
        self.assertTrue(plan.exhausted)

    def test_cancel_stops_new_work_from_being_scheduled(self):
        plan = IPv4ScanPlan.from_range("192.168.1.1", "192.168.1.3")
        self.assertEqual(plan.take(1), ["192.168.1.1"])
        plan.cancel()
        self.assertEqual(plan.take(2), [])
        self.assertFalse(plan.exhausted)


if __name__ == "__main__":
    unittest.main()
