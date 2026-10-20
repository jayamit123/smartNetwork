"""
monitoring/internet_monitor.py

Phase 2 module.

Checks reachability of a configurable external host (internet_host in
config/settings.json, default 8.8.8.8) using a configurable number of
ICMP packets (internet_ping_count, default 3) sent in ONE subprocess
call. From that single ping round we derive average/min/max latency,
packet loss, and jitter (mean absolute difference between consecutive
successful latency samples -- see jitter_monitor.py for the exact
method, documented there and in the README).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from monitoring.jitter_monitor import compute_jitter_ms
from monitoring.latency_monitor import run_ping
from monitoring.packet_loss_monitor import compute_packet_loss_percent
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class InternetResult:
    reachable: bool
    status: str  # "PASS" or "FAIL"
    latency_avg_ms: Optional[float]
    latency_min_ms: Optional[float]
    latency_max_ms: Optional[float]
    packet_loss_percent: float
    jitter_ms: Optional[float]
    error: str = ""
    estimated_bytes_used: int = 0


def check_internet(
    host: str,
    ping_count: int = 3,
    timeout_seconds: float = 2.0,
) -> InternetResult:
    """
    Ping `host` `ping_count` times in one round. Reachable if at least
    one reply was received; packet loss and jitter are always computed
    from whatever samples came back.
    """
    ping_result = run_ping(host, count=ping_count, timeout_seconds=timeout_seconds)

    packet_loss_percent = compute_packet_loss_percent(
        ping_result.packets_sent, ping_result.packets_received
    )
    jitter_ms = compute_jitter_ms(ping_result.samples_ms)

    if ping_result.reachable:
        return InternetResult(
            reachable=True,
            status="PASS",
            latency_avg_ms=ping_result.average_latency_ms,
            latency_min_ms=ping_result.min_latency_ms,
            latency_max_ms=ping_result.max_latency_ms,
            packet_loss_percent=packet_loss_percent,
            jitter_ms=jitter_ms,
            estimated_bytes_used=ping_result.estimated_bytes_used,
        )

    logger.warning("Internet host %s unreachable: %s", host, ping_result.error or "no reply")
    return InternetResult(
        reachable=False,
        status="FAIL",
        latency_avg_ms=None,
        latency_min_ms=None,
        latency_max_ms=None,
        packet_loss_percent=packet_loss_percent,
        jitter_ms=jitter_ms,
        error=ping_result.error or f"{host} unreachable",
        estimated_bytes_used=ping_result.estimated_bytes_used,
    )


if __name__ == "__main__":
    print(check_internet("127.0.0.1", ping_count=3))
    print(check_internet("8.8.8.8", ping_count=3))
