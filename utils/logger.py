"""
utils/logger.py

Centralized logging configuration for the Smart Network Diagnosis System.

Every module in this project should obtain its logger through
`get_logger(__name__)` instead of creating its own handlers. This keeps
log formatting consistent and guarantees that all log output (console +
file) is captured in one place, which is required by the project's
"ERROR HANDLING" specification (the GUI must never crash silently).
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Directory where log files are stored. Created next to this file's
# project root, not inside utils/, so it survives even if utils/ is
# treated as read-only in some deployment.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "application.log")

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def _ensure_log_dir():
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        return True
    except OSError:
        # If we cannot create the log directory (e.g. permission denied),
        # we fall back to console-only logging instead of crashing the app.
        return False


def _configure_root_logger():
    """
    Configure the root logger exactly once for the whole process.
    Subsequent calls to get_logger() just create named children of it.
    """
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger("smart_network_diagnosis")
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler: INFO and above, so day-to-day use isn't noisy.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler: DEBUG and above, rotated so it never grows unbounded.
    if _ensure_log_dir():
        try:
            file_handler = RotatingFileHandler(
                _LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError:
            # Disk / permission problems must not prevent the app from running.
            root_logger.warning(
                "Could not open log file at %s. Continuing with console logging only.",
                _LOG_FILE,
            )

    root_logger.propagate = False
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger named `smart_network_diagnosis.<name>`.

    Usage:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened")
    """
    _configure_root_logger()
    return logging.getLogger("smart_network_diagnosis").getChild(name)
