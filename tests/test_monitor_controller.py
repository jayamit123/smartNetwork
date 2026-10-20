import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from monitoring.monitor_controller import MonitorController


class MonitorControllerTests(unittest.TestCase):
    def test_network_probes_run_concurrently_in_one_round(self):
        controller = MonitorController(settings={}, database=None)
        controller._interface_monitor.refresh = lambda: SimpleNamespace(
            interface="test0",
            ipv4="192.0.2.2",
            gateway="192.0.2.1",
        )
        probe_barrier = threading.Barrier(4)

        def meet_other_probes():
            probe_barrier.wait(timeout=2)

        def gateway_probe(*args, **kwargs):
            meet_other_probes()
            return SimpleNamespace(
                reachable=True,
                latency_avg_ms=1.0,
                latency_min_ms=1.0,
                latency_max_ms=1.0,
                packet_loss_percent=0.0,
            )

        def internet_probe(*args, **kwargs):
            meet_other_probes()
            return SimpleNamespace(
                reachable=True,
                latency_avg_ms=10.0,
                latency_min_ms=10.0,
                latency_max_ms=10.0,
                packet_loss_percent=0.0,
                jitter_ms=0.0,
                estimated_bytes_used=128,
            )

        def dns_probe(*args, **kwargs):
            meet_other_probes()
            return SimpleNamespace(success=True, response_time_ms=2.0, resolved_address="192.0.2.3")

        def http_probe(*args, **kwargs):
            meet_other_probes()
            return SimpleNamespace(
                success=True,
                status_code=200,
                response_time_ms=20.0,
                estimated_bytes_used=512,
            )

        with (
            patch("monitoring.monitor_controller.check_gateway", side_effect=gateway_probe),
            patch("monitoring.monitor_controller.check_internet", side_effect=internet_probe),
            patch("monitoring.monitor_controller.check_dns", side_effect=dns_probe),
            patch("monitoring.monitor_controller.check_http", side_effect=http_probe),
        ):
            measurement = controller._collect_one_round()

        self.assertEqual(measurement.interface_name, "test0")
        self.assertEqual(measurement.gateway_reachable, 1)
        self.assertEqual(measurement.internet_reachable, 1)
        self.assertEqual(measurement.dns_success, 1)
        self.assertEqual(measurement.http_status_code, 200)

    def test_interface_snapshot_is_cached_between_monitoring_ticks(self):
        controller = MonitorController(settings={}, database=None)
        snapshot = SimpleNamespace(interface="test0", ipv4="192.0.2.2", gateway=None)
        with (
            patch.object(controller._interface_monitor, "refresh", return_value=snapshot) as refresh,
            patch("monitoring.monitor_controller.check_gateway") as gateway,
            patch("monitoring.monitor_controller.check_internet") as internet,
            patch("monitoring.monitor_controller.check_dns") as dns,
            patch("monitoring.monitor_controller.check_http") as http,
        ):
            gateway.return_value = SimpleNamespace(
                reachable=False,
                latency_avg_ms=None,
                latency_min_ms=None,
                latency_max_ms=None,
                packet_loss_percent=100.0,
            )
            internet.return_value = SimpleNamespace(
                reachable=True,
                latency_avg_ms=10.0,
                latency_min_ms=10.0,
                latency_max_ms=10.0,
                packet_loss_percent=0.0,
                jitter_ms=0.0,
                estimated_bytes_used=128,
            )
            dns.return_value = SimpleNamespace(success=True, response_time_ms=2.0, resolved_address="192.0.2.3")
            http.return_value = SimpleNamespace(
                success=True,
                status_code=200,
                response_time_ms=20.0,
                estimated_bytes_used=512,
            )

            controller._collect_one_round()
            controller._collect_one_round()

        refresh.assert_called_once_with()

    def test_jitter_is_computed_from_consecutive_one_ping_cycles(self):
        controller = MonitorController(settings={}, database=None)
        snapshot = SimpleNamespace(interface="test0", ipv4="192.0.2.2", gateway="192.0.2.1")
        gateway_result = SimpleNamespace(
            reachable=True,
            latency_avg_ms=1.0,
            latency_min_ms=1.0,
            latency_max_ms=1.0,
            packet_loss_percent=0.0,
        )
        internet_results = [
            SimpleNamespace(
                reachable=True,
                latency_avg_ms=10.0,
                latency_min_ms=10.0,
                latency_max_ms=10.0,
                packet_loss_percent=0.0,
                jitter_ms=None,
                estimated_bytes_used=128,
            ),
            SimpleNamespace(
                reachable=True,
                latency_avg_ms=16.5,
                latency_min_ms=16.5,
                latency_max_ms=16.5,
                packet_loss_percent=0.0,
                jitter_ms=None,
                estimated_bytes_used=128,
            ),
        ]
        dns_result = SimpleNamespace(success=True, response_time_ms=2.0, resolved_address="192.0.2.3")
        http_result = SimpleNamespace(
            success=True,
            status_code=200,
            response_time_ms=20.0,
            estimated_bytes_used=512,
        )
        with (
            patch.object(controller._interface_monitor, "refresh", return_value=snapshot),
            patch("monitoring.monitor_controller.check_gateway", return_value=gateway_result),
            patch(
                "monitoring.monitor_controller.check_internet",
                side_effect=internet_results,
            ),
            patch("monitoring.monitor_controller.check_dns", return_value=dns_result),
            patch("monitoring.monitor_controller.check_http", return_value=http_result),
        ):
            first = controller._collect_one_round()
            second = controller._collect_one_round()

        self.assertIsNone(first.jitter_ms)
        self.assertEqual(second.jitter_ms, 6.5)


if __name__ == "__main__":
    unittest.main()
