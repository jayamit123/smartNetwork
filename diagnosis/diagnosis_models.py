"""
diagnosis/diagnosis_models.py

Phase 4 module: the data model returned by temporal_analysis.py.

`DetectionResult` is intentionally a plain, flat dataclass of booleans,
numbers and short strings -- no nested objects, no probability scores,
no free-text "diagnosis" sentence. Every field answers a narrow,
explainable question ("did recent packet loss cross the configured
threshold?"), never a root-cause question ("is the router broken?").
Phase 5 is expected to import this dataclass and reason over its fields;
Phase 4 itself performs no such reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Status values for `analysis_status`.
STATUS_SUFFICIENT_DATA = "SUFFICIENT_DATA"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# Values for `severity`.
SEVERITY_NORMAL = "NORMAL"
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"


@dataclass
class DetectionResult:
    """
    One temporal-analysis outcome, computed from the most recent
    `analysis_window` rows of `network_measurements`.

    Fields follow the project spec's example model (Section 18) with a
    few additional, clearly-named symptom fields (e.g.
    `gateway_unreachable`, `dns_intermittent`, the six `baseline_*`
    values and `severity_score`) so the GUI and Phase 5 have the
    underlying detail behind each roll-up flag, without changing the
    meaning of any required field.
    """

    # -- Identity / bookkeeping -----------------------------------------
    timestamp: str                       # when this analysis was run (ISO-8601)
    analysis_status: str                 # SUFFICIENT_DATA | INSUFFICIENT_DATA
    window_size: int                     # configured analysis_window
    measurements_analyzed: int           # rows actually available/used

    # -- Overall condition -------------------------------------------------
    degraded: bool                       # any symptom currently active
    intermittent: bool                   # degradation appears/disappears in the window
    persistent: bool                     # degradation is continuous across the whole window
    recovery_observed: bool              # window shows a return to normal after degradation

    # -- Gateway symptoms (NOT a root-cause claim) -----------------------
    gateway_problem: bool
    gateway_unreachable: bool
    gateway_high_latency: bool
    gateway_packet_loss: bool

    # -- Internet symptoms (NOT a root-cause claim) ----------------------
    internet_problem: bool
    internet_unreachable: bool
    internet_high_latency: bool
    internet_packet_loss: bool

    # -- Aggregate latency / packet-loss / jitter symptoms ---------------
    high_latency: bool
    critical_latency: bool
    packet_loss_detected: bool
    critical_packet_loss: bool
    high_jitter: bool

    # -- DNS symptoms -----------------------------------------------------
    dns_degradation: bool
    dns_intermittent: bool
    dns_slow: bool

    # -- HTTP symptoms ------------------------------------------------------
    http_degradation: bool

    # -- Severity -----------------------------------------------------------
    severity: str                        # NORMAL | LOW | MEDIUM | HIGH | CRITICAL
    severity_score: int                  # transparent integer score behind `severity`

    # -- Baselines (median of recent valid values; None if no valid data) --
    baseline_gateway_latency_ms: Optional[float]
    baseline_internet_latency_ms: Optional[float]
    baseline_packet_loss_percent: Optional[float]
    baseline_jitter_ms: Optional[float]
    baseline_dns_response_time_ms: Optional[float]
    baseline_http_response_time_ms: Optional[float]

    # Short, human-readable notes explaining which symptoms fired --
    # purely descriptive (used for logging / GUI tooltips), never a
    # root-cause statement.
    symptoms: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    @staticmethod
    def insufficient_data(timestamp: str, window_size: int, measurements_analyzed: int) -> "DetectionResult":
        """Build the result returned when there isn't enough history yet."""
        return DetectionResult(
            timestamp=timestamp,
            analysis_status=STATUS_INSUFFICIENT_DATA,
            window_size=window_size,
            measurements_analyzed=measurements_analyzed,
            degraded=False,
            intermittent=False,
            persistent=False,
            recovery_observed=False,
            gateway_problem=False,
            gateway_unreachable=False,
            gateway_high_latency=False,
            gateway_packet_loss=False,
            internet_problem=False,
            internet_unreachable=False,
            internet_high_latency=False,
            internet_packet_loss=False,
            high_latency=False,
            critical_latency=False,
            packet_loss_detected=False,
            critical_packet_loss=False,
            high_jitter=False,
            dns_degradation=False,
            dns_intermittent=False,
            dns_slow=False,
            http_degradation=False,
            severity=STATUS_INSUFFICIENT_DATA,
            severity_score=0,
            baseline_gateway_latency_ms=None,
            baseline_internet_latency_ms=None,
            baseline_packet_loss_percent=None,
            baseline_jitter_ms=None,
            baseline_dns_response_time_ms=None,
            baseline_http_response_time_ms=None,
            symptoms=[f"Only {measurements_analyzed} measurement(s) available; {window_size} required."],
        )
