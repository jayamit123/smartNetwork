"""
monitoring/dns_monitor.py

Checks DNS availability using the Windows operating system resolver.
Preserves the DnsResult interface used by the monitoring system.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DnsResult:
    success: bool
    status: str
    response_time_ms: Optional[float]
    resolved_address: Optional[str] = None
    error: str = ""


def check_dns(domain: str, timeout_seconds: float = 3.0) -> DnsResult:
    """
    Resolve a domain using the operating system's configured resolver.

    Note: socket.getaddrinfo uses the OS resolver, but Python's standard
    library does not provide a portable per-call DNS timeout for it.
    The timeout_seconds parameter is retained for interface compatibility.
    """
    start = time.monotonic()

    try:
        answers = socket.getaddrinfo(
            domain,
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )

        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        resolved_address = addresses[0] if addresses else None

        if not resolved_address:
            logger.warning("DNS test failed: no IPv4 address returned for %s", domain)
            return DnsResult(
                success=False,
                status="FAIL",
                response_time_ms=None,
                error="No IPv4 address returned",
            )

        return DnsResult(
            success=True,
            status="PASS",
            response_time_ms=elapsed_ms,
            resolved_address=resolved_address,
        )

    except socket.gaierror as exc:
        logger.warning("DNS test failed for %s: %s", domain, exc)
        return DnsResult(
            success=False,
            status="FAIL",
            response_time_ms=None,
            error=str(exc),
        )

    except OSError as exc:
        logger.warning("DNS test failed for %s: %s", domain, exc)
        return DnsResult(
            success=False,
            status="FAIL",
            response_time_ms=None,
            error=str(exc),
        )


if __name__ == "__main__":
    print(check_dns("google.com"))
    print(check_dns("this-domain-should-not-exist-xyz123.invalid"))
