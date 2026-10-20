"""
utils/config_loader.py

Loads config/settings.json so that the monitoring interval, ping counts,
targets and timeouts are never hardcoded inside the monitoring/analysis
modules. If the settings file is missing or contains invalid JSON, sane
defaults are returned instead of crashing the application, and the
problem is logged.

Key names match the project specification exactly:
    monitoring_interval, gateway_ping_count, internet_ping_count,
    internet_host, dns_test_domain, http_test_url, http_timeout

A few additional keys (network_info_refresh_seconds, dns_timeout,
ping_timeout_seconds, warning_thresholds) support extra, non-diagnostic
niceties already present in this project (auto-refreshing the network
info panel, per-call network timeouts, and the live dashboard's simple
NORMAL/DEGRADED/DISCONNECTED status roll-up) -- they are not part of the
required spec but follow the same "nothing hardcoded" rule.

Phase 4 adds two further keys, used by diagnosis/temporal_analysis.py:
    analysis_window  -- how many recent network_measurements rows to
                         analyze together (e.g. 6).
    thresholds       -- high/critical thresholds for latency, packet
                         loss, jitter, DNS and HTTP response time.
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import tempfile
from urllib.parse import urlparse
from typing import Any, Dict

from utils.logger import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, "config", "settings.json")

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "monitoring_interval": 1,
    "gateway_ping_count": 1,
    "internet_ping_count": 1,
    "internet_host": "8.8.8.8",
    "dns_test_domain": "google.com",
    "http_test_url": "https://www.google.com",
    "http_timeout": 1,

    "network_info_refresh_seconds": 5,
    "dns_timeout": 1,
    "ping_timeout_seconds": 1,

    "warning_thresholds": {
        "latency_ms": 100,
        "packet_loss_percent": 5,
        "jitter_ms": 30,
    },

    # Phase 4 (temporal analysis): how many recent network_measurements
    # rows to look at, and the thresholds used to decide whether a
    # metric counts as "high"/"critical" over that window. Read by
    # diagnosis/temporal_analysis.py -- never hardcoded there.
    "analysis_window": 6,
    "thresholds": {
        "high_latency_ms": 200,
        "critical_latency_ms": 500,
        "packet_loss_percent": 10,
        "critical_packet_loss_percent": 30,
        "high_jitter_ms": 50,
        "high_dns_response_ms": 500,
        "high_http_response_ms": 3000,
    },
}


def load_settings() -> Dict[str, Any]:
    """Return the contents of config/settings.json, falling back to
    built-in defaults (merged shallowly) if the file is missing/invalid."""
    settings = dict(_DEFAULT_SETTINGS)

    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            settings.update(loaded)
        else:
            logger.warning("settings.json did not contain a JSON object; using defaults.")
    except FileNotFoundError:
        logger.warning("settings.json not found at %s; using default settings.", _SETTINGS_PATH)
    except json.JSONDecodeError as exc:
        logger.warning("settings.json is not valid JSON (%s); using default settings.", exc)
    except OSError as exc:
        logger.warning("Could not read settings.json (%s); using default settings.", exc)

    return settings


def validate_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize settings supported by this application.

    Numeric values may arrive as strings from the settings form. The
    returned mapping is a copy and retains any other JSON-compatible keys.
    """
    if not isinstance(settings, dict):
        raise ValueError("Settings must be a JSON object.")

    normalized = dict(settings)
    errors = []

    integer_ranges = {
        "monitoring_interval": (1, 3600),
        "gateway_ping_count": (1, 20),
        "internet_ping_count": (1, 20),
        "http_timeout": (1, 300),
        "network_info_refresh_seconds": (1, 3600),
        "dns_timeout": (1, 300),
        "ping_timeout_seconds": (1, 300),
        "analysis_window": (1, 1000),
    }
    for key, (minimum, maximum) in integer_ranges.items():
        try:
            raw = settings[key]
            if isinstance(raw, bool):
                raise ValueError
            value = int(raw)
            if str(raw).strip() != str(value):
                raise ValueError
            if not minimum <= value <= maximum:
                errors.append(f"{key} must be between {minimum} and {maximum}.")
            else:
                normalized[key] = value
        except (KeyError, TypeError, ValueError):
            errors.append(f"{key} must be a whole number between {minimum} and {maximum}.")

    text_settings = {
        "internet_host": "Internet host",
        "dns_test_domain": "DNS test domain",
        "http_test_url": "HTTP test URL",
    }
    for key, label in text_settings.items():
        value = settings.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label} is required.")
        else:
            normalized[key] = value.strip()

    http_url = normalized.get("http_test_url")
    if isinstance(http_url, str) and http_url.strip():
        try:
            parsed_url = urlparse(http_url)
            valid_port = parsed_url.port is None or 1 <= parsed_url.port <= 65535
        except ValueError:
            parsed_url = None
            valid_port = False
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or not valid_port
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            errors.append("HTTP test URL must be an absolute http:// or https:// URL.")

    hostname_pattern = re.compile(
        r"(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\."
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?"
    )
    for key, label in (("internet_host", "Internet test host"), ("dns_test_domain", "DNS test domain")):
        hostname = normalized.get(key)
        if isinstance(hostname, str) and hostname.strip():
            hostname = hostname.strip()
            is_ipv4_literal = bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname))
            try:
                if is_ipv4_literal:
                    ipaddress.IPv4Address(hostname)
                valid_hostname = bool(hostname_pattern.fullmatch(hostname))
            except ipaddress.AddressValueError:
                valid_hostname = False
            if not valid_hostname:
                errors.append(f"{label} must be a valid hostname or IPv4 address.")

    numeric_groups = {
        "warning_thresholds": {
            "latency_ms": (0, None),
            "packet_loss_percent": (0, 100),
            "jitter_ms": (0, None),
        },
        "thresholds": {
            "high_latency_ms": (0, None),
            "critical_latency_ms": (0, None),
            "packet_loss_percent": (0, 100),
            "critical_packet_loss_percent": (0, 100),
            "high_jitter_ms": (0, None),
            "high_dns_response_ms": (0, None),
            "high_http_response_ms": (0, None),
        },
    }
    for group_name, fields in numeric_groups.items():
        group = settings.get(group_name)
        if not isinstance(group, dict):
            errors.append(f"{group_name} must be an object.")
            continue
        normalized_group = dict(group)
        for key, (minimum, maximum) in fields.items():
            try:
                raw = group[key]
                if isinstance(raw, bool):
                    raise ValueError
                value = float(raw)
                if not value == value or value in (float("inf"), float("-inf")):
                    raise ValueError
                if value < minimum or (maximum is not None and value > maximum):
                    bound = f"{minimum} to {maximum}" if maximum is not None else f"at least {minimum}"
                    errors.append(f"{group_name}.{key} must be {bound}.")
                else:
                    normalized_group[key] = value
            except (KeyError, TypeError, ValueError):
                errors.append(f"{group_name}.{key} must be a valid number.")
        normalized[group_name] = normalized_group

    temporal = normalized.get("thresholds", {})
    try:
        if temporal["high_latency_ms"] >= temporal["critical_latency_ms"]:
            errors.append("thresholds.critical_latency_ms must exceed thresholds.high_latency_ms.")
        if temporal["packet_loss_percent"] >= temporal["critical_packet_loss_percent"]:
            errors.append(
                "thresholds.critical_packet_loss_percent must exceed thresholds.packet_loss_percent."
            )
    except (KeyError, TypeError):
        pass

    if errors:
        raise ValueError("\n".join(errors))
    return normalized


def save_settings(settings: Dict[str, Any]) -> bool:
    """Validate and atomically persist settings to config/settings.json."""
    validated = validate_settings(settings)
    temporary_path = None
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(_SETTINGS_PATH),
            prefix=".settings-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(validated, handle, indent=4)
            handle.write("\n")
        os.replace(temporary_path, _SETTINGS_PATH)
        return True
    except OSError as exc:
        logger.error("Could not save settings.json: %s", exc)
        return False
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                logger.warning("Could not remove temporary settings file %s.", temporary_path)
