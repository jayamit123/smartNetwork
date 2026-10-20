"""
Read-only history and session diagnosis views.

Session analysis is computed from that session's stored measurements only.
Persisted events and diagnoses are shown separately when available; opening
history never creates or modifies records.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List

from database.database import Database
from diagnosis.correlation_engine import correlate_symptoms
from diagnosis.temporal_analysis import analyze_measurements
from utils.config_loader import load_settings
from utils.logger import get_logger
from gui.theme import PALETTE, configure_styles, font_family

logger = get_logger(__name__)

_COLORS = {
    "background": PALETTE["background"],
    "surface": PALETTE["surface"],
    "text": PALETTE["text"],
    "muted": PALETTE["muted"],
    "blue": PALETTE["primary"],
    "green": PALETTE["success"],
    "orange": PALETTE["warning"],
    "red": PALETTE["danger"],
}


def _display(value: Any, precision: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


def _status(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return "PASS" if bool(int(value)) else "FAIL"
    except (TypeError, ValueError):
        return "—"


class HistoryView(tk.Toplevel):
    def __init__(self, master: tk.Misc, database: Database):
        super().__init__(master)
        self.title("Monitoring history")
        self.geometry("1040x600")
        self.minsize(760, 420)
        self.configure(background=_COLORS["background"])

        self._database = database
        self._sessions: List[Dict[str, Any]] = []
        self._session_windows: Dict[int, SessionMeasurementsView] = {}

        self._configure_styles()
        self._build_widgets()
        self.refresh()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        configure_styles(style)
        family = font_family(self)
        style.configure("History.TFrame", background=_COLORS["background"])
        style.configure(
            "HistoryCard.TFrame",
            background=_COLORS["surface"],
            relief="solid",
            borderwidth=1,
            bordercolor=PALETTE["border"],
        )
        style.configure(
            "HistoryTitle.TLabel",
            background=_COLORS["background"],
            foreground=_COLORS["text"],
            font=(family, 24, "bold"),
        )
        style.configure(
            "HistoryMuted.TLabel",
            background=_COLORS["background"],
            foreground=_COLORS["muted"],
            font=(family, 9),
        )
        style.configure(
            "History.Treeview",
            rowheight=32,
            background=_COLORS["surface"],
            fieldbackground=_COLORS["surface"],
            foreground=PALETTE["body"],
            font=(family, 9),
            bordercolor=PALETTE["border"],
        )
        style.configure(
            "History.Treeview.Heading",
            background=PALETTE["table_header"],
            foreground=_COLORS["text"],
            font=(family, 9, "bold"),
            padding=(8, 8),
        )

    def _build_widgets(self) -> None:
        family = font_family(self)
        container = ttk.Frame(self, padding=20, style="History.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(container, text="Monitoring history", style="HistoryTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            container,
            text="Review stored sessions, measurements, and available diagnosis evidence.",
            style="HistoryMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        toolbar = ttk.Frame(container, style="History.TFrame")
        toolbar.grid(row=2, column=0, sticky="nsew")
        toolbar.columnconfigure(0, weight=1)
        toolbar.rowconfigure(1, weight=1)
        filters = ttk.Frame(toolbar, style="History.TFrame")
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="Search", style="HistoryMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 7)
        )
        self._search_var = tk.StringVar()
        search = ttk.Entry(filters, textvariable=self._search_var)
        search.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self._search_var.trace_add("write", lambda *_args: self._apply_filters())
        ttk.Label(filters, text="Status", style="HistoryMuted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 7)
        )
        self._status_var = tk.StringVar(value="All")
        status_filter = ttk.Combobox(
            filters,
            textvariable=self._status_var,
            values=("All", "IN_PROGRESS", "COMPLETED", "INTERRUPTED"),
            state="readonly",
            width=16,
        )
        status_filter.grid(row=0, column=3, sticky="w", padx=(0, 10))
        status_filter.bind("<<ComboboxSelected>>", lambda _event: self._apply_filters())
        ttk.Button(
            filters, text="Refresh", style="Secondary.TButton", command=self.refresh
        ).grid(row=0, column=4, sticky="e")

        columns = (
            "session_id",
            "start_time",
            "end_time",
            "interface",
            "measurements",
            "events",
            "final_status",
        )
        headings = {
            "session_id": "Session",
            "start_time": "Started",
            "end_time": "Ended",
            "interface": "Interface",
            "measurements": "Measurements",
            "events": "Events",
            "final_status": "Status",
        }
        self._tree = ttk.Treeview(
            toolbar, columns=columns, show="headings", selectmode="browse", style="History.Treeview"
        )
        widths = {
            "session_id": 75,
            "start_time": 175,
            "end_time": 175,
            "interface": 125,
            "measurements": 105,
            "events": 80,
            "final_status": 120,
        }
        for column in columns:
            self._tree.heading(column, text=headings[column])
            self._tree.column(column, width=widths[column], minwidth=70, anchor="center")
        self._tree.grid(row=1, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(toolbar, orient="vertical", command=self._tree.yview)
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(toolbar, orient="horizontal", command=self._tree.xview)
        x_scroll.grid(row=2, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self._tree.bind("<Double-1>", self._on_row_double_click)

        footer = ttk.Frame(container, style="History.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self._count_label = ttk.Label(footer, text="", style="HistoryMuted.TLabel")
        self._count_label.pack(side="left")
        ttk.Label(
            footer,
            text="Double-click a session to inspect its saved measurements and diagnosis.",
            style="HistoryMuted.TLabel",
        ).pack(side="right")

    def refresh(self) -> None:
        self._sessions = self._database.get_sessions()
        self._apply_filters()

    def _apply_filters(self) -> None:
        search_term = self._search_var.get().strip().casefold()
        chosen_status = self._status_var.get()
        for row_id in self._tree.get_children():
            self._tree.delete(row_id)

        visible = 0
        for session in self._sessions:
            status = str(session.get("final_status") or "UNKNOWN")
            searchable = " ".join(
                str(session.get(key) or "")
                for key in ("session_id", "start_time", "end_time", "interface_name", "ipv4_address", "gateway_ip")
            ).casefold()
            if chosen_status != "All" and status != chosen_status:
                continue
            if search_term and search_term not in searchable:
                continue
            self._tree.insert(
                "",
                "end",
                iid=str(session["session_id"]),
                values=(
                    session.get("session_id", "—"),
                    session.get("start_time") or "—",
                    session.get("end_time") or "In progress",
                    session.get("interface_name") or "—",
                    session.get("measurement_count", 0),
                    session.get("event_count", 0),
                    status,
                ),
            )
            visible += 1
        self._count_label.configure(
            text=f"{visible} of {len(self._sessions)} sessions"
            if self._sessions
            else "No monitoring sessions have been stored."
        )

    def _on_row_double_click(self, _event) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        try:
            session_id = int(selection[0])
        except ValueError:
            return
        existing = self._session_windows.get(session_id)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.refresh()
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass
        self._session_windows[session_id] = SessionMeasurementsView(
            self, self._database, session_id
        )


class SessionMeasurementsView(tk.Toplevel):
    """Read-only session measurements plus computed and persisted diagnosis."""

    def __init__(self, master: tk.Misc, database: Database, session_id: int):
        super().__init__(master)
        self._database = database
        self._session_id = session_id
        self._settings = load_settings()
        self.title(f"Session #{session_id} — details")
        self.geometry("1240x760")
        self.minsize(900, 560)
        self.configure(background=_COLORS["background"])
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        family = font_family(self)
        container = ttk.Frame(self, padding=18, style="History.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        header = ttk.Frame(container, style="History.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text=f"Session #{self._session_id}",
            style="HistoryTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._summary_label = ttk.Label(header, text="", style="HistoryMuted.TLabel")
        self._summary_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(
            header, text="Refresh", style="Secondary.TButton", command=self.refresh
        ).grid(row=0, column=1, rowspan=2)

        notebook = ttk.Notebook(container)
        notebook.grid(row=1, column=0, sticky="nsew")

        measurements_tab = ttk.Frame(notebook, padding=12, style="HistoryCard.TFrame")
        measurements_tab.columnconfigure(0, weight=1)
        measurements_tab.rowconfigure(1, weight=1)
        notebook.add(measurements_tab, text="Measurements")
        ttk.Label(
            measurements_tab,
            text="Stored records, in chronological order. Unavailable measurements are shown as em dashes.",
            style="HistoryMuted.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._measurement_tree = self._create_measurement_tree(measurements_tab)
        self._measurement_tree.grid(row=1, column=0, sticky="nsew")

        diagnosis_tab = ttk.Frame(notebook, padding=12, style="HistoryCard.TFrame")
        diagnosis_tab.columnconfigure(0, weight=1)
        diagnosis_tab.rowconfigure(1, weight=1)
        notebook.add(diagnosis_tab, text="Events & diagnosis")
        self._diagnosis_text = tk.Text(
            diagnosis_tab,
            wrap="word",
            background=_COLORS["surface"],
            foreground=_COLORS["text"],
            relief="flat",
            padx=14,
            pady=12,
            font=(family, 10),
            state="disabled",
        )
        self._diagnosis_text.grid(row=0, column=0, sticky="nsew")
        diagnosis_scroll = ttk.Scrollbar(
            diagnosis_tab, orient="vertical", command=self._diagnosis_text.yview
        )
        diagnosis_scroll.grid(row=0, column=1, sticky="ns")
        self._diagnosis_text.configure(yscrollcommand=diagnosis_scroll.set)

        event_frame = ttk.Frame(diagnosis_tab, style="HistoryCard.TFrame")
        event_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        event_frame.columnconfigure(0, weight=1)
        event_frame.rowconfigure(1, weight=1)
        ttk.Label(
            event_frame,
            text="Persisted temporal events",
            font=(font_family(self), 10, "bold"),
        ).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        event_columns = ("start", "end", "duration", "parameters", "severity", "evidence")
        self._events_tree = ttk.Treeview(
            event_frame, columns=event_columns, show="headings", height=5
        )
        for column, heading, width in (
            ("start", "Start", 160),
            ("end", "End", 160),
            ("duration", "Duration (s)", 100),
            ("parameters", "Affected parameters", 220),
            ("severity", "Severity", 100),
            ("evidence", "Evidence", 380),
        ):
            self._events_tree.heading(column, text=heading)
            self._events_tree.column(column, width=width, minwidth=80, anchor="w")
        self._events_tree.grid(row=1, column=0, sticky="nsew")
        event_y_scroll = ttk.Scrollbar(event_frame, orient="vertical", command=self._events_tree.yview)
        event_y_scroll.grid(row=1, column=1, sticky="ns")
        event_x_scroll = ttk.Scrollbar(event_frame, orient="horizontal", command=self._events_tree.xview)
        event_x_scroll.grid(row=2, column=0, sticky="ew")
        self._events_tree.configure(
            yscrollcommand=event_y_scroll.set, xscrollcommand=event_x_scroll.set
        )

    @staticmethod
    def _create_measurement_tree(parent: ttk.Frame) -> ttk.Treeview:
        columns = (
            "timestamp",
            "interface",
            "ipv4",
            "gateway_ip",
            "gateway",
            "gateway_latency",
            "gateway_loss",
            "internet_host",
            "internet",
            "internet_latency",
            "internet_loss",
            "jitter",
            "dns_domain",
            "dns",
            "dns_latency",
            "dns_ip",
            "http_url",
            "http_status",
            "http_latency",
            "overall",
            "bytes",
        )
        headings = {
            "timestamp": "Timestamp",
            "interface": "Interface",
            "ipv4": "IPv4",
            "gateway_ip": "Gateway IP",
            "gateway": "Gateway",
            "gateway_latency": "GW latency (ms)",
            "gateway_loss": "GW loss (%)",
            "internet_host": "Internet host",
            "internet": "Internet",
            "internet_latency": "Internet latency (ms)",
            "internet_loss": "Internet loss (%)",
            "jitter": "Jitter (ms)",
            "dns_domain": "DNS domain",
            "dns": "DNS",
            "dns_latency": "DNS response (ms)",
            "dns_ip": "Resolved IP",
            "http_url": "HTTP URL",
            "http_status": "HTTP status",
            "http_latency": "HTTP response (ms)",
            "overall": "Overall",
            "bytes": "Est. bytes",
        }
        widths = {
            "timestamp": 165,
            "interface": 115,
            "ipv4": 115,
            "gateway_ip": 115,
            "gateway": 82,
            "gateway_latency": 110,
            "gateway_loss": 90,
            "internet_host": 115,
            "internet": 82,
            "internet_latency": 125,
            "internet_loss": 100,
            "jitter": 90,
            "dns_domain": 120,
            "dns": 72,
            "dns_latency": 115,
            "dns_ip": 125,
            "http_url": 180,
            "http_status": 90,
            "http_latency": 120,
            "overall": 105,
            "bytes": 90,
        }
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=14)
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=70, anchor="center", stretch=False)
        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        x_scroll.grid(row=2, column=0, sticky="ew")
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(2, weight=0)
        return tree

    def refresh(self) -> None:
        measurements = self._database.get_session_measurements(self._session_id)
        for row_id in self._measurement_tree.get_children():
            self._measurement_tree.delete(row_id)
        for row in measurements:
            self._measurement_tree.insert("", "end", values=self._measurement_values(row))
        self._summary_label.configure(
            text=self._session_summary(measurements)
        )
        self._update_diagnosis(measurements)
        self._update_events()

    @staticmethod
    def _measurement_values(row: Dict[str, Any]) -> tuple:
        return (
            row.get("timestamp") or "—",
            row.get("interface_name") or "—",
            row.get("ipv4_address") or "—",
            row.get("gateway_ip") or "—",
            _status(row.get("gateway_reachable")),
            _display(row.get("gateway_latency_ms")),
            _display(row.get("gateway_packet_loss")),
            row.get("internet_host") or "—",
            _status(row.get("internet_reachable")),
            _display(row.get("internet_latency_ms")),
            _display(row.get("internet_packet_loss")),
            _display(row.get("jitter_ms")),
            row.get("dns_domain") or "—",
            _status(row.get("dns_success")),
            _display(row.get("dns_response_time_ms")),
            row.get("dns_resolved_ip") or "—",
            row.get("http_url") or "—",
            _display(row.get("http_status_code"), precision=0),
            _display(row.get("http_response_time_ms")),
            row.get("overall_status") or "—",
            _display(row.get("bytes_used"), precision=0),
        )

    def _session_summary(self, measurements: List[Dict[str, Any]]) -> str:
        session = self._database.get_session(self._session_id) or {}
        start = session.get("start_time") or "Unknown start"
        end = session.get("end_time") or "In progress"
        interface = session.get("interface_name") or "Unknown interface"
        return (
            f"{interface}  ·  {start} to {end}  ·  "
            f"{len(measurements)} stored measurement(s)"
        )

    def _update_diagnosis(self, measurements: List[Dict[str, Any]]) -> None:
        self._diagnosis_text.configure(state="normal")
        self._diagnosis_text.delete("1.0", "end")
        if not measurements:
            self._diagnosis_text.insert(
                "end",
                "Session analysis\n"
                "No stored measurements are available for this session. No diagnosis was generated.\n\n"
                "Persisted diagnoses\nNo diagnosis records are stored for this session.",
            )
            self._diagnosis_text.configure(state="disabled")
            return

        window_size = max(1, int(self._settings.get("analysis_window", 6)))
        recent_rows = list(reversed(measurements[-window_size:]))
        try:
            detection = analyze_measurements(recent_rows, self._settings)
            latest_correlation = correlate_symptoms(detection, measurements[-1])
        except Exception:
            logger.exception("Could not compute history diagnosis for session #%s.", self._session_id)
            self._diagnosis_text.insert(
                "end",
                "Session analysis could not be computed. Check the application log for details.",
            )
            self._diagnosis_text.configure(state="disabled")
            return

        lines = [
            "SESSION ANALYSIS (computed from this session's stored measurements)",
            f"Analysis timestamp: {detection.timestamp}",
            f"Measurements analyzed: {detection.measurements_analyzed} / {detection.window_size}",
            f"Analysis status: {detection.analysis_status.replace('_', ' ')}",
        ]
        if detection.analysis_status == "SUFFICIENT_DATA":
            pattern = (
                "PERSISTENT"
                if detection.persistent
                else "INTERMITTENT"
                if detection.intermittent
                else "NONE"
            )
            lines.extend(
                [
                    f"Temporal condition: {'DEGRADED' if detection.degraded else 'NORMAL'}",
                    f"Temporal pattern: {pattern}",
                    f"Recovery observed: {'Yes' if detection.recovery_observed else 'No'}",
                    f"Temporal severity: {detection.severity} (score {detection.severity_score})",
                    f"Probable fault category: {latest_correlation.probable_category.replace('_', ' ')}",
                    f"Diagnosis status: {latest_correlation.status.replace('_', ' ')}",
                    "Correlated symptoms: "
                    + (", ".join(item.replace("_", " ") for item in latest_correlation.correlated_symptoms) or "None"),
                    "Evidence:",
                ]
            )
            lines.extend(f"  • {item}" for item in latest_correlation.evidence)
            if detection.symptoms:
                lines.append("Temporal event indicators:")
                lines.extend(f"  • {item}" for item in detection.symptoms)
            lines.extend(
                [
                    "",
                    "Baselines from analyzed measurements:",
                    f"  Gateway latency: {_display(detection.baseline_gateway_latency_ms)} ms",
                    f"  Internet latency: {_display(detection.baseline_internet_latency_ms)} ms",
                    f"  Packet loss: {_display(detection.baseline_packet_loss_percent)}%",
                    f"  Jitter: {_display(detection.baseline_jitter_ms)} ms",
                    f"  DNS response: {_display(detection.baseline_dns_response_time_ms)} ms",
                    f"  HTTP response: {_display(detection.baseline_http_response_time_ms)} ms",
                ]
            )
        else:
            lines.append(
                "Not enough stored measurements to analyze this session. "
                "The probable category is not inferred from insufficient data."
            )
            lines.extend(
                [
                    f"Temporal severity: {detection.severity}",
                    f"Probable fault category: {latest_correlation.probable_category.replace('_', ' ')}",
                    f"Diagnosis status: {latest_correlation.status.replace('_', ' ')}",
                ]
            )
            lines.extend(f"  • {item}" for item in latest_correlation.evidence)
            lines.extend(f"  • {item}" for item in detection.symptoms)

        persisted = self._database.get_session_diagnoses(self._session_id)
        lines.extend(["", "PERSISTED DIAGNOSES"])
        if persisted:
            for diagnosis in persisted:
                lines.extend(
                    [
                        f"Created: {diagnosis.get('created_at') or '—'}",
                        f"Category: {diagnosis.get('fault_category') or '—'}",
                        f"Evidence: {diagnosis.get('evidence') or '—'}",
                        f"Recommended action: {diagnosis.get('recommended_action') or '—'}",
                        "",
                    ]
                )
        else:
            lines.append("No diagnosis records are stored for this session.")
        self._diagnosis_text.insert("end", "\n".join(lines))
        self._diagnosis_text.configure(state="disabled")

    def _update_events(self) -> None:
        for row_id in self._events_tree.get_children():
            self._events_tree.delete(row_id)
        events = self._database.get_session_events(self._session_id)
        for event in events:
            self._events_tree.insert(
                "",
                "end",
                values=(
                    event.get("start_time") or "—",
                    event.get("end_time") or "Ongoing / unknown",
                    _display(event.get("duration_seconds")),
                    event.get("affected_parameters") or "—",
                    event.get("severity") or "—",
                    event.get("evidence") or "—",
                ),
            )
        if not events:
            self._events_tree.insert(
                "",
                "end",
                values=("—", "—", "—", "No persisted events", "—", "—"),
            )
