"""
diagnosis/

Phase 4 package: Temporal Analysis & Fault (Symptom) Detection.

This package looks at *several* recent rows from the existing
`network_measurements` SQLite table (Phase 3) and decides whether the
network is currently showing a persistent or intermittent degradation.
It never inspects a single measurement in isolation and it never names a
root cause (e.g. "router is faulty", "ISP problem") -- that
classification step is left for Phase 5, which will consume the
`DetectionResult` produced here.

Public API:
    from diagnosis.temporal_analysis import analyze_recent_measurements
    from diagnosis.diagnosis_models import DetectionResult
"""

from diagnosis.diagnosis_models import DetectionResult
from diagnosis.temporal_analysis import analyze_recent_measurements

__all__ = ["DetectionResult", "analyze_recent_measurements"]
