
"""
Phase 5: Multi-parameter correlation engine.

Combines Phase 4 temporal symptoms with the latest measurements.
It identifies probable symptom categories, not guaranteed root causes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from diagnosis.diagnosis_models import DetectionResult


@dataclass
class CorrelationResult:
    status: str
    probable_category: str
    evidence: List[str] = field(default_factory=list)
    correlated_symptoms: List[str] = field(default_factory=list)


def _as_bool(value: Any) -> Any:
    """Convert common database boolean values safely."""
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        value = value.strip().lower()

        if value in ("1", "true", "yes", "success", "reachable"):
            return True

        if value in ("0", "false", "no", "failure", "unreachable"):
            return False

    return None


def correlate_symptoms(
    detection: DetectionResult,
    latest: Dict[str, Any],
) -> CorrelationResult:
    """Correlate recent temporal symptoms with current measurements."""

    if detection.analysis_status != "SUFFICIENT_DATA":
        return CorrelationResult(
            status="INSUFFICIENT_DATA",
            probable_category="UNDETERMINED",
            evidence=[
                "Collect more network measurements before drawing a conclusion."
            ],
            correlated_symptoms=[],
        )

    evidence: List[str] = []
    symptoms: List[str] = []

    gateway_ok = _as_bool(latest.get("gateway_reachable"))
    internet_ok = _as_bool(latest.get("internet_reachable"))
    dns_ok = _as_bool(latest.get("dns_success"))

    http_code = latest.get("http_status_code")
    try:
        http_code = int(http_code) if http_code is not None else None
    except (TypeError, ValueError):
        http_code = None

    # Record the symptoms detected by Phase 4.
    symptom_checks = [
        (
            detection.gateway_problem,
            "gateway_problem",
            "Repeated gateway-related symptoms were detected.",
        ),
        (
            detection.internet_problem,
            "internet_problem",
            "Repeated internet reachability, latency, or packet-loss symptoms were detected.",
        ),
        (
            detection.dns_degradation,
            "dns_degradation",
            "Repeated DNS degradation was detected in the analysis window.",
        ),
        (
            detection.http_degradation,
            "http_degradation",
            "Repeated HTTP connectivity degradation was detected.",
        ),
        (
            detection.high_latency,
            "high_latency",
            "High latency was detected in recent measurements.",
        ),
        (
            detection.packet_loss_detected,
            "packet_loss",
            "Repeated packet loss was detected.",
        ),
        (
            detection.high_jitter,
            "high_jitter",
            "High delay variation was detected.",
        ),
    ]

    for active, symptom_name, explanation in symptom_checks:
        if active:
            symptoms.append(symptom_name)
            evidence.append(explanation)

    # Select a probable category using current and historical indicators.
    # This is a diagnostic hypothesis, not proof of a physical root cause.
    if detection.gateway_unreachable or gateway_ok is False:
        category = "LOCAL_GATEWAY_CONNECTIVITY"
        evidence.append(
            "The gateway was reported unreachable in the recent analysis "
            "or latest measurement."
        )

    elif detection.dns_degradation and dns_ok is False:
        category = "DNS_RESOLUTION"
        evidence.append(
            "DNS degradation and a failed latest DNS check were observed."
        )

    elif (
        (internet_ok is False or detection.internet_unreachable)
        and gateway_ok is not False
        and not detection.gateway_unreachable
    ):
        category = "INTERNET_PATH_CONNECTIVITY"
        evidence.append(
            "Internet reachability failed while no gateway failure was "
            "confirmed by the available indicators."
        )

    elif (
        http_code is not None
        and not 200 <= http_code < 400
        and dns_ok is True
    ):
        category = "HTTP_DESTINATION_OR_SERVICE"
        evidence.append(
            f"The latest HTTP status code was {http_code}, while DNS succeeded. "
            "The destination service or HTTP path may need checking."
        )

    elif (
        detection.high_latency
        or detection.packet_loss_detected
        or detection.high_jitter
    ):
        category = "NETWORK_PERFORMANCE_DEGRADATION"
        evidence.append(
            "One or more latency, packet-loss, or jitter indicators were detected."
        )

    elif detection.degraded:
        category = "OTHER_OR_MIXED_DEGRADATION"
        evidence.append(
            "Degradation was detected, but the available indicators do not "
            "strongly identify one specific category."
        )

    else:
        category = "NO_PERSISTENT_DEGRADATION_DETECTED"
        evidence.append(
            "No active degradation was identified by the current temporal analysis."
        )

    return CorrelationResult(
        status="ANALYZED",
        probable_category=category,
        evidence=evidence,
        correlated_symptoms=symptoms,
    )
