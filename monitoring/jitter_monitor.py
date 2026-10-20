"""
monitoring/jitter_monitor.py

Phase 2 module.

Pure calculation of network jitter from a list of round-trip latency
samples taken within a single ping round.

Jitter here is defined per RFC 3550's "mean deviation" style approach,
simplified to the mean of the absolute differences between consecutive
latency samples (this is the same practical definition used by most
consumer network-quality tools such as speed-test utilities). It answers
"how much does the latency wobble from one packet to the next", which is
what makes voice/video calls choppy even when average latency looks fine.
"""

from __future__ import annotations

from typing import List, Optional


def compute_jitter_ms(samples_ms: List[float]) -> Optional[float]:
    """
    Return jitter in milliseconds, or None if there are fewer than two
    samples (jitter is undefined for 0 or 1 data points).
    """
    if len(samples_ms) < 2:
        return None

    differences = [
        abs(samples_ms[i] - samples_ms[i - 1]) for i in range(1, len(samples_ms))
    ]
    return round(sum(differences) / len(differences), 2)


def is_within_threshold(jitter_ms: Optional[float], threshold_ms: float) -> bool:
    """
    True if jitter is at/below the configured threshold. A None jitter
    (not enough samples to compute it) is treated as within threshold,
    since we cannot penalize a measurement we could not take.
    """
    if jitter_ms is None:
        return True
    return jitter_ms <= threshold_ms


if __name__ == "__main__":
    print(compute_jitter_ms([20.0, 22.0, 19.5, 21.0]))  # small jitter
    print(compute_jitter_ms([20.0, 60.0, 15.0, 80.0]))  # large jitter
    print(compute_jitter_ms([20.0]))                     # None
    print(compute_jitter_ms([]))                          # None
