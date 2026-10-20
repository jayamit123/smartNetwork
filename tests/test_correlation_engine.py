
import unittest

from diagnosis.diagnosis_models import DetectionResult
from diagnosis.correlation_engine import correlate_symptoms


def make_detection(**overrides):
    values = dict(
        timestamp="2026-10-19T22:00:00",
        analysis_status="SUFFICIENT_DATA",
        window_size=10,
        measurements_analyzed=10,
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
        severity="NORMAL",
        severity_score=0,
        baseline_gateway_latency_ms=2.0,
        baseline_internet_latency_ms=20.0,
        baseline_packet_loss_percent=0.0,
        baseline_jitter_ms=1.0,
        baseline_dns_response_time_ms=10.0,
        baseline_http_response_time_ms=100.0,
    )
    values.update(overrides)
    return DetectionResult(**values)


class CorrelationEngineTests(unittest.TestCase):

    def test_insufficient_data(self):
        detection = DetectionResult.insufficient_data(
            "2026-10-19T22:00:00", 10, 2
        )
        result = correlate_symptoms(detection, {})
        self.assertEqual(result.status, "INSUFFICIENT_DATA")
        self.assertEqual(result.probable_category, "UNDETERMINED")

    def test_gateway_failure(self):
        detection = make_detection(gateway_unreachable=True)
        result = correlate_symptoms(
            detection,
            {"gateway_reachable": 0}
        )
        self.assertEqual(
            result.probable_category,
            "LOCAL_GATEWAY_CONNECTIVITY"
        )

    def test_dns_failure(self):
        detection = make_detection(dns_degradation=True)
        result = correlate_symptoms(
            detection,
            {"gateway_reachable": 1, "dns_success": 0}
        )
        self.assertEqual(result.probable_category, "DNS_RESOLUTION")

    def test_internet_path_failure(self):
        detection = make_detection(internet_unreachable=True)
        result = correlate_symptoms(
            detection,
            {"gateway_reachable": 1, "internet_reachable": 0}
        )
        self.assertEqual(
            result.probable_category,
            "INTERNET_PATH_CONNECTIVITY"
        )

    def test_high_latency(self):
        detection = make_detection(high_latency=True)
        result = correlate_symptoms(detection, {})
        self.assertEqual(
            result.probable_category,
            "NETWORK_PERFORMANCE_DEGRADATION"
        )

    def test_normal_network(self):
        detection = make_detection()
        result = correlate_symptoms(detection, {})
        self.assertEqual(
            result.probable_category,
            "NO_PERSISTENT_DEGRADATION_DETECTED"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
