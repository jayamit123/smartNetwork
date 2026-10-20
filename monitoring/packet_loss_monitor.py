"""
monitoring/packet_loss_monitor.py

Phase 2 module.

Pure calculation of packet loss percentage from a ping round's sent/
received counts. Kept as its own module (rather than folded into
latency_monitor.py) so that the fault-classification and threshold logic
added in later phases has one obvious place to import packet-loss maths
from, matching the project's required module layout.
"""

from __future__ import annotations


def compute_packet_loss_percent(packets_sent: int, packets_received: int) -> float:
    """
    Return packet loss as a percentage in [0, 100].

    If no packets were sent at all (a degenerate/invalid call), we treat
    that as 100% loss rather than dividing by zero or claiming 0% loss,
    since "no data" must never be reported as "everything fine".
    """
    if packets_sent <= 0:
        return 100.0

    lost = max(0, packets_sent - packets_received)
    return round((lost / packets_sent) * 100.0, 2)


def is_within_threshold(packet_loss_percent: float, threshold_percent: float) -> bool:
    """True if the measured packet loss is at or below the configured
    threshold (i.e. considered acceptable / PASS)."""
    return packet_loss_percent <= threshold_percent


if __name__ == "__main__":
    print(compute_packet_loss_percent(4, 4))   # 0.0
    print(compute_packet_loss_percent(4, 3))   # 25.0
    print(compute_packet_loss_percent(4, 0))   # 100.0
    print(compute_packet_loss_percent(0, 0))   # 100.0 (degenerate case)
