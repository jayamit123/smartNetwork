"""
monitoring/gateway_monitor.py

Phase 2 module.

Checks reachability and latency of the default gateway using a
configurable number of ICMP packets (gateway_ping_count in
config/settings.json, default 3) sent in a single ping invocation.
Collects average, minimum and maximum latency plus packet loss, matching
the project's required MonitoringResult fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from monitoring.latency_monitor import run_ping
from monitoring.packet_loss_monitor import compute_packet_loss_percent
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GatewayResult:
    reachable: bool
    status: str  # "PASS" or "FAIL" (convenience string form of `reachable`)
    latency_avg_ms: Optional[float]
    latency_min_ms: Optional[float]
    latency_max_ms: Optional[float]
    packet_loss_percent: float
    error: str = ""


def check_gateway(
    gateway_ip: Optional[str],
    ping_count: int = 3,
    timeout_seconds: float = 2.0,
) -> GatewayResult:
    """
    Ping the default gateway `ping_count` times in one round. If no
    gateway address was detected at all (e.g. adapter down), this is
    reported as unreachable without even attempting a network call.
    """
    if not gateway_ip:
        logger.warning("Gateway unreachable: no gateway address detected.")
        return GatewayResult(
            reachable=False,
            status="FAIL",
            latency_avg_ms=None,
            latency_min_ms=None,
            latency_max_ms=None,
            packet_loss_percent=100.0,
            error="No gateway detected",
        )

    ping_result = run_ping(gateway_ip, count=ping_count, timeout_seconds=timeout_seconds)
    packet_loss_percent = compute_packet_loss_percent(
        ping_result.packets_sent, ping_result.packets_received
    )

    if ping_result.reachable:
        return GatewayResult(
            reachable=True,
            status="PASS",
            latency_avg_ms=ping_result.average_latency_ms,
            latency_min_ms=ping_result.min_latency_ms,
            latency_max_ms=ping_result.max_latency_ms,
            packet_loss_percent=packet_loss_percent,
        )

    logger.warning("Gateway %s unreachable: %s", gateway_ip, ping_result.error or "no reply")
    return GatewayResult(
        reachable=False,
        status="FAIL",
        latency_avg_ms=None,
        latency_min_ms=None,
        latency_max_ms=None,
        packet_loss_percent=packet_loss_percent,
        error=ping_result.error or "Gateway unreachable",
    )


if __name__ == "__main__":
    print(check_gateway("127.0.0.1", ping_count=3))
    print(check_gateway(None))
