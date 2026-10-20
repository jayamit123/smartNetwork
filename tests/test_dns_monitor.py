import unittest
import socket
import threading
from unittest.mock import patch

from monitoring import dns_monitor
from monitoring.dns_monitor import check_dns


class DnsMonitorTests(unittest.TestCase):
    @patch("monitoring.dns_monitor.socket.getaddrinfo")
    def test_resolution_uses_system_resolver(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.11", 0)),
        ]

        result = check_dns("example.com", timeout_seconds=1)

        getaddrinfo.assert_called_once_with(
            "example.com",
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.resolved_address, "192.0.2.10")

    @patch("monitoring.dns_monitor.socket.getaddrinfo")
    def test_dns_timeout_returns_failed_result(self, getaddrinfo):
        release_lookup = threading.Event()

        def stalled_lookup(*args, **kwargs):
            release_lookup.wait(timeout=2)
            return []

        getaddrinfo.side_effect = stalled_lookup
        lookup = None
        try:
            result = check_dns("slow.example", timeout_seconds=0.1)
            lookup = dns_monitor._active_lookup
        finally:
            release_lookup.set()
            if lookup is not None:
                lookup.completed.wait(timeout=1)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("timed out", result.error)

    @patch("monitoring.dns_monitor.socket.getaddrinfo")
    def test_dns_error_from_system_resolver_returns_failure(self, getaddrinfo):
        getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        result = check_dns("invalid.example", timeout_seconds=1)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("Name or service not known", result.error)


if __name__ == "__main__":
    unittest.main()
