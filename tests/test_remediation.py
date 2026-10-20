import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from database.database import Database
from monitoring.remediation import RemediationService


class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.database = Database(str(Path(self.temporary_directory.name) / "remediation-test.db"))
        self.session_id = self.database.create_session("test0", "192.0.2.2", "192.0.2.1")
        self.service = RemediationService(self.database)

    def tearDown(self):
        self.database.close()
        self.temporary_directory.cleanup()

    def add_measurement(self, index, dns_success, internet_reachable=1, http_status=200):
        self.database.insert_measurement(
            {
                "timestamp": f"2026-10-20T10:00:{index:02}",
                "dns_success": dns_success,
                "internet_reachable": internet_reachable,
                "http_status_code": http_status,
                "overall_status": "NORMAL" if dns_success else "DEGRADED",
                "bytes_used": 100,
            },
            session_id=self.session_id,
        )

    def test_requires_three_consecutive_dns_failures_with_other_checks_working(self):
        for index in range(3):
            self.add_measurement(index, dns_success=0)
        eligible, _, _ = self.service.eligibility()
        self.assertTrue(eligible)

        self.add_measurement(3, dns_success=0, internet_reachable=0)
        eligible, reason, _ = self.service.eligibility()
        self.assertFalse(eligible)
        self.assertIn("External connectivity", reason)

    def test_remediation_is_audited_and_verified_from_following_measurements(self):
        for index in range(3):
            self.add_measurement(index, dns_success=0)

        with patch("monitoring.remediation.flush_dns_cache", return_value="DNS cache flushed"):
            result = self.service.run_dns_flush()
        self.assertIn("next 3 measurements", result["note"])

        for index in range(3, 6):
            self.add_measurement(index, dns_success=1)
            self.service.on_measurement()

        action = self.database.get_session_remediation_actions(self.session_id)[0]
        self.assertEqual(json.loads(action["result"])["status"], "VERIFIED_IMPROVED")
        verification = self.database.get_session_verification_results(self.session_id)[0]
        self.assertEqual(verification["result"], "VERIFIED_IMPROVED")
        self.assertEqual(verification["after_value"], "3/3 successful checks")

    def test_auto_mode_defaults_off_and_cannot_run_without_eligibility(self):
        self.assertFalse(self.service.automatic_dns_enabled)
        self.service.on_measurement()
        self.assertEqual(self.database.get_session_remediation_actions(self.session_id), [])

    def test_opted_in_automation_runs_only_after_three_isolated_failures(self):
        with (
            patch("monitoring.remediation.os.name", "nt"),
            patch("monitoring.remediation.flush_dns_cache", return_value="DNS cache flushed") as flush,
        ):
            self.service.set_automatic_dns_enabled(True)
            for index in range(2):
                self.add_measurement(index, dns_success=0)
                self.service.on_measurement()
            flush.assert_not_called()

            self.add_measurement(2, dns_success=0)
            self.service.on_measurement()

        flush.assert_called_once_with()
        action = self.database.get_session_remediation_actions(self.session_id)[0]
        self.assertIn("AUTOMATIC_OPT_IN", action["result"])
        self.assertIn("PENDING_VERIFICATION", action["result"])


if __name__ == "__main__":
    unittest.main()
