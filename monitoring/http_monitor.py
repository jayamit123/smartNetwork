"""
monitoring/http_monitor.py

Phase 2 module.

Measures HTTP/HTTPS reachability of a configurable URL (default
https://www.google.com) and its response time. This is deliberately a
GET rather than a HEAD request because some servers/CDNs treat HEAD
differently (or block it), and because a real GET most closely matches
"can this machine actually load a web page right now", which is the
practical question the fault classifier (Phase 5) needs answered.

To keep this a genuinely "light" check even though it is a full GET, we
stream the response and only read a small prefix of the body rather than
downloading the entire page -- we only need to confirm the connection and
first bytes succeeded, not the full content.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from utils.logger import get_logger

logger = get_logger(__name__)

# Only read up to this many bytes of the response body -- enough to
# confirm the server actually sent something, without downloading the
# whole page on every monitoring tick.
_MAX_BODY_BYTES_READ = 2048


@dataclass
class HttpResult:
    success: bool
    status: str  # "PASS" or "FAIL" (convenience string form of `success`)
    response_time_ms: Optional[float]
    status_code: Optional[int] = None
    error: str = ""
    estimated_bytes_used: int = 0


def check_http(url: str, timeout_seconds: float = 5.0) -> HttpResult:
    """
    GET `url` and report PASS/FAIL, response time and status code.
    PASS means the connection succeeded AND the server returned a
    non-error status code (< 400). Every network-related requests
    exception is caught and turned into a clean FAIL result.
    """
    start = time.monotonic()
    try:
        with requests.get(url, timeout=timeout_seconds, stream=True) as response:
            body_bytes_read = 0
            for chunk in response.iter_content(chunk_size=512):
                body_bytes_read += len(chunk)
                if body_bytes_read >= _MAX_BODY_BYTES_READ:
                    break

            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            estimated_bytes = body_bytes_read + 512  # + rough header/request overhead

            if response.status_code < 400:
                return HttpResult(
                    success=True,
                    status="PASS",
                    response_time_ms=elapsed_ms,
                    status_code=response.status_code,
                    estimated_bytes_used=estimated_bytes,
                )

            logger.warning("HTTP test failed for %s: status %s", url, response.status_code)
            return HttpResult(
                success=False,
                status="FAIL",
                response_time_ms=None,
                status_code=response.status_code,
                error=f"HTTP status {response.status_code}",
                estimated_bytes_used=estimated_bytes,
            )

    except requests.exceptions.Timeout:
        logger.warning("HTTP test failed: request to %s timed out after %.1fs", url, timeout_seconds)
        return HttpResult(success=False, status="FAIL", response_time_ms=None, status_code=None, error="HTTP timeout")

    except requests.exceptions.ConnectionError as exc:
        logger.warning("HTTP test failed: connection error for %s: %s", url, exc)
        return HttpResult(success=False, status="FAIL", response_time_ms=None, status_code=None, error="Connection error")

    except requests.exceptions.RequestException as exc:
        logger.warning("HTTP test failed for %s: %s", url, exc)
        return HttpResult(success=False, status="FAIL", response_time_ms=None, status_code=None, error=str(exc))


if __name__ == "__main__":
    print(check_http("https://pypi.org"))
    print(check_http("https://this-domain-should-not-exist-xyz123.invalid"))
