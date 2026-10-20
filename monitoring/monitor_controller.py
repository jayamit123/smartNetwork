"""
monitoring/monitor_controller.py

Phase 2 + Phase 3 module: the Monitoring Controller.

Runs one full "round" of measurements (interface snapshot, gateway,
internet + packet-loss + jitter, DNS, HTTP) on a background thread, on a
configurable interval, WITHOUT blocking the Tkinter GUI thread:

    Tkinter GUI
         |
         | Start Monitoring
         v
    MonitorController.start()
         |
         v
    Background Monitoring Thread (_run)
         |
         +---- Network Interface  (interface_monitor.py -> network_utils.py)
         +---- Gateway Test        (gateway_monitor.py)
         +---- Internet Test       (internet_monitor.py)
         +---- Latency             (latency_monitor.py, used by the above two)
         +---- Packet Loss         (packet_loss_monitor.py)
         +---- Jitter              (jitter_monitor.py)
         +---- DNS Test            (dns_monitor.py)
         +---- HTTP Test           (http_monitor.py)
         v
    MeasurementRecord (== the spec's MonitoringResult)
         v
    Phase 3 Database Logger (database/database.py: insert_measurement)
         v
    queue.Queue -> polled by the GUI thread via after()

Each measurement's own failure is isolated: if the gateway ping fails,
the internet/DNS/HTTP tests still run, and the round still produces one
complete database record with NULLs (None) in place of the numeric
values that could not be measured -- never fabricated strings such as
"error" or "N/A" in a numeric column.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from database.database import Database
from monitoring.dns_monitor import check_dns
from monitoring.gateway_monitor import check_gateway
from monitoring.http_monitor import check_http
from monitoring.interface_monitor import InterfaceMonitor
from monitoring.internet_monitor import check_internet
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MeasurementRecord:
    """
    One complete monitoring cycle. Field names match the project's
    required MonitoringResult exactly (plus a couple of extras --
    overall_status, bytes_used, session_id -- that support this
    project's live dashboard and session-history views without changing
    the meaning of any required field).
    """

    timestamp: str
    interface_name: Optional[str]
    ipv4_address: Optional[str]

    gateway_ip: Optional[str]
    gateway_reachable: int          # 0 or 1 (SQLite boolean convention)
    gateway_latency_ms: Optional[float]
    gateway_latency_min_ms: Optional[float]
    gateway_latency_max_ms: Optional[float]
    gateway_packet_loss: float

    internet_host: str
    internet_reachable: int
    internet_latency_ms: Optional[float]
    internet_latency_min_ms: Optional[float]
    internet_latency_max_ms: Optional[float]
    internet_packet_loss: float

    jitter_ms: Optional[float]

    dns_domain: str
    dns_success: int
    dns_response_time_ms: Optional[float]
    dns_resolved_ip: Optional[str]

    http_url: str
    http_status_code: Optional[int]
    http_response_time_ms: Optional[float]

    overall_status: str
    bytes_used: int

    def as_db_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MonitorController:
    """
    Owns the background monitoring thread. GUI code should only ever
    call start()/stop()/is_running() and drain get_updates_nowait() on a
    timer -- it must never touch the thread directly, and the thread
    must never touch Tkinter widgets directly.
    """

    def __init__(self, settings: Dict[str, Any], database: Database):
        self._settings = settings
        self._database = database
        self._interface_monitor = InterfaceMonitor()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._updates: "queue.Queue[MeasurementRecord]" = queue.Queue()

        self.session_id: Optional[int] = None

    # ------------------------------------------------------------------
    # Public control surface (safe to call from the GUI thread)
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_settings(self, settings: Dict[str, Any]) -> None:
        """Replace monitoring configuration while the controller is stopped."""
        if self.is_running():
            raise RuntimeError("Monitoring settings cannot be changed while monitoring is running.")
        self._settings = dict(settings)

    def start(self) -> Optional[int]:
        """Start a new monitoring session and background thread. Returns
        the new session_id, or None if the database session row could
        not be created (monitoring is then NOT started)."""
        if self.is_running():
            logger.warning("start() called while monitoring is already running; ignoring.")
            return self.session_id

        snapshot = self._interface_monitor.refresh()
        session_id = self._database.create_session(
            interface=snapshot.interface, ipv4=snapshot.ipv4, gateway=snapshot.gateway
        )
        if session_id is None:
            logger.error("Could not start monitoring: session could not be created in the database.")
            return None

        self.session_id = session_id
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MonitorControllerThread", daemon=True)
        self._thread.start()
        return session_id

    def stop(self, final_status: str = "COMPLETED") -> None:
        if not self.is_running():
            return

        self._stop_event.set()
        self._thread.join(timeout=15)
        if self.session_id is not None:
            self._database.end_session(self.session_id, final_status=final_status)

    def get_updates_nowait(self) -> list:
        """Drain and return every MeasurementRecord produced since the
        last call. Safe to call frequently from a GUI `after()` tick."""
        records = []
        while True:
            try:
                records.append(self._updates.get_nowait())
            except queue.Empty:
                break
        return records

    # ------------------------------------------------------------------
    # Background thread body
    # ------------------------------------------------------------------

    def _run(self) -> None:
        interval_seconds = max(1, int(self._settings.get("monitoring_interval", 5)))

        while not self._stop_event.is_set():
            round_start = time.monotonic()
            try:
                record = self._collect_one_round()
                stored = self._database.insert_measurement(record, session_id=self.session_id)
                if not stored:
                    logger.error("Measurement collected but could not be stored in the database.")
                self._updates.put(record)
            except Exception as exc:  # noqa: BLE001 - a monitoring round must never kill the thread
                logger.exception("Monitoring exception during a measurement round: %s", exc)

            elapsed = time.monotonic() - round_start
            remaining = max(0.0, interval_seconds - elapsed)
            # wait() (not sleep()) so stop() is responsive even mid-interval.
            self._stop_event.wait(remaining)

    def _collect_one_round(self) -> MeasurementRecord:
        settings = self._settings

        gateway_ping_count = int(settings.get("gateway_ping_count", 3))
        internet_ping_count = int(settings.get("internet_ping_count", 3))
        internet_host = settings.get("internet_host", "8.8.8.8")
        dns_domain = settings.get("dns_test_domain", "google.com")
        http_url = settings.get("http_test_url", "https://www.google.com")
        http_timeout = settings.get("http_timeout", 5)
        dns_timeout = settings.get("dns_timeout", 3)
        ping_timeout = settings.get("ping_timeout_seconds", 2)

        # Cheap: OS queries only, no network traffic. Refreshed every
        # round so a Wi-Fi roam / adapter change is picked up.
        snapshot = self._interface_monitor.refresh()

        gateway_result = check_gateway(snapshot.gateway, ping_count=gateway_ping_count, timeout_seconds=ping_timeout)
        internet_result = check_internet(internet_host, ping_count=internet_ping_count, timeout_seconds=ping_timeout)
        dns_result = check_dns(dns_domain, timeout_seconds=dns_timeout)
        http_result = check_http(http_url, timeout_seconds=http_timeout)

        overall_status = self._compute_overall_status(gateway_result, internet_result, dns_result, http_result, settings)

        bytes_used = (
            gateway_ping_count * 64 * 2
            + internet_result.estimated_bytes_used
            + 100  # rough flat estimate for one DNS query+response
            + http_result.estimated_bytes_used
        )

        return MeasurementRecord(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            interface_name=snapshot.interface,
            ipv4_address=snapshot.ipv4,

            gateway_ip=snapshot.gateway,
            gateway_reachable=1 if gateway_result.reachable else 0,
            gateway_latency_ms=gateway_result.latency_avg_ms,
            gateway_latency_min_ms=gateway_result.latency_min_ms,
            gateway_latency_max_ms=gateway_result.latency_max_ms,
            gateway_packet_loss=gateway_result.packet_loss_percent,

            internet_host=internet_host,
            internet_reachable=1 if internet_result.reachable else 0,
            internet_latency_ms=internet_result.latency_avg_ms,
            internet_latency_min_ms=internet_result.latency_min_ms,
            internet_latency_max_ms=internet_result.latency_max_ms,
            internet_packet_loss=internet_result.packet_loss_percent,

            jitter_ms=internet_result.jitter_ms,

            dns_domain=dns_domain,
            dns_success=1 if dns_result.success else 0,
            dns_response_time_ms=dns_result.response_time_ms,
            dns_resolved_ip=dns_result.resolved_address,

            http_url=http_url,
            http_status_code=http_result.status_code,
            http_response_time_ms=http_result.response_time_ms,

            overall_status=overall_status,
            bytes_used=int(bytes_used),
        )

    @staticmethod
    def _compute_overall_status(gateway_result, internet_result, dns_result, http_result, settings) -> str:
        """
        Simple, explainable status roll-up for live-dashboard display
        purposes only. This is NOT fault classification and does not
        attempt to name a probable cause -- it only answers "is
        everything currently fine, degraded, or down". Per the project
        rule for this phase, no measurement is ever labelled as an
        "ISP problem", "router problem" etc. here.
        """
        if not gateway_result.reachable:
            logger.warning("Gateway unreachable.")
        if not internet_result.reachable:
            logger.warning("Internet host unreachable.")

        if not gateway_result.reachable and not internet_result.reachable:
            return "DISCONNECTED"

        thresholds = settings.get("warning_thresholds", {})
        latency_threshold = thresholds.get("latency_ms", 100)
        packet_loss_threshold = thresholds.get("packet_loss_percent", 5)
        jitter_threshold = thresholds.get("jitter_ms", 30)

        degraded = False
        if not internet_result.reachable or not dns_result.success or not http_result.success:
            degraded = True
        if internet_result.latency_avg_ms is not None and internet_result.latency_avg_ms > latency_threshold:
            degraded = True
        if internet_result.packet_loss_percent > packet_loss_threshold:
            degraded = True
        if internet_result.jitter_ms is not None and internet_result.jitter_ms > jitter_threshold:
            degraded = True

        return "DEGRADED" if degraded else "NORMAL"


if __name__ == "__main__":
    from utils.config_loader import load_settings

    test_settings = load_settings()
    test_db = Database()
    controller = MonitorController(test_settings, test_db)

    sid = controller.start()
    print("Started session:", sid)
    time.sleep(6)
    for rec in controller.get_updates_nowait():
        print(rec)
    controller.stop()
    test_db.close()
