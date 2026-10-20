"""
database/database.py

Phase 3 module: Data Storage and Logging.

Wraps a single SQLite database at:

    data/network_monitor.db

(the `data/` directory is created automatically if it does not exist).

Two tables are maintained:

1. `network_measurements` -- the primary, spec-required table. One row
   per monitoring cycle, fully self-contained (it carries its own
   interface/ipv4/gateway/target snapshot, not just a foreign key), so a
   single row is enough on its own for later temporal analysis:

       id, timestamp, interface_name, ipv4_address, gateway_ip,
       gateway_reachable, gateway_latency_ms, gateway_latency_min_ms,
       gateway_latency_max_ms, gateway_packet_loss,
       internet_host, internet_reachable, internet_latency_ms,
       internet_latency_min_ms, internet_latency_max_ms,
       internet_packet_loss, jitter_ms,
       dns_domain, dns_success, dns_response_time_ms, dns_resolved_ip,
       http_url, http_status_code, http_response_time_ms,
       overall_status, bytes_used, session_id

2. `monitoring_sessions` -- an optional grouping of measurements taken
   between one Start-Monitoring and Stop-Monitoring click (used by the
   GUI's "View History" / "View Live Monitoring" windows to show one
   session's data at a time, and to report session start/end times).
   `network_measurements.session_id` links back to this table but is
   nullable, so the flat table is always complete on its own.

The application never deletes previous data on startup or restart --
tables are created with `CREATE TABLE IF NOT EXISTS` and existing rows
are left untouched.

Thread safety: sqlite3 connections are not safe to share across threads
by default. Since the background monitoring thread writes while the GUI
thread reads concurrently, this module opens its connection with
`check_same_thread=False` and serializes all access with a single
`threading.Lock`.
"""

from __future__ import annotations

import sqlite3
import threading
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "network_monitor.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_sessions (
    session_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    interface_name       TEXT,
    ipv4_address         TEXT,
    gateway_ip           TEXT,
    measurement_count   INTEGER NOT NULL DEFAULT 0,
    overhead_bytes_total INTEGER NOT NULL DEFAULT 0,
    final_status        TEXT NOT NULL DEFAULT 'IN_PROGRESS'
);

CREATE TABLE IF NOT EXISTS network_measurements (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT NOT NULL,

    interface_name           TEXT,
    ipv4_address              TEXT,

    gateway_ip                TEXT,
    gateway_reachable         INTEGER,
    gateway_latency_ms        REAL,
    gateway_latency_min_ms    REAL,
    gateway_latency_max_ms    REAL,
    gateway_packet_loss       REAL,

    internet_host              TEXT,
    internet_reachable         INTEGER,
    internet_latency_ms        REAL,
    internet_latency_min_ms    REAL,
    internet_latency_max_ms    REAL,
    internet_packet_loss       REAL,

    jitter_ms                   REAL,

    dns_domain                  TEXT,
    dns_success                 INTEGER,
    dns_response_time_ms        REAL,
    dns_resolved_ip              TEXT,

    http_url                     TEXT,
    http_status_code             INTEGER,
    http_response_time_ms        REAL,

    overall_status                TEXT,
    bytes_used                    INTEGER NOT NULL DEFAULT 0,

    session_id                    INTEGER,
    FOREIGN KEY (session_id) REFERENCES monitoring_sessions (session_id)
);

CREATE TABLE IF NOT EXISTS detected_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    duration_seconds     REAL,
    affected_parameters TEXT,
    severity            TEXT,
    evidence             TEXT,
    FOREIGN KEY (session_id) REFERENCES monitoring_sessions (session_id)
);

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    event_id            INTEGER,
    fault_category      TEXT,
    evidence             TEXT,
    recommended_action  TEXT,
    created_at          TEXT,
    FOREIGN KEY (session_id) REFERENCES monitoring_sessions (session_id),
    FOREIGN KEY (event_id) REFERENCES detected_events (event_id)
);

