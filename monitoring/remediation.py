"""Guarded local DNS remediation with explicit audit and verification."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from database.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)

_ACTION_NAME = "Flush Windows DNS cache"
_COMMAND_DESCRIPTION = "ipconfig /flushdns"
_REQUIRED_FAILURES = 3
_VERIFYING_MEASUREMENTS = 3
_AUTO_COOLDOWN_SECONDS = 300

def flush_dns_cache() -> str:
    """Flush the Windows DNS client cache without changing adapter settings."""
    if os.name != "nt":
        raise NotImplementedError("DNS cache flushing is currently supported on Windows only.")

    result = subprocess.run(
        ["ipconfig", "/flushdns"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ipconfig returned a failure status").strip()
        raise RuntimeError(message)
    return (result.stdout or result.stderr or "Windows reported that the DNS cache was flushed.").strip()


class RemediationService:
    """Run only a confirmed or explicitly enabled DNS-cache remediation."""

    def __init__(self, database: Database):
        self._database = database
        self._lock = threading.RLock()
        self._automatic_dns_enabled = False
        self._next_automatic_attempt = 0.0

    @property
    def automatic_dns_enabled(self) -> bool:
        with self._lock:
            return self._automatic_dns_enabled

    def set_automatic_dns_enabled(self, enabled: bool) -> bool:
        if enabled and os.name != "nt":
            raise NotImplementedError("Automatic DNS-cache remediation is currently supported on Windows only.")
        with self._lock:
            self._automatic_dns_enabled = enabled
        return self._automatic_dns_enabled

    def eligibility(self) -> Tuple[bool, str, List[Dict[str, Any]]]:
        latest = self._database.get_recent_measurements(limit=_REQUIRED_FAILURES)
        if len(latest) < _REQUIRED_FAILURES:
            return False, f"Requires {_REQUIRED_FAILURES} recent checks.", latest
        if any(row.get("dns_success") != 0 for row in latest):
            return False, f"Requires {_REQUIRED_FAILURES} consecutive DNS failures.", latest
        if any(row.get("internet_reachable") != 1 for row in latest):
            return False, "External connectivity must be working to isolate DNS as the likely local issue.", latest
        if any(
            row.get("http_status_code") is None
            or not 200 <= int(row["http_status_code"]) < 400
            for row in latest
        ):
            return False, "HTTP must be responding successfully to isolate DNS as the likely local issue.", latest
        if self._database.get_pending_remediation_actions():
            return False, "A DNS remediation is already awaiting verification.", latest
        return True, "Three consecutive DNS failures with working internet and HTTP checks.", latest

    def run_dns_flush(self, mode: str = "MANUAL") -> Dict[str, Any]:
        with self._lock:
            eligible, reason, rows = self.eligibility()
            if not eligible:
                raise ValueError(reason)
            if not rows or rows[0].get("session_id") is None:
                raise ValueError("A saved monitoring session is required to audit remediation.")

            baseline = {
                "measurement_id": rows[0]["id"],
                "dns_success": rows[0].get("dns_success"),
                "http_status_code": rows[0].get("http_status_code"),
                "internet_reachable": rows[0].get("internet_reachable"),
            }
            remediation_id = self._database.create_remediation_action(
                session_id=rows[0]["session_id"],
                action_name=_ACTION_NAME,
                command=_COMMAND_DESCRIPTION,
                pre_measurements=baseline,
                result=json.dumps(
                    {"status": "EXECUTING", "mode": mode, "reason": reason},
                    ensure_ascii=True,
                ),
            )
            if remediation_id is None:
                raise RuntimeError("Could not save remediation audit record.")

            self._next_automatic_attempt = time.monotonic() + _AUTO_COOLDOWN_SECONDS
            try:
                output = flush_dns_cache()
            except (OSError, RuntimeError, subprocess.TimeoutExpired, NotImplementedError) as exc:
                self._database.update_remediation_result(
                    remediation_id,
                    json.dumps(
                        {"status": "EXECUTION_FAILED", "mode": mode, "error": str(exc)},
                        ensure_ascii=True,
                    ),
                )
                logger.exception("DNS-cache remediation #%s failed.", remediation_id)
                raise

            self._database.update_remediation_result(
                remediation_id,
                json.dumps(
                    {
                        "status": "PENDING_VERIFICATION",
                        "mode": mode,
                        "message": output,
                        "baseline_measurement_id": baseline["measurement_id"],
                        "observations": [],
                    },
                    ensure_ascii=True,
                ),
            )
            return {
                "remediation_id": remediation_id,
                "message": output,
                "note": f"Remediation ran. Verification will use the next {_VERIFYING_MEASUREMENTS} measurements.",
            }

    def on_measurement(self) -> None:
        """Verify pending actions, then optionally launch one eligible fix."""
        with self._lock:
            latest = self._database.get_recent_measurements(limit=1)
            if latest:
                self._verify_pending(latest[0])
            if (
                self._automatic_dns_enabled
                and time.monotonic() >= self._next_automatic_attempt
            ):
                eligible, _, _ = self.eligibility()
                if eligible:
                    try:
                        self.run_dns_flush(mode="AUTOMATIC_OPT_IN")
                    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                        logger.error("Automatic DNS remediation was not completed: %s", exc)

    def _verify_pending(self, measurement: Dict[str, Any]) -> None:
        for action in self._database.get_pending_remediation_actions():
            try:
                result = json.loads(action["result"])
                baseline = json.loads(action["pre_measurements"] or "{}")
                if int(measurement["id"]) <= int(result["baseline_measurement_id"]):
                    continue
                observations = result.get("observations", [])
                if observations and observations[-1].get("measurement_id") == measurement["id"]:
                    continue
                observations.append(
                    {
                        "measurement_id": measurement["id"],
                        "dns_success": measurement.get("dns_success"),
                    }
                )
                result["observations"] = observations[-_VERIFYING_MEASUREMENTS:]
                if len(result["observations"]) < _VERIFYING_MEASUREMENTS:
                    self._database.update_remediation_result(action["remediation_id"], json.dumps(result))
                    continue

                successes = sum(item.get("dns_success") == 1 for item in result["observations"])
                improved = successes >= 2
                verification = "VERIFIED_IMPROVED" if improved else "NO_IMPROVEMENT"
                result["status"] = verification
                result["verified_measurements"] = len(result["observations"])
                result["dns_successes"] = successes
                self._database.update_remediation_result(action["remediation_id"], json.dumps(result))
                self._database.record_verification_result(
                    session_id=action["session_id"],
                    remediation_id=action["remediation_id"],
                    metric="dns_success",
                    before_value=str(baseline.get("dns_success")),
                    after_value=f"{successes}/{_VERIFYING_MEASUREMENTS} successful checks",
                    result=verification,
                )
                if not improved:
                    self._next_automatic_attempt = time.monotonic() + _AUTO_COOLDOWN_SECONDS
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                logger.exception(
                    "Could not verify DNS remediation #%s: %s",
                    action.get("remediation_id"),
                    exc,
                )
