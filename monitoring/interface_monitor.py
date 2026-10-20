"""
monitoring/interface_monitor.py

Phase 1 module.

Thin wrapper around utils.network_utils that the GUI (and, starting in
Phase 2, the continuous Monitoring Controller) uses to obtain the current
network-interface snapshot. Keeping this as its own module -- rather than
having the GUI call utils.network_utils directly -- means Phase 2 can later
extend InterfaceMonitor with caching / change-detection without touching
the GUI code.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Dict

from utils.logger import get_logger
from utils.network_utils import NetworkInfo, get_network_info

logger = get_logger(__name__)


class InterfaceMonitor:
    """Provides on-demand snapshots of the machine's network configuration."""

    def __init__(self) -> None:
        self._last_snapshot: NetworkInfo = NetworkInfo()

    def refresh(self) -> NetworkInfo:
        """
        Re-detect the current network configuration and remember it as the
        last known snapshot. Never raises: network_utils.get_network_info()
        already guarantees a safe, non-throwing result.
        """
        self._last_snapshot = get_network_info()
        logger.debug("Interface snapshot refreshed: %s", self._last_snapshot)
        return self._last_snapshot

    @property
    def last_snapshot(self) -> NetworkInfo:
        return self._last_snapshot

    def as_dict(self) -> Dict:
        """Convenience for logging / future JSON export."""
        return asdict(self._last_snapshot)


if __name__ == "__main__":
    monitor = InterfaceMonitor()
    snapshot = monitor.refresh()
    print(snapshot)