CREATE TABLE IF NOT EXISTS remediation_actions (
    remediation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    diagnosis_id        INTEGER,
    action_name         TEXT,
    command             TEXT,
    requires_admin      INTEGER NOT NULL DEFAULT 0,
    executed_at         TEXT,
    pre_measurements    TEXT,
    result              TEXT,
    FOREIGN KEY (session_id) REFERENCES monitoring_sessions (session_id),
    FOREIGN KEY (diagnosis_id) REFERENCES diagnoses (diagnosis_id)
);

CREATE TABLE IF NOT EXISTS verification_results (
    verification_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    remediation_id       INTEGER,
    metric               TEXT,
    before_value         TEXT,
    after_value          TEXT,
    result               TEXT,
    verified_at          TEXT,
    FOREIGN KEY (session_id) REFERENCES monitoring_sessions (session_id),
    FOREIGN KEY (remediation_id) REFERENCES remediation_actions (remediation_id)
);
"""


class Database:
    """Thread-safe wrapper around the project's SQLite database."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._connection: Optional[sqlite3.Connection] = None
        self._connect_and_initialize()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _connect_and_initialize(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._connection = sqlite3.connect(
                self.db_path, check_same_thread=False, isolation_level=None
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON;")
            with self._lock:
                self._connection.executescript(_SCHEMA)
            logger.info("Database initialized at %s", self.db_path)
        except sqlite3.Error as exc:
            logger.exception("Database initialization failed: %s", exc)
            raise

    def close(self) -> None:
        if self._connection is not None:
            with self._lock:
                self._connection.close()
            self._connection = None

    # ------------------------------------------------------------------
    # monitoring_sessions (Start/Stop grouping used by the GUI's history
    # and live-monitoring windows; optional, not required by the flat
    # network_measurements table below)
    # ------------------------------------------------------------------

    def create_session(self, interface: Optional[str], ipv4: Optional[str], gateway: Optional[str]) -> Optional[int]:
        start_time = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                cursor = self._connection.execute(
                    """
                    INSERT INTO monitoring_sessions
                        (start_time, interface_name, ipv4_address, gateway_ip, final_status)
                    VALUES (?, ?, ?, ?, 'IN_PROGRESS')
                    """,
                    (start_time, interface, ipv4, gateway),
                )
            session_id = cursor.lastrowid
            logger.info("Monitoring started (session #%s).", session_id)
            return session_id
        except sqlite3.Error as exc:
            logger.error("Could not create monitoring session: %s", exc)
            return None

    def end_session(self, session_id: int, final_status: str = "COMPLETED") -> bool:
        end_time = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                self._connection.execute(
                    "UPDATE monitoring_sessions SET end_time = ?, final_status = ? WHERE session_id = ?",
                    (end_time, final_status, session_id),
                )
            logger.info("Monitoring stopped (session #%s, %s).", session_id, final_status)
            return True
        except sqlite3.Error as exc:
            logger.error("Could not end monitoring session #%s: %s", session_id, exc)
            return False

    def get_sessions(self) -> List[Dict[str, Any]]:
        query = """
            SELECT
                s.session_id, s.start_time, s.end_time,
                s.interface_name, s.ipv4_address, s.gateway_ip,
                s.measurement_count, s.overhead_bytes_total, s.final_status,
                (SELECT COUNT(*) FROM detected_events e WHERE e.session_id = s.session_id) AS event_count
            FROM monitoring_sessions s
            ORDER BY s.session_id DESC
        """
        try:
            with self._lock:
                rows = self._connection.execute(query).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch sessions: %s", exc)
            return []

    def clear_sessions(self) -> Dict[str, int]:
        """Delete all persisted monitoring history in foreign-key order."""
        tables = (
            "verification_results",
            "remediation_actions",
            "diagnoses",
            "detected_events",
            "network_measurements",
            "monitoring_sessions",
        )
        try:
            with self._lock:
                self._connection.execute("BEGIN")
                deleted = {}
                for table in tables:
                    cursor = self._connection.execute(f"DELETE FROM {table}")
                    deleted[table] = cursor.rowcount
                self._connection.execute("COMMIT")
            logger.info("Cleared persisted monitoring history: %s", deleted)
            return deleted
        except sqlite3.Error:
            with self._lock:
                if self._connection is not None:
                    self._connection.rollback()
            logger.exception("Could not clear persisted monitoring history.")
            raise

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        try:
            with self._lock:
                row = self._connection.execute(
                    "SELECT * FROM monitoring_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error as exc:
            logger.error("Could not fetch session #%s: %s", session_id, exc)
            return None

    def get_session_measurements(self, session_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Every network_measurements row belonging to one session, oldest first."""
        query = "SELECT * FROM network_measurements WHERE session_id = ? ORDER BY id ASC"
        params: tuple = (session_id,)
        if limit is not None:
            query += " LIMIT ?"
            params = (session_id, limit)
        try:
            with self._lock:
                rows = self._connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch measurements for session #%s: %s", session_id, exc)
            return []

    def get_session_events(self, session_id: int) -> List[Dict[str, Any]]:
        """Return persisted temporal events for one session, oldest first."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    """
                    SELECT * FROM detected_events
                    WHERE session_id = ?
                    ORDER BY start_time ASC, event_id ASC
                    """,
                    (session_id,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch events for session #%s: %s", session_id, exc)
            return []

    def get_session_diagnoses(self, session_id: int) -> List[Dict[str, Any]]:
        """Return persisted diagnoses for one session, newest first."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    """
                    SELECT * FROM diagnoses
                    WHERE session_id = ?
                    ORDER BY created_at DESC, diagnosis_id DESC
                    """,
                    (session_id,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch diagnoses for session #%s: %s", session_id, exc)
            return []

    def get_session_remediation_actions(self, session_id: int) -> List[Dict[str, Any]]:
        """Return stored remediation review entries, newest plan first."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    """
                    SELECT * FROM remediation_actions
                    WHERE session_id = ?
                    ORDER BY remediation_id DESC
                    """,
                    (session_id,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch remediation reviews for session #%s: %s", session_id, exc)
            return []

    def get_session_verification_results(self, session_id: int) -> List[Dict[str, Any]]:
        """Return recorded verification outcomes for one session."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    """
                    SELECT * FROM verification_results
                    WHERE session_id = ?
                    ORDER BY verified_at DESC, verification_id DESC
                    """,
                    (session_id,),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch verification results for session #%s: %s", session_id, exc)
            return []

    def create_remediation_action(
        self,
        session_id: int,
        action_name: str,
        command: str,
        pre_measurements: Dict[str, Any],
        result: str,
    ) -> Optional[int]:
        try:
            with self._lock:
                cursor = self._connection.execute(
                    """
                    INSERT INTO remediation_actions
                        (session_id, action_name, command, requires_admin, executed_at,
                         pre_measurements, result)
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        session_id,
                        action_name,
                        command,
                        datetime.now().isoformat(timespec="seconds"),
                        json.dumps(pre_measurements, ensure_ascii=True),
                        result,
                    ),
                )
                return cursor.lastrowid
        except sqlite3.Error as exc:
            logger.exception("Could not record remediation action.")
            raise RuntimeError("Could not record remediation action.") from exc

    def get_pending_remediation_actions(self) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                rows = self._connection.execute(
                    """
                    SELECT * FROM remediation_actions
                    WHERE result LIKE '%"status": "PENDING_VERIFICATION"%'
                    ORDER BY remediation_id ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.exception("Could not fetch pending remediation actions.")
            raise RuntimeError("Could not fetch pending remediation actions.") from exc

    def update_remediation_result(self, remediation_id: int, result: str) -> None:
        try:
            with self._lock:
                cursor = self._connection.execute(
                    "UPDATE remediation_actions SET result = ? WHERE remediation_id = ?",
                    (result, remediation_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"Remediation action {remediation_id} was not found.")
        except sqlite3.Error as exc:
            logger.exception("Could not update remediation action #%s.", remediation_id)
            raise RuntimeError("Could not update remediation action.") from exc

    def record_verification_result(
        self,
        session_id: int,
        remediation_id: int,
        metric: str,
        before_value: str,
        after_value: str,
        result: str,
    ) -> None:
        try:
            with self._lock:
                self._connection.execute(
                    """
                    INSERT INTO verification_results
                        (session_id, remediation_id, metric, before_value,
                         after_value, result, verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        remediation_id,
                        metric,
                        before_value,
                        after_value,
                        result,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
        except sqlite3.Error as exc:
            logger.exception("Could not record remediation verification.")
            raise RuntimeError("Could not record remediation verification.") from exc

    def record_remediation_review(
        self,
        session_id: int,
        recommendations: List[Dict[str, Any]],
        decision: str,
    ) -> Optional[str]:
        """Persist a human review decision for a recommendation plan.

        Review entries use the existing remediation_actions table with no
        command or executed_at value. This records approval/rejection only;
        it never performs a remediation action.
        """
        decision = str(decision).strip().upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("decision must be APPROVED or REJECTED")
        if not recommendations:
            raise ValueError("at least one recommendation is required")
        if any(not isinstance(item, dict) or not item.get("action_name") for item in recommendations):
            raise ValueError("each recommendation must include an action_name")

        plan_id = str(uuid.uuid4())
        reviewed_at = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock:
                self._connection.execute("BEGIN")
                for rank, item in enumerate(recommendations, start=1):
                    review_data = {
                        "plan_id": plan_id,
                        "plan_status": decision,
                        "reviewed_at": reviewed_at,
                        "rank": rank,
                        "reason": item.get("reason"),
                        "risk": item.get("risk"),
                        "severity": item.get("severity"),
                        "verification_steps": item.get("verification_steps", []),
                    }
                    self._connection.execute(
                        """
                        INSERT INTO remediation_actions
                            (session_id, action_name, command, requires_admin,
                             executed_at, pre_measurements, result)
                        VALUES (?, ?, NULL, 0, NULL, NULL, ?)
                        """,
                        (
                            session_id,
                            str(item["action_name"]),
                            json.dumps(review_data, ensure_ascii=True),
                        ),
                    )
                self._connection.execute("COMMIT")
            logger.info(
                "Remediation review %s recorded for session #%s (plan %s).",
                decision,
                session_id,
                plan_id,
            )
            return plan_id
        except sqlite3.Error as exc:
            with self._lock:
                if self._connection is not None:
                    self._connection.rollback()
            logger.error("Could not record remediation review for session #%s: %s", session_id, exc)
            return None

    # ------------------------------------------------------------------
    # network_measurements -- the required flat measurement log
    # ------------------------------------------------------------------

    _MEASUREMENT_COLUMNS = [
        "timestamp",
        "interface_name", "ipv4_address",
        "gateway_ip", "gateway_reachable", "gateway_latency_ms",
        "gateway_latency_min_ms", "gateway_latency_max_ms", "gateway_packet_loss",
        "internet_host", "internet_reachable", "internet_latency_ms",
        "internet_latency_min_ms", "internet_latency_max_ms", "internet_packet_loss",
        "jitter_ms",
        "dns_domain", "dns_success", "dns_response_time_ms", "dns_resolved_ip",
        "http_url", "http_status_code", "http_response_time_ms",
        "overall_status", "bytes_used", "session_id",
    ]

    def insert_measurement(self, result: Any, session_id: Optional[int] = None) -> bool:
        """
        Insert one monitoring cycle into network_measurements.

        `result` may be a dict OR a dataclass instance (e.g.
        monitor_controller.MeasurementRecord) -- whichever the caller has
        on hand. Missing keys default to NULL rather than raising, and
        the parent session's counters (if session_id is given) are
        atomically updated in the same call.
        """
        if is_dataclass(result) and not isinstance(result, type):
            data = asdict(result)
        elif isinstance(result, dict):
            data = dict(result)
        else:
            logger.error("insert_measurement() received an unsupported type: %s", type(result))
            return False

        if session_id is not None:
            data["session_id"] = session_id

        values = [data.get(col) for col in self._MEASUREMENT_COLUMNS]
        placeholders = ", ".join("?" for _ in self._MEASUREMENT_COLUMNS)
        columns_sql = ", ".join(self._MEASUREMENT_COLUMNS)

        try:
            with self._lock:
                self._connection.execute(
                    f"INSERT INTO network_measurements ({columns_sql}) VALUES ({placeholders})",
                    values,
                )
                if session_id is not None:
                    self._connection.execute(
                        """
                        UPDATE monitoring_sessions
                        SET measurement_count = measurement_count + 1,
                            overhead_bytes_total = overhead_bytes_total + ?
                        WHERE session_id = ?
                        """,
                        (data.get("bytes_used", 0) or 0, session_id),
                    )
            logger.info("Measurement stored (timestamp=%s).", data.get("timestamp"))
            return True
        except sqlite3.Error as exc:
            logger.error("Could not insert measurement: %s", exc)
            return False

    def get_recent_measurements(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Most recent `limit` measurements across all sessions, newest first."""
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT * FROM network_measurements ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch recent measurements: %s", exc)
            return []

    def get_measurements(
        self, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        All measurements whose ISO-8601 timestamp falls within
        [start_time, end_time] (either bound optional), oldest first.
        Used by later phases' temporal analysis over an arbitrary window.
        """
        query = "SELECT * FROM network_measurements WHERE 1=1"
        params: List[Any] = []
        if start_time is not None:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND timestamp <= ?"
            params.append(end_time)
        query += " ORDER BY id ASC"

        try:
            with self._lock:
                rows = self._connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("Could not fetch measurements in range: %s", exc)
            return []

    def get_measurement_count(self) -> int:
        """Total number of measurements ever stored (used by the GUI's
        'Records Stored' counter -- always read live from SQLite, never
        faked)."""
        try:
            with self._lock:
                row = self._connection.execute("SELECT COUNT(*) AS n FROM network_measurements").fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.Error as exc:
            logger.error("Could not count measurements: %s", exc)
            return 0


def initialize_database(db_path: Optional[str] = None) -> Database:
    """
    Module-level convenience matching the project spec's
    `initialize_database()` function: creates the data/ directory, the
    SQLite file and all tables if they do not already exist, and returns
    a ready-to-use Database instance. Equivalent to `Database(db_path)`.
    """
    return Database(db_path=db_path)


if __name__ == "__main__":
    # Quick manual smoke test using a throwaway database file.
    test_db = initialize_database(db_path=os.path.join(_PROJECT_ROOT, "data", "_selftest.db"))
    sid = test_db.create_session("eth0", "192.0.2.2", "192.0.2.1")
    print("session id:", sid)

    sample_result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "interface_name": "eth0",
        "ipv4_address": "192.0.2.2",
        "gateway_ip": "192.0.2.1",
        "gateway_reachable": 1,
        "gateway_latency_ms": 4.5,
        "gateway_latency_min_ms": 4.1,
        "gateway_latency_max_ms": 4.9,
        "gateway_packet_loss": 0.0,
        "internet_host": "8.8.8.8",
        "internet_reachable": 1,
        "internet_latency_ms": 25.2,
        "internet_latency_min_ms": 22.0,
        "internet_latency_max_ms": 28.0,
        "internet_packet_loss": 0.0,
        "jitter_ms": 3.2,
        "dns_domain": "google.com",
        "dns_success": 1,
        "dns_response_time_ms": 10.3,
        "dns_resolved_ip": "142.250.1.1",
        "http_url": "https://www.google.com",
        "http_status_code": 200,
        "http_response_time_ms": 150.0,
        "overall_status": "NORMAL",
        "bytes_used": 996,
    }
    print("insert ok:", test_db.insert_measurement(sample_result, session_id=sid))
    print("recent:", test_db.get_recent_measurements(limit=5))
    print("count:", test_db.get_measurement_count())
    print("range query:", test_db.get_measurements())
    test_db.end_session(sid, "COMPLETED")
    print("sessions:", test_db.get_sessions())
    test_db.close()
    os.remove(os.path.join(_PROJECT_ROOT, "data", "_selftest.db"))
