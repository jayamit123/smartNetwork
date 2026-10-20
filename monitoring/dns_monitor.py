"""
monitoring/dns_monitor.py

Checks DNS availability using the operating system resolver.
Preserves the DnsResult interface used by the monitoring system.
"""

from __future__ import annotations

import time
import socket
import threading
from dataclasses import dataclass
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_lookup_lock = threading.Lock()


@dataclass
class DnsResult:
    success: bool
    status: str
    response_time_ms: Optional[float]
    resolved_address: Optional[str] = None
    error: str = ""


@dataclass
class _Lookup:
    domain: str
    completed: threading.Event
    addresses: List[str]
    error: str = ""


_active_lookup: Optional[_Lookup] = None


def _run_lookup(lookup: _Lookup) -> None:
    global _active_lookup
    try:
        answers = socket.getaddrinfo(
            lookup.domain,
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        lookup.addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    except OSError as exc:
        lookup.error = str(exc)
    finally:
        with _lookup_lock:
            if _active_lookup is lookup:
                _active_lookup = None
        lookup.completed.set()


def check_dns(domain: str, timeout_seconds: float = 3.0) -> DnsResult:
    """
    Resolve an A record through the operating system resolver. A single
    daemon lookup thread keeps a stalled system resolver from blocking a
    monitoring tick or accumulating unbounded threads.
    """
    start = time.monotonic()
    global _active_lookup
    with _lookup_lock:
        lookup = _active_lookup
        if lookup is not None and lookup.domain != domain:
            error = "Another DNS lookup is still pending"
            logger.warning("DNS test failed for %s: %s", domain, error)
            return DnsResult(success=False, status="FAIL", response_time_ms=None, error=error)
        if lookup is None:
            lookup = _Lookup(domain=domain, completed=threading.Event(), addresses=[])
            _active_lookup = lookup
            threading.Thread(
                target=_run_lookup,
                args=(lookup,),
                name="DnsLookup",
                daemon=True,
            ).start()

    if not lookup.completed.wait(max(0.1, timeout_seconds)):
        error = f"DNS lookup timed out after {timeout_seconds} seconds"
        logger.warning("DNS test failed for %s: %s", domain, error)
        return DnsResult(success=False, status="FAIL", response_time_ms=None, error=error)

    if not lookup.addresses:
        error = lookup.error or "No IPv4 address returned"
        logger.warning("DNS test failed for %s: %s", domain, error)
        return DnsResult(success=False, status="FAIL", response_time_ms=None, error=error)

    return DnsResult(
        success=True,
        status="PASS",
        response_time_ms=round((time.monotonic() - start) * 1000, 2),
        resolved_address=lookup.addresses[0],
    )


if __name__ == "__main__":
    print(check_dns("google.com"))
    print(check_dns("this-domain-should-not-exist-xyz123.invalid"))
