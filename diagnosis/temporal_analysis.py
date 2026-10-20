"""
diagnosis/temporal_analysis.py

Phase 4 module: Temporal Analysis & Fault (Symptom) Detection.

    Measurements (SQLite, Phase 3)
          |
          v
    Recent Time Window (config: analysis_window)
          |
          v
    Temporal Analysis (this module)
          |
          v
    Detect Degradation (symptoms, intermittent/persistent, severity)
          |
          v
    DetectionResult  --------------------------------------> Phase 5 (not built here)

This module answers one question only: "is the network currently
experiencing a persistent or intermittent degradation, and how severe
does that look?". It deliberately never says *why* (no "router fault",
no "ISP problem", no confidence score, no remediation) -- that is
Phase 5's job. Everything here is a transparent, rule-based check over
real rows read from `network_measurements`; no machine learning, no
fabricated data.

Two detection concepts, used throughout:

1. "Aggregate" symptom flags (e.g. `high_latency`, `dns_degradation`)
   describe the whole analysis window, not one row, so that a single
   noisy reading can never flip a flag on its own (Section 6 of the
   spec). Two rules are used, chosen per parameter type:
     - Continuous metrics (latency, packet loss %, jitter, response
       times): "at least half of the recent *valid* values exceed the
       configured threshold".
     - Binary success/failure metrics (gateway/internet reachability,
       DNS success, HTTP success): "the failure occurred at least
       twice in the window" -- one failure is treated as noise, two or
       more is treated as a real, repeated symptom.

2. "Per-measurement" degraded/normal flags describe each row on its
   own (did *this* row cross a threshold or fail?) and are used only to
   detect the *temporal pattern* across the window: alternating
   normal/degraded rows (intermittent), continuously degraded rows
   (persistent), or a return to normal after degradation (recovery).
   This is a separate computation from (1) by design -- a window can
   show a clear intermittent *pattern* built from just two bad rows
   out of six, well below the "at least half" bar used for the
   aggregate flags.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.database import Database
from diagnosis.diagnosis_models import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_NORMAL,
    STATUS_SUFFICIENT_DATA,
    DetectionResult,
)
from utils.config_loader import load_settings
from utils.logger import get_logger

logger = get_logger(__name__)

# A binary symptom (a failure/unreachable reading) is only treated as a
# real, repeated problem once it has happened at least this many times
# in the window -- a single failure is treated as noise (Section 6).
_MIN_REPEATED_FAILURES = 2

_DEFAULT_ANALYSIS_WINDOW = 6

_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "high_latency_ms": 200,
    "critical_latency_ms": 500,
    "packet_loss_percent": 10,
    "critical_packet_loss_percent": 30,
    "high_jitter_ms": 50,
    "high_dns_response_ms": 500,
    "high_http_response_ms": 3000,
}


# ---------------------------------------------------------------------------
# Configuration helpers -- nothing below this point ever hardcodes a
# threshold or window size; everything is read from config/settings.json
# via utils.config_loader, with the module-level defaults above used only
# if a key is genuinely absent from settings.
# ---------------------------------------------------------------------------

def _get_analysis_window(settings: Dict[str, Any]) -> int:
    try:
        window = int(settings.get("analysis_window", _DEFAULT_ANALYSIS_WINDOW))
    except (TypeError, ValueError):
        logger.warning("Invalid analysis_window in settings; falling back to default.")
        window = _DEFAULT_ANALYSIS_WINDOW
    return max(1, window)


def _get_thresholds(settings: Dict[str, Any]) -> Dict[str, float]:
    thresholds = dict(_DEFAULT_THRESHOLDS)
    configured = settings.get("thresholds", {})
    if isinstance(configured, dict):
        thresholds.update(configured)
    else:
        logger.warning("Invalid 'thresholds' in settings; using defaults.")
    return thresholds


# ---------------------------------------------------------------------------
# Small, generic numeric helpers
# ---------------------------------------------------------------------------

def _valid_numbers(values: List[Any]) -> List[float]:
    """Drop None/missing entries. Never fabricates a substitute value."""
    return [float(v) for v in values if v is not None]


def _median_or_none(values: List[Any]) -> Optional[float]:
    valid = _valid_numbers(values)
    if not valid:
        return None
    return round(statistics.median(valid), 2)


def _at_least_half_exceed(values: List[Any], threshold: float) -> bool:
    """
    Aggregate rule for continuous metrics: True only when at least half
    of the recent *valid* measurements exceed `threshold`. A single
    abnormal reading can never satisfy this on its own once the window
    holds more than one valid value.
    """
    valid = _valid_numbers(values)
    if not valid:
        return False
    exceed_count = sum(1 for v in valid if v > threshold)
    return exceed_count >= (len(valid) / 2)


def _repeated_failures(is_failure_flags: List[bool]) -> bool:
    """
    Aggregate rule for binary success/failure metrics: True once a
    failure has occurred at least `_MIN_REPEATED_FAILURES` times in the
    window. One isolated failure is treated as noise.
    """
    return sum(1 for f in is_failure_flags if f) >= _MIN_REPEATED_FAILURES


# ---------------------------------------------------------------------------
# Per-measurement (row-level) degraded/normal classification, used only
# for the temporal pattern (intermittent/persistent/recovery) detection.
# ---------------------------------------------------------------------------

def _row_is_degraded(row: Dict[str, Any], thresholds: Dict[str, float]) -> bool:
    """
    Does this single measurement, on its own, show at least one
    threshold-crossing or failure? Used only to build the chronological
    normal/degraded sequence for pattern detection -- never surfaced on
    its own as a reported symptom (that would violate the "not because
    of one abnormal measurement" rule).
    """
    if row.get("gateway_reachable") == 0:
        return True
    if row.get("internet_reachable") == 0:
        return True

    gateway_latency = row.get("gateway_latency_ms")
    if gateway_latency is not None and gateway_latency > thresholds["high_latency_ms"]:
        return True

    internet_latency = row.get("internet_latency_ms")
    if internet_latency is not None and internet_latency > thresholds["high_latency_ms"]:
        return True

    gateway_loss = row.get("gateway_packet_loss")
    if gateway_loss is not None and gateway_loss > thresholds["packet_loss_percent"]:
        return True

    internet_loss = row.get("internet_packet_loss")
    if internet_loss is not None and internet_loss > thresholds["packet_loss_percent"]:
        return True

    jitter = row.get("jitter_ms")
    if jitter is not None and jitter > thresholds["high_jitter_ms"]:
        return True

    if row.get("dns_success") == 0:
        return True

    dns_time = row.get("dns_response_time_ms")
    if dns_time is not None and dns_time > thresholds["high_dns_response_ms"]:
        return True

    http_status = row.get("http_status_code")
    if http_status is None or http_status >= 400:
        return True

    http_time = row.get("http_response_time_ms")
    if http_time is not None and http_time > thresholds["high_http_response_ms"]:
        return True

    return False


def _count_degraded_runs(flags: List[bool]) -> int:
    """Number of separate contiguous degraded blocks in a chronological
    True/False sequence, e.g. [F,F,T,T,F,T] -> 2 runs."""
    runs = 0
    previous = False
    for flag in flags:
        if flag and not previous:
            runs += 1
        previous = flag
    return runs


@dataclass
class _TemporalPattern:
    persistent: bool
    intermittent: bool
    recovery_observed: bool


def _detect_temporal_pattern(chronological_flags: List[bool]) -> _TemporalPattern:
    """
    Classify the chronological (oldest-first) sequence of per-row
    degraded/normal flags into NORMAL / INTERMITTENT / PERSISTENT, plus
    a separate recovery observation. See the module docstring for the
    rules; briefly:

      - persistent  : every measurement in the window is degraded
                       (Section 14 example: 6/6 degraded).
      - intermittent: degradation appears in 2+ separate runs, i.e. it
                       comes and goes more than once (Section 13
                       example: normal/degraded/normal/degraded...).
      - recovery    : the most recent measurement is normal, but at
                       least one earlier measurement in the window was
                       degraded (Section 15 example: degraded then a
                       return to normal).
    """
    if not chronological_flags:
        return _TemporalPattern(persistent=False, intermittent=False, recovery_observed=False)

    all_degraded = all(chronological_flags)
    run_count = _count_degraded_runs(chronological_flags)

    persistent = all_degraded
    intermittent = (not persistent) and run_count >= 2
    recovery_observed = (not chronological_flags[-1]) and any(chronological_flags[:-1])

    return _TemporalPattern(persistent=persistent, intermittent=intermittent, recovery_observed=recovery_observed)


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

def _calculate_severity(
    *,
    high_latency: bool,
    critical_latency: bool,
    packet_loss_detected: bool,
    critical_packet_loss: bool,
    high_jitter: bool,
    dns_degradation: bool,
    http_degradation: bool,
    gateway_unreachable: bool,
    internet_unreachable: bool,
    persistent: bool,
    intermittent: bool,
) -> "tuple[str, int]":
    """
    Transparent, additive point score -> severity band. Every point is
    attached to one concrete, already-detected symptom -- nothing here
    is a subjective judgement call.

        +1  high_latency               +1  packet_loss_detected
        +2  critical_latency           +2  critical_packet_loss
        +1  high_jitter
        +1  dns_degradation            +1  http_degradation
        +2  gateway_unreachable        +2  internet_unreachable
        +1  intermittent_degradation   +2  persistent_degradation

    Score -> severity:
        0        -> NORMAL
        1        -> LOW
        2 - 3    -> MEDIUM
        4 - 5    -> HIGH
        6+       -> CRITICAL

    A total connectivity failure (both gateway and internet unreachable
    *and* that unreachability is persistent across the whole window) is
    always forced to CRITICAL, matching "severe repeated connectivity
    failure" from the spec, even if the additive score alone would land
    it in HIGH.
    """
    score = 0
    score += 1 if high_latency else 0
    score += 2 if critical_latency else 0
    score += 1 if packet_loss_detected else 0
    score += 2 if critical_packet_loss else 0
    score += 1 if high_jitter else 0
    score += 1 if dns_degradation else 0
    score += 1 if http_degradation else 0
    score += 2 if gateway_unreachable else 0
    score += 2 if internet_unreachable else 0
    score += 1 if intermittent else 0
    score += 2 if persistent else 0

    full_outage = gateway_unreachable and internet_unreachable and persistent
    if full_outage:
        score = max(score, 6)

    if score <= 0:
        severity = SEVERITY_NORMAL
    elif score == 1:
        severity = SEVERITY_LOW
    elif score <= 3:
        severity = SEVERITY_MEDIUM
    elif score <= 5:
        severity = SEVERITY_HIGH
    else:
        severity = SEVERITY_CRITICAL

    return severity, score


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def analyze_measurements(
    rows_newest_first: List[Dict[str, Any]],
    settings: Optional[Dict[str, Any]] = None,
) -> DetectionResult:
    """
    Core Phase 4 logic, given already-fetched rows (newest first, the
    same order `Database.get_recent_measurements()` returns). Kept
    separate from `analyze_recent_measurements()` so it can be unit
    tested with simulated rows without touching SQLite (Section 22).

    Steps (matches Section 19 of the spec):
        1. (caller already read recent measurements)
        2. Check whether enough data exists.
        3. Calculate baselines.
        4-10. Analyze latency / packet loss / jitter / gateway /
              internet / DNS / HTTP.
        11-12. Detect intermittent / persistent degradation.
        13. Detect recovery observation.
        14. Calculate severity.
        15. Return a DetectionResult.
    """
    settings = settings if settings is not None else load_settings()
    window_size = _get_analysis_window(settings)
    thresholds = _get_thresholds(settings)
    now_iso = datetime.now().isoformat(timespec="seconds")

    logger.info("Temporal analysis started (window=%d, available=%d).", window_size, len(rows_newest_first))

    # ---- Step 2: sufficient data? -------------------------------------
    if len(rows_newest_first) < window_size:
        logger.info(
            "Temporal analysis: insufficient data (%d/%d measurements).",
            len(rows_newest_first), window_size,
        )
        return DetectionResult.insufficient_data(now_iso, window_size, len(rows_newest_first))

    window_rows = rows_newest_first[:window_size]
    chronological_rows = list(reversed(window_rows))  # oldest -> newest, for pattern detection

    # ---- Step 3: baselines (median of recent valid values) -------------
    baseline_gateway_latency = _median_or_none([r.get("gateway_latency_ms") for r in window_rows])
    baseline_internet_latency = _median_or_none([r.get("internet_latency_ms") for r in window_rows])
    baseline_packet_loss = _median_or_none([r.get("internet_packet_loss") for r in window_rows])
    baseline_jitter = _median_or_none([r.get("jitter_ms") for r in window_rows])
    baseline_dns_response = _median_or_none([r.get("dns_response_time_ms") for r in window_rows])
    baseline_http_response = _median_or_none([r.get("http_response_time_ms") for r in window_rows])

    # ---- Step 4/9/10: latency (gateway + internet) ----------------------
    gateway_latencies = [r.get("gateway_latency_ms") for r in window_rows]
    internet_latencies = [r.get("internet_latency_ms") for r in window_rows]

    gateway_high_latency = _at_least_half_exceed(gateway_latencies, thresholds["high_latency_ms"])
    gateway_critical_latency = _at_least_half_exceed(gateway_latencies, thresholds["critical_latency_ms"])
    internet_high_latency = _at_least_half_exceed(internet_latencies, thresholds["high_latency_ms"])
    internet_critical_latency = _at_least_half_exceed(internet_latencies, thresholds["critical_latency_ms"])

    high_latency = gateway_high_latency or internet_high_latency
    critical_latency = gateway_critical_latency or internet_critical_latency
    if high_latency:
        logger.info("Temporal analysis: high latency detected.")
    if critical_latency:
        logger.info("Temporal analysis: critical latency detected.")

    # ---- Step 5/9/10: packet loss (gateway + internet) ------------------
    gateway_losses = [r.get("gateway_packet_loss") for r in window_rows]
    internet_losses = [r.get("internet_packet_loss") for r in window_rows]

    gateway_packet_loss = _at_least_half_exceed(gateway_losses, thresholds["packet_loss_percent"])
    gateway_critical_packet_loss = _at_least_half_exceed(gateway_losses, thresholds["critical_packet_loss_percent"])
    internet_packet_loss = _at_least_half_exceed(internet_losses, thresholds["packet_loss_percent"])
    internet_critical_packet_loss = _at_least_half_exceed(internet_losses, thresholds["critical_packet_loss_percent"])

    packet_loss_detected = gateway_packet_loss or internet_packet_loss
    critical_packet_loss = gateway_critical_packet_loss or internet_critical_packet_loss
    if packet_loss_detected:
        logger.info("Temporal analysis: packet loss detected.")

    # ---- Step 6: jitter ---------------------------------------------------
    jitters = [r.get("jitter_ms") for r in window_rows]
    high_jitter = _at_least_half_exceed(jitters, thresholds["high_jitter_ms"])
    if high_jitter:
        logger.info("Temporal analysis: high jitter detected.")

    # ---- Step 7: gateway reachability -------------------------------------
    gateway_unreachable_flags = [r.get("gateway_reachable") == 0 for r in window_rows]
    gateway_unreachable = _repeated_failures(gateway_unreachable_flags)

    # ---- Step 8: internet reachability -----------------------------------
    internet_unreachable_flags = [r.get("internet_reachable") == 0 for r in window_rows]
    internet_unreachable = _repeated_failures(internet_unreachable_flags)

    gateway_problem = gateway_unreachable or gateway_high_latency or gateway_packet_loss
    internet_problem = internet_unreachable or internet_high_latency or internet_packet_loss

    # ---- Step 9: DNS --------------------------------------------------------
    dns_failure_flags = [r.get("dns_success") == 0 for r in window_rows]
    dns_success_count = sum(1 for f in dns_failure_flags if not f)
    dns_failure_count = sum(1 for f in dns_failure_flags if f)
    dns_degradation = _repeated_failures(dns_failure_flags)
    dns_intermittent = dns_degradation and dns_success_count > 0 and dns_failure_count > 0

    dns_response_times = [
        r.get("dns_response_time_ms") for r in window_rows if r.get("dns_success") == 1
    ]
    dns_slow = _at_least_half_exceed(dns_response_times, thresholds["high_dns_response_ms"])
    if dns_degradation:
        logger.info("Temporal analysis: DNS degradation detected.")

    # ---- Step 10: HTTP -------------------------------------------------------
    http_failure_flags = [
        (r.get("http_status_code") is None) or (r.get("http_status_code") >= 400)
        for r in window_rows
    ]
    http_repeated_failures = _repeated_failures(http_failure_flags)
    http_response_times = [
        r.get("http_response_time_ms")
        for r, failed in zip(window_rows, http_failure_flags)
        if not failed
    ]
    http_slow = _at_least_half_exceed(http_response_times, thresholds["high_http_response_ms"])
    http_degradation = http_repeated_failures or http_slow
    if http_degradation:
        logger.info("Temporal analysis: HTTP degradation detected.")

    # ---- Steps 11-13: intermittent / persistent / recovery ----------------
    row_degraded_flags = [_row_is_degraded(r, thresholds) for r in chronological_rows]
    pattern = _detect_temporal_pattern(row_degraded_flags)
    if pattern.intermittent:
        logger.info("Temporal analysis: intermittent degradation detected.")
    if pattern.persistent:
        logger.info("Temporal analysis: persistent degradation detected.")
    if pattern.recovery_observed:
        logger.info("Temporal analysis: recovery observed.")

    degraded = any(
        [
            gateway_problem, internet_problem, high_latency, critical_latency,
            packet_loss_detected, critical_packet_loss, high_jitter,
            dns_degradation, http_degradation, pattern.persistent, pattern.intermittent,
        ]
    )

    # ---- Step 14: severity --------------------------------------------------
    severity, severity_score = _calculate_severity(
        high_latency=high_latency,
        critical_latency=critical_latency,
        packet_loss_detected=packet_loss_detected,
        critical_packet_loss=critical_packet_loss,
        high_jitter=high_jitter,
        dns_degradation=dns_degradation,
        http_degradation=http_degradation,
        gateway_unreachable=gateway_unreachable,
        internet_unreachable=internet_unreachable,
        persistent=pattern.persistent,
        intermittent=pattern.intermittent,
    )
    logger.info("Temporal analysis: severity calculated as %s (score=%d).", severity, severity_score)

    symptoms: List[str] = []
    if gateway_unreachable:
        symptoms.append("Gateway unreachable on multiple recent checks.")
    if internet_unreachable:
        symptoms.append("Internet host unreachable on multiple recent checks.")
    if high_latency:
        symptoms.append("Latency repeatedly above the high-latency threshold.")
    if critical_latency:
        symptoms.append("Latency repeatedly above the critical-latency threshold.")
    if packet_loss_detected:
        symptoms.append("Packet loss repeatedly above the configured threshold.")
    if critical_packet_loss:
        symptoms.append("Packet loss repeatedly above the critical threshold.")
    if high_jitter:
        symptoms.append("Jitter repeatedly above the configured threshold.")
    if dns_degradation:
        symptoms.append("Repeated DNS resolution failures.")
    if dns_slow:
        symptoms.append("DNS resolution repeatedly slow.")
    if http_degradation:
        symptoms.append("Repeated HTTP failures or slow responses.")
    if pattern.persistent:
        symptoms.append("Degradation is continuous across the whole analysis window.")
    if pattern.intermittent:
        symptoms.append("Degradation appears and disappears within the analysis window.")
    if pattern.recovery_observed:
        symptoms.append("Network appears to have recovered after an earlier degraded period.")

    return DetectionResult(
        timestamp=now_iso,
        analysis_status=STATUS_SUFFICIENT_DATA,
        window_size=window_size,
        measurements_analyzed=len(window_rows),
        degraded=degraded,
        intermittent=pattern.intermittent,
        persistent=pattern.persistent,
        recovery_observed=pattern.recovery_observed,
        gateway_problem=gateway_problem,
        gateway_unreachable=gateway_unreachable,
        gateway_high_latency=gateway_high_latency,
        gateway_packet_loss=gateway_packet_loss,
        internet_problem=internet_problem,
        internet_unreachable=internet_unreachable,
        internet_high_latency=internet_high_latency,
        internet_packet_loss=internet_packet_loss,
        high_latency=high_latency,
        critical_latency=critical_latency,
        packet_loss_detected=packet_loss_detected,
        critical_packet_loss=critical_packet_loss,
        high_jitter=high_jitter,
        dns_degradation=dns_degradation,
        dns_intermittent=dns_intermittent,
        dns_slow=dns_slow,
        http_degradation=http_degradation,
        severity=severity,
        severity_score=severity_score,
        baseline_gateway_latency_ms=baseline_gateway_latency,
        baseline_internet_latency_ms=baseline_internet_latency,
        baseline_packet_loss_percent=baseline_packet_loss,
        baseline_jitter_ms=baseline_jitter,
        baseline_dns_response_time_ms=baseline_dns_response,
        baseline_http_response_time_ms=baseline_http_response,
        symptoms=symptoms,
    )


def analyze_recent_measurements(
    database: Database,
    settings: Optional[Dict[str, Any]] = None,
) -> DetectionResult:
    """
    Public Phase 4 entry point used by the GUI (and, later, Phase 5):
    reads the most recent `analysis_window` rows straight from the
    existing `network_measurements` table -- no second database, no
    fabricated data -- and runs the full temporal analysis over them.
    """
    settings = settings if settings is not None else load_settings()
    window_size = _get_analysis_window(settings)

    try:
        rows_newest_first = database.get_recent_measurements(limit=window_size)
    except Exception as exc:  # noqa: BLE001 - analysis must never crash the caller (GUI)
        logger.exception("Temporal analysis: could not read recent measurements: %s", exc)
        rows_newest_first = []

    return analyze_measurements(rows_newest_first, settings=settings)


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # SIMULATED TEST DATA -- exercises the scenarios from Section 22 of
    # the spec without touching the real database or requiring an
    # actual network fault. Every row below is clearly synthetic.
    # ------------------------------------------------------------------
    def _row(
        gw_reachable=1, gw_latency=5.0, gw_loss=0.0,
        net_reachable=1, net_latency=20.0, net_loss=0.0,
        jitter=3.0, dns_ok=1, dns_ms=10.0, http_code=200, http_ms=150.0,
    ) -> Dict[str, Any]:
        return {
            "gateway_reachable": gw_reachable, "gateway_latency_ms": gw_latency, "gateway_packet_loss": gw_loss,
            "internet_reachable": net_reachable, "internet_latency_ms": net_latency, "internet_packet_loss": net_loss,
            "jitter_ms": jitter,
            "dns_success": dns_ok, "dns_response_time_ms": dns_ms,
            "http_status_code": http_code, "http_response_time_ms": http_ms,
        }

    test_settings = {"analysis_window": 6, "thresholds": dict(_DEFAULT_THRESHOLDS)}

    scenarios = {
        "Test 1 - Normal": [_row() for _ in range(6)],
        "Test 2 - High latency": [_row(net_latency=v) for v in (250, 280, 300, 275, 290, 310)],
        "Test 3 - Packet loss": [_row(net_loss=v) for v in (0, 15, 20, 25, 18, 22)],
        "Test 4 - DNS degradation": [
            _row(dns_ok=1), _row(dns_ok=1), _row(dns_ok=0, dns_ms=None),
            _row(dns_ok=0, dns_ms=None), _row(dns_ok=1), _row(dns_ok=0, dns_ms=None),
        ],
        "Test 5 - Intermittent": [
            _row(), _row(), _row(net_latency=300), _row(net_loss=25), _row(), _row(net_latency=300),
        ],
        "Test 6 - Persistent": [_row(net_latency=300) for _ in range(6)],
        "Test 7 - Recovery": [
            _row(), _row(net_loss=25), _row(net_loss=25), _row(), _row(),
        ],
    }
    # Test 7 only has 5 rows on purpose -> pad to the window size with a
    # trailing normal reading (still clearly-labeled simulated data).
    scenarios["Test 7 - Recovery"].append(_row())

    print("SIMULATED TEST DATA -- diagnosis/temporal_analysis.py self-test\n")
    for name, chronological in scenarios.items():
        newest_first = list(reversed(chronological))
        result = analyze_measurements(newest_first, settings=test_settings)
        print(f"{name}:")
        print(f"  status={result.analysis_status} degraded={result.degraded} "
              f"intermittent={result.intermittent} persistent={result.persistent} "
              f"recovery={result.recovery_observed}")
        print(f"  high_latency={result.high_latency} packet_loss_detected={result.packet_loss_detected} "
              f"dns_degradation={result.dns_degradation} http_degradation={result.http_degradation}")
        print(f"  severity={result.severity} (score={result.severity_score})\n")
