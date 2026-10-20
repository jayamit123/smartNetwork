"""
gui/dashboard.py

Main dashboard frame.

Phase 1 added the static network-configuration panel. Phase 2 adds the
START/STOP MONITORING controls and a live metrics panel driven by
monitoring/monitor_controller.py's background thread. Phase 3 adds the
"View History" button backed by database/database.py. Phase 4 adds temporal
analysis, and Phase 5 correlates temporal symptoms with the latest measurement.

MonitorController runs on a background thread and never touches Tkinter.
This Dashboard polls its queue on the Tkinter thread and updates the widgets.
"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from database.database import Database
from diagnosis.temporal_analysis import analyze_recent_measurements
from diagnosis.correlation_engine import correlate_symptoms
from diagnosis.recommendation_engine import generate_recommendations
from monitoring.interface_monitor import InterfaceMonitor
from monitoring.monitor_controller import MonitorController
from utils.config_loader import load_settings
from utils.logger import get_logger
from gui.theme import PALETTE, configure_styles, create_card, font_family

logger = get_logger(__name__)

_PALETTE = PALETTE

_STATUS_COLORS = {
    "Connected": PALETTE["success"],
    "CONNECTED": PALETTE["success"],
    "NORMAL": PALETTE["success"],
    "PASS": PALETTE["success"],
    "SUCCESS": PALETTE["success"],
    "Disconnected": PALETTE["danger"],
    "DISCONNECTED": PALETTE["danger"],
    "FAIL": PALETTE["danger"],
    "FAILED": PALETTE["danger"],
    "DEGRADED": PALETTE["warning"],
    "Unknown": PALETTE["warning"],
    "INSUFFICIENT DATA": PALETTE["warning"],
    "INSUFFICIENT_DATA": PALETTE["warning"],
    "UNDETERMINED": PALETTE["warning"],
    "NONE": PALETTE["success"],
    "INTERMITTENT": PALETTE["warning"],
    "PERSISTENT": PALETTE["danger"],
    "ANALYZED": PALETTE["success"],
}

_SEVERITY_COLORS = {
    "NORMAL": PALETTE["success"],
    "LOW": PALETTE["success"],
    "MEDIUM": PALETTE["warning"],
    "HIGH": PALETTE["danger"],
    "CRITICAL": PALETTE["danger"],
    "INSUFFICIENT_DATA": PALETTE["warning"],
}

_POLL_INTERVAL_MS = 500


class Dashboard(ttk.Frame):
    """Main dashboard frame, shown inside the application's root window."""

    def __init__(self, master: tk.Misc):
        super().__init__(master)

        self._configure_styles()

        self._settings = load_settings()
        self._interface_monitor = InterfaceMonitor()
        self._database = Database()
        self._monitor_controller = MonitorController(self._settings, self._database)

        self._auto_refresh_job = None
        self._poll_job = None
        self._monitoring_view = None
        self._history_view = None
        self._remediation_view = None
        self._settings_view = None

        self._build_shell()
        self._build_widgets()
        self.refresh_network_info()
        self._schedule_auto_refresh()

    def _configure_styles(self) -> None:
        configure_styles(ttk.Style(self))

    def _build_shell(self) -> None:
        self.configure(style="Dashboard.TFrame")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, width=228, style="Sidebar.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        brand = ttk.Frame(sidebar, padding=(18, 22, 18, 24), style="Sidebar.TFrame")
        brand.grid(row=0, column=0, sticky="ew")
        brand.columnconfigure(1, weight=1)
        logo = tk.Label(
            brand,
            text="SN",
            width=3,
            height=1,
            background=_PALETTE["primary"],
            foreground=_PALETTE["surface"],
            font=(font_family(self), 12, "bold"),
            padx=2,
            pady=7,
        )
        logo.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        ttk.Label(brand, text="SMART NETWORK", style="SidebarBrand.TLabel").grid(
            row=0, column=1, sticky="sw"
        )
        ttk.Label(brand, text="DIAGNOSIS SYSTEM", style="SidebarCaption.TLabel").grid(
            row=1, column=1, sticky="nw", pady=(2, 0)
        )

        ttk.Label(
            sidebar, text="WORKSPACE", style="SidebarSection.TLabel"
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 8))
        navigation = (
            ("overview", "⌂", "Overview", None),
            ("monitoring", "◉", "Live monitoring", self._open_monitoring_view),
            ("history", "▤", "History", self._open_history_view),
            ("remediation", "✓", "Remediation plan", self._open_remediation_view),
        )
        self._navigation_buttons = {}
        for row, (key, icon, label, command) in enumerate(navigation, start=2):
            button = ttk.Button(
                sidebar,
                text=f"  {icon}   {label}",
                style="SidebarActive.TButton" if key == "overview" else "SidebarNav.TButton",
                command=lambda page=key, callback=command: self._navigate(page, callback),
            )
            button.grid(row=row, column=0, sticky="ew", padx=10, pady=2)
            self._navigation_buttons[key] = button

        ttk.Label(
            sidebar, text="PREFERENCES", style="SidebarSection.TLabel"
        ).grid(row=6, column=0, sticky="w", padx=20, pady=(28, 8))
        settings_button = ttk.Button(
            sidebar,
            text="  ⚙   Settings",
            style="SidebarNav.TButton",
            command=lambda: self._navigate("settings", self._open_settings_view),
        )
        settings_button.grid(row=7, column=0, sticky="ew", padx=10, pady=2)
        self._navigation_buttons["settings"] = settings_button
        sidebar.rowconfigure(8, weight=1)

        sidebar.columnconfigure(0, weight=1)
        footer = ttk.Frame(sidebar, padding=(18, 14), style="Sidebar.TFrame")
        footer.grid(row=8, column=0, sticky="sew")
        ttk.Label(footer, text="NETWORK OPERATIONS", style="SidebarCaption.TLabel").pack(anchor="w")
        ttk.Label(footer, text="Local monitoring console", style="SidebarCaption.TLabel").pack(
            anchor="w", pady=(3, 0)
        )

        workspace = ttk.Frame(self, style="Dashboard.TFrame")
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(1, weight=1)

        header = ttk.Frame(workspace, padding=(24, 14), style="AppHeader.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Smart Network Diagnosis System",
            style="AppHeaderTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._clock_label = ttk.Label(header, text="", style="AppHeaderMuted.TLabel")
        self._clock_label.grid(row=0, column=1, sticky="e", padx=(12, 20))
        self._header_monitoring_label = ttk.Label(
            header,
            text="●  MONITORING STOPPED",
            style="AppHeaderMuted.TLabel",
            foreground=_PALETTE["muted"],
        )
        self._header_monitoring_label.grid(row=0, column=2, sticky="e", padx=(0, 16))
        ttk.Button(
            header,
            text="Refresh",
            style="Secondary.TButton",
            command=self.refresh_network_info,
        ).grid(row=0, column=3, sticky="e", padx=(0, 8))
        ttk.Button(
            header,
            text="Settings",
            style="Secondary.TButton",
            command=lambda: self._navigate("settings", self._open_settings_view),
        ).grid(row=0, column=4, sticky="e")

        content_area = ttk.Frame(workspace, style="Dashboard.TFrame")
        content_area.grid(row=1, column=0, sticky="nsew")
        content_area.columnconfigure(0, weight=1)
        content_area.rowconfigure(0, weight=1)
        self._scroll_canvas = tk.Canvas(
            content_area,
            highlightthickness=0,
            borderwidth=0,
            background=_PALETTE["background"],
        )
        self._scrollbar = ttk.Scrollbar(
            content_area, orient="vertical", command=self._scroll_canvas.yview
        )
        self._scroll_content = ttk.Frame(
            self._scroll_canvas, padding=(28, 24), style="Dashboard.TFrame"
        )
        self._scroll_window = self._scroll_canvas.create_window(
            (0, 0), window=self._scroll_content, anchor="nw"
        )
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")
        self._scroll_content.bind("<Configure>", self._on_scroll_content_configure)
        self._scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._clock_job = None
        self._update_clock()

    def _navigate(self, page: str, callback=None) -> None:
        for key, button in self._navigation_buttons.items():
            button.configure(
                style="SidebarActive.TButton" if key == page else "SidebarNav.TButton"
            )
        if callback is not None:
            callback()

    def _update_clock(self) -> None:
        self._clock_label.configure(
            text=datetime.datetime.now().strftime("%a, %b %d  ·  %I:%M:%S %p")
        )
        self._clock_job = self.after(1000, self._update_clock)

    def _set_header_monitoring_status(self, running: bool) -> None:
        if running:
            self._header_monitoring_label.configure(
                text="●  MONITORING ACTIVE",
                foreground=_PALETTE["success"],
            )
        else:
            self._header_monitoring_label.configure(
                text="●  MONITORING STOPPED",
                foreground=_PALETTE["muted"],
            )

    def _on_scroll_content_configure(self, _event=None) -> None:
        """Update the scrollable region when dashboard content changes size."""
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_scroll_canvas_configure(self, event) -> None:
        """Keep the content as wide as the visible canvas."""
        self._scroll_canvas.itemconfigure(self._scroll_window, width=event.width)
        wraplength = max(280, event.width - 110)
        for label_map_name in ("_correlation_labels", "_recommendation_labels"):
            label_map = getattr(self, label_map_name, {})
            for label in label_map.values():
                label.configure(wraplength=wraplength)

    def _on_mousewheel(self, event) -> None:
        """Allow scrolling with the mouse wheel while the dashboard is visible."""
        if self.winfo_exists():
            self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        content = self._scroll_content
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        title = ttk.Frame(content, style="Dashboard.TFrame")
        title.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        ttk.Label(title, text="Network overview", style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title,
            text="Monitor connectivity, review diagnostics, and track network health.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        status_card, status_body = create_card(
            content,
            "Network status",
            "Current connection state, refreshed automatically from this device.",
        )
        status_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        status_row = ttk.Frame(status_body, style="Card.TFrame")
        status_row.pack(fill="x")
        status_row.columnconfigure(1, weight=1)
        ttk.Label(status_row, text="CONNECTION", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 20)
        )
        self._status_value_label = ttk.Label(
            status_row, text="Checking...", style="MetricValue.TLabel"
        )
        self._status_value_label.grid(row=0, column=1, sticky="w")
        self._last_updated_label = ttk.Label(status_row, text="", style="CardMuted.TLabel")
        self._last_updated_label.grid(row=0, column=2, sticky="e", padx=(12, 0))

        config_card, config_body = create_card(content, "Network configuration")
        config_card.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 14))
        controls_card, controls_body = create_card(content, "Monitoring controls", "Start or stop background network checks.")
        controls_card.grid(row=2, column=1, sticky="nsew", padx=(7, 0), pady=(0, 14))

        config_inner = ttk.Frame(config_body, style="Card.TFrame")
        config_inner.pack(fill="x")
        config_inner.columnconfigure(1, weight=1)
        config_inner.columnconfigure(3, weight=1)
        self._field_labels = {}
        fields = [
            ("interface", "Interface"),
            ("connection_type", "Connection"),
            ("ipv4", "IPv4 address"),
            ("mac_address", "MAC address"),
            ("gateway", "Gateway"),
            ("dns", "DNS server(s)"),
        ]
        for index, (key, caption) in enumerate(fields):
            row, pair = divmod(index, 2)
            label_column = pair * 2
            value_column = label_column + 1
            ttk.Label(config_inner, text=caption, style="CardMuted.TLabel").grid(
                row=row, column=label_column, sticky="w", padx=(0, 8), pady=7
            )
            value = ttk.Label(
                config_inner, text="—", style="Card.TLabel", wraplength=260, justify="left"
            )
            value.grid(row=row, column=value_column, sticky="w", padx=(0, 14), pady=7)
            self._field_labels[key] = value
        config_actions = ttk.Frame(config_body, style="Card.TFrame")
        config_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(
            config_actions,
            text="Refresh details",
            style="Secondary.TButton",
            command=self.refresh_network_info,
        ).pack(anchor="w")

        self._start_button = ttk.Button(
            controls_body,
            text="Start monitoring",
            style="Primary.TButton",
            command=self._on_start_clicked,
        )
        self._start_button.pack(anchor="w", pady=(0, 8))
        self._stop_button = ttk.Button(
            controls_body,
            text="Stop monitoring",
            style="Secondary.TButton",
            command=self._on_stop_clicked,
            state="disabled",
        )
        self._stop_button.pack(anchor="w")
        self._monitoring_state_label = ttk.Label(
            controls_body,
            text="Monitoring: STOPPED",
            style="Card.TLabel",
            font=(font_family(self), 10, "bold"),
            foreground=_PALETTE["danger"],
        )
        self._monitoring_state_label.pack(anchor="w", pady=(14, 0))
        self._records_stored_label = ttk.Label(
            controls_body, text="Records stored: 0", style="CardMuted.TLabel"
        )
        self._records_stored_label.pack(anchor="w", pady=(6, 0))

        metrics_card, metrics_body = create_card(content, "Live metrics", "Latest results from the monitoring session.")
        metrics_card.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        for column in range(3):
            metrics_body.columnconfigure(column, weight=1, uniform="metric")
        self._metric_labels = {}
        metric_fields = [
            ("gateway", "Gateway"),
            ("internet", "Internet"),
            ("dns", "DNS"),
            ("packet_loss", "Packet loss"),
            ("jitter", "Jitter"),
            ("http", "HTTP"),
        ]
        for index, (key, caption) in enumerate(metric_fields):
            row, column = divmod(index, 3)
            metric = ttk.Frame(metrics_body, style="Card.TFrame", padding=(12, 10))
            metric.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
            ttk.Label(metric, text=caption.upper(), style="CardMuted.TLabel").pack(anchor="w")
            value_label = ttk.Label(metric, text="—", style="MetricValue.TLabel")
            value_label.pack(anchor="w", pady=(7, 0))
            self._metric_labels[key] = value_label

        temporal_card, temporal_body = create_card(content, "Trend analysis", "Recent measurements identify persistent or intermittent degradation.")
        temporal_card.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        temporal_inner = ttk.Frame(temporal_body, style="Card.TFrame")
        temporal_inner.pack(fill="x")
        temporal_inner.columnconfigure(1, weight=1)
        temporal_inner.columnconfigure(3, weight=1)
        self._temporal_labels = {}
        temporal_fields = [
            ("status", "Analysis status"),
            ("condition", "Current condition"),
            ("degradation", "Degradation"),
            ("severity", "Severity"),
            ("high_latency", "High latency"),
            ("packet_loss", "Packet loss"),
            ("high_jitter", "High jitter"),
            ("gateway_problem", "Gateway problem"),
            ("internet_problem", "Internet problem"),
            ("dns_degradation", "DNS degradation"),
            ("http_degradation", "HTTP degradation"),
            ("recovery", "Recovery observed"),
        ]
        for index, (key, caption) in enumerate(temporal_fields):
            row, pair = divmod(index, 2)
            label_column = pair * 2
            value_column = label_column + 1
            ttk.Label(temporal_inner, text=caption, style="CardMuted.TLabel").grid(
                row=row, column=label_column, sticky="w", padx=(0, 9), pady=6
            )
            value = ttk.Label(temporal_inner, text="—", style="Card.TLabel")
            value.grid(row=row, column=value_column, sticky="w", padx=(0, 20), pady=6)
            self._temporal_labels[key] = value

        correlation_card, correlation_body = create_card(content, "Correlation diagnosis", "Correlated symptoms and supporting evidence.")
        correlation_card.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        correlation_body.columnconfigure(0, weight=1)
        self._correlation_labels = {}
        correlation_fields = [
            ("status", "Diagnosis status"),
            ("category", "Probable fault category"),
            ("symptoms", "Correlated symptoms"),
            ("evidence", "Supporting evidence"),
        ]
        for row, (key, caption) in enumerate(correlation_fields):
            ttk.Label(correlation_body, text=caption, style="CardMuted.TLabel").grid(
                row=row + 2, column=0, sticky="nw", pady=5, padx=(0, 14)
            )
            value = ttk.Label(
                correlation_body,
                text="—",
                style="Card.TLabel",
                wraplength=900,
                justify="left",
            )
            value.grid(row=row + 2, column=1, sticky="w", pady=5)
            self._correlation_labels[key] = value
        correlation_body.columnconfigure(1, weight=1)

        recommendation_card, recommendation_body = create_card(
            content, "Recommended next steps", "Suggested actions based on the latest diagnosis."
        )
        recommendation_card.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        recommendation_body.columnconfigure(1, weight=1)
        self._recommendation_labels = {}
        recommendation_fields = [
            ("root_cause", "Probable root cause"),
            ("explanation", "Explanation"),
            ("severity", "Severity"),
            ("fixes", "Suggested fixes"),
            ("verification", "Verification steps"),
        ]
        for row, (key, caption) in enumerate(recommendation_fields, start=2):
            ttk.Label(recommendation_body, text=caption, style="CardMuted.TLabel").grid(
                row=row, column=0, sticky="nw", pady=5, padx=(0, 14)
            )
            value = ttk.Label(
                recommendation_body,
                text="Waiting for diagnosis...",
                style="Card.TLabel",
                wraplength=900,
                justify="left",
            )
            value.grid(row=row, column=1, sticky="w", pady=5)
            self._recommendation_labels[key] = value

        history_card, history_body = create_card(content, "Recent measurements", "Latest samples collected during monitoring.")
        history_card.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
        content.rowconfigure(7, weight=1)
        columns = ("time", "gateway", "internet", "latency", "packet_loss", "jitter", "dns", "http")
        headings = {
            "time": "Time",
            "gateway": "Gateway",
            "internet": "Internet",
            "latency": "Latency",
            "packet_loss": "Packet loss",
            "jitter": "Jitter",
            "dns": "DNS",
            "http": "HTTP",
        }
        table_frame = ttk.Frame(history_body, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self._history_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        for column in columns:
            self._history_tree.heading(column, text=headings[column])
            self._history_tree.column(column, width=100, minwidth=78, anchor="center", stretch=True)
        self._history_tree.grid(row=0, column=0, sticky="nsew")
        history_y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self._history_tree.yview)
        history_y_scroll.grid(row=0, column=1, sticky="ns")
        history_x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self._history_tree.xview)
        history_x_scroll.grid(row=1, column=0, sticky="ew")
        self._history_tree.configure(
            yscrollcommand=history_y_scroll.set, xscrollcommand=history_x_scroll.set
        )

        note = ttk.Label(
            content,
            text=(
                "Diagnosis combines network measurements, temporal trends, and correlated symptoms. "
                "Fault categories are hypotheses, not proof."
            ),
            style="Muted.TLabel",
            wraplength=900,
            justify="left",
        )
        note.grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 8))
        self._update_records_stored_label()
        self._set_correlation_insufficient("Start monitoring to collect measurements.")

    # ------------------------------------------------------------------
    # Phase 1 behaviour: network configuration
    # ------------------------------------------------------------------

    def refresh_network_info(self) -> None:
        try:
            snapshot = self._interface_monitor.refresh()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to refresh network info: %s", exc)
            self._status_value_label.configure(text="ERROR", foreground=_STATUS_COLORS["Unknown"])
            return

        if not self._monitor_controller.is_running():
            status_text = snapshot.status if snapshot.status else "Unknown"
            self._status_value_label.configure(
                text=status_text.upper(), foreground=_STATUS_COLORS.get(status_text, _STATUS_COLORS["Unknown"])
            )

        self._field_labels["interface"].configure(text=snapshot.interface or "Not detected")
        self._field_labels["connection_type"].configure(text=snapshot.connection_type or "Unknown")
        self._field_labels["ipv4"].configure(text=snapshot.ipv4 or "Not assigned")
        self._field_labels["mac_address"].configure(text=snapshot.mac_address or "Unknown")
        self._field_labels["gateway"].configure(text=snapshot.gateway or "Not detected")
        self._field_labels["dns"].configure(text=snapshot.dns_display)
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_updated_label.configure(text=f"Last updated: {now_text}")

    def _schedule_auto_refresh(self) -> None:
        if self._auto_refresh_job is not None:
            try:
                self.after_cancel(self._auto_refresh_job)
            except tk.TclError:
                pass
            self._auto_refresh_job = None
        interval_seconds = self._settings.get("network_info_refresh_seconds", 5)
        interval_ms = max(1, int(interval_seconds)) * 1000

        def _tick():
            self.refresh_network_info()
            self._auto_refresh_job = self.after(interval_ms, _tick)

        self._auto_refresh_job = self.after(interval_ms, _tick)

    # ------------------------------------------------------------------
    # Phase 2/3 behaviour: monitoring controls
    # ------------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        session_id = self._monitor_controller.start()
        if session_id is None:
            messagebox.showerror(
                "Smart Network Diagnosis System",
                "Could not start monitoring: the database session could not be created. "
                "Check the log file in the logs/ folder for details.",
            )
            return
        self._start_button.configure(state="disabled")
        self._stop_button.configure(state="normal")
        self._monitoring_state_label.configure(
            text=f"Monitoring: RUNNING (session #{session_id})", foreground=_PALETTE["success"]
        )
        self._set_header_monitoring_status(True)
        self._start_poll_loop()
        logger.info("User started monitoring (session #%s).", session_id)

    def _on_stop_clicked(self) -> None:
        self._monitor_controller.stop()
        self._start_button.configure(state="normal")
        self._stop_button.configure(state="disabled")
        self._monitoring_state_label.configure(text="Monitoring: STOPPED", foreground=_PALETTE["danger"])
        self._set_header_monitoring_status(False)
        self._stop_poll_loop()
        logger.info("User stopped monitoring.")

    def _start_poll_loop(self) -> None:
        def _tick():
            self._poll_monitor_updates()
            if self._monitor_controller.is_running():
                self._poll_job = self.after(_POLL_INTERVAL_MS, _tick)
        self._poll_job = self.after(_POLL_INTERVAL_MS, _tick)

    def _stop_poll_loop(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except Exception:  # noqa: BLE001
                pass
            self._poll_job = None

    
    def _poll_monitor_updates(self) -> None:
        records = self._monitor_controller.get_updates_nowait()

        for record in records:
            self._update_live_metrics(record)
            self._append_inline_history_row(record)
            self._update_records_stored_label()

            if self._monitoring_view is not None:
                try:
                    updated = self._monitoring_view.push_record(record)
                    if not updated:
                        self._monitoring_view = None
                except tk.TclError:
                    self._monitoring_view = None

        if records:
            self._run_temporal_analysis()

    def _run_temporal_analysis(self) -> None:
        try:
            detection = analyze_recent_measurements(self._database, self._settings)
        except Exception:  # noqa: BLE001
            logger.exception("Temporal analysis failed.")
            self._set_correlation_insufficient("Temporal analysis could not be completed.")
            return

        self._update_temporal_analysis_panel(detection)
        self._update_correlation_diagnosis(detection)

    def _update_temporal_analysis_panel(self, result) -> None:
        labels = self._temporal_labels
        if result.analysis_status != "SUFFICIENT_DATA":
            labels["status"].configure(text="INSUFFICIENT DATA", foreground=_STATUS_COLORS["Unknown"])
            for key in (
                "condition", "degradation", "severity", "high_latency", "packet_loss",
                "high_jitter", "gateway_problem", "internet_problem",
                "dns_degradation", "http_degradation", "recovery",
            ):
                labels[key].configure(text="—", foreground=_PALETTE["muted"])
            return

        labels["status"].configure(text="SUFFICIENT DATA", foreground=_STATUS_COLORS["NORMAL"])
        condition_text = "DEGRADED" if result.degraded else "NORMAL"
        labels["condition"].configure(
            text=condition_text, foreground=_STATUS_COLORS.get(condition_text, _STATUS_COLORS["Unknown"])
        )
        if result.persistent:
            degradation_text = "PERSISTENT"
        elif result.intermittent:
            degradation_text = "INTERMITTENT"
        else:
            degradation_text = "NONE"
        labels["degradation"].configure(
            text=degradation_text, foreground=_STATUS_COLORS.get(degradation_text, _STATUS_COLORS["Unknown"])
        )
        labels["severity"].configure(
            text=result.severity, foreground=_SEVERITY_COLORS.get(result.severity, _STATUS_COLORS["Unknown"])
        )

        def _yes_no(flag: bool) -> str:
            return "YES" if flag else "NO"

        def _flag_color(flag: bool) -> str:
            return _STATUS_COLORS["DEGRADED"] if flag else _STATUS_COLORS["NORMAL"]

        for key, flag in (
            ("high_latency", result.high_latency),
            ("packet_loss", result.packet_loss_detected),
            ("high_jitter", result.high_jitter),
            ("gateway_problem", result.gateway_problem),
            ("internet_problem", result.internet_problem),
            ("dns_degradation", result.dns_degradation),
            ("http_degradation", result.http_degradation),
            ("recovery", result.recovery_observed),
        ):
            labels[key].configure(text=_yes_no(flag), foreground=_flag_color(flag))

    # ------------------------------------------------------------------
    # Phase 5: correlation diagnosis
    # ------------------------------------------------------------------

    def _set_correlation_insufficient(self, reason: str) -> None:
        self._correlation_labels["status"].configure(
            text="INSUFFICIENT DATA", foreground=_STATUS_COLORS["INSUFFICIENT DATA"]
        )
        self._correlation_labels["category"].configure(
            text="UNDETERMINED", foreground=_PALETTE["warning"]
        )
        self._correlation_labels["symptoms"].configure(text="—")
        self._correlation_labels["evidence"].configure(text=reason)

    def _update_correlation_diagnosis(self, detection) -> None:
        """Correlate the Phase 4 result with the newest saved database row."""
        try:
            recent_rows = self._database.get_recent_measurements(limit=1)
            if not recent_rows:
                self._set_correlation_insufficient("No saved measurements are available yet.")
                return

            # Database.get_recent_measurements returns dictionaries, newest first.
            latest = dict(recent_rows[0])
            result = correlate_symptoms(detection, latest)
        except Exception:  # noqa: BLE001
            logger.exception("Correlation diagnosis failed.")
            self._set_correlation_insufficient("Correlation analysis failed. Check the logs for details.")
            return

        status_color = _STATUS_COLORS.get(result.status, _STATUS_COLORS["Unknown"])
        self._correlation_labels["status"].configure(text=result.status.replace("_", " "), foreground=status_color)
        self._correlation_labels["category"].configure(
            text=result.probable_category.replace("_", " "),
            foreground=(
                _PALETTE["success"]
                if result.probable_category == "NO_PERSISTENT_DEGRADATION_DETECTED"
                else _PALETTE["warning"]
            ),
        )
        symptoms_text = ", ".join(item.replace("_", " ") for item in result.correlated_symptoms)
        self._correlation_labels["symptoms"].configure(text=symptoms_text or "No active correlated symptoms")
        evidence_text = "\n".join(f"• {item}" for item in result.evidence) if result.evidence else "No supporting evidence available."
        self._correlation_labels["evidence"].configure(text=evidence_text)
        self._update_recommendation_panel(result)

    
    def _update_recommendation_panel(self, correlation) -> None:
        """Display recommendations generated from the latest diagnosis."""
        try:
            recommendation = generate_recommendations(correlation)

            self._recommendation_labels["root_cause"].configure(
                text=recommendation.root_cause
            )
            self._recommendation_labels["explanation"].configure(
                text=recommendation.explanation
            )
            self._recommendation_labels["severity"].configure(
                text=recommendation.severity
            )
            self._recommendation_labels["fixes"].configure(
                text="\n".join(
                    f"{i}. {item}"
                    for i, item in enumerate(
                        recommendation.suggested_fixes, start=1
                    )
                ) or "No fixes suggested."
            )
            self._recommendation_labels["verification"].configure(
                text="\n".join(
                    f"{i}. {item}"
                    for i, item in enumerate(
                        recommendation.verification_steps, start=1
                    )
                ) or "No verification steps available."
            )

        except Exception:
            logger.exception("Phase 6 recommendation update failed.")
            for label in self._recommendation_labels.values():
                label.configure(
                    text="Recommendations unavailable. Check application logs."
                )


    # ------------------------------------------------------------------
    # Live metrics and history
    # ------------------------------------------------------------------

    def _update_live_metrics(self, record) -> None:
        self._status_value_label.configure(
            text=record.overall_status,
            foreground=_STATUS_COLORS.get(record.overall_status, _STATUS_COLORS["Unknown"]),
        )
        gateway_status = "PASS" if record.gateway_reachable else "FAIL"
        internet_status = "PASS" if record.internet_reachable else "FAIL"
        dns_status = "SUCCESS" if record.dns_success else "FAILED"
        http_status = "SUCCESS" if record.http_status_code is not None and record.http_status_code < 400 else "FAILED"

        def _fmt(status, value, unit=""):
            if value is None:
                return status
            return f"{status}    {value} {unit}".strip()

        self._metric_labels["gateway"].configure(text=_fmt(gateway_status, record.gateway_latency_ms, "ms"))
        self._metric_labels["internet"].configure(text=_fmt(internet_status, record.internet_latency_ms, "ms"))
        self._metric_labels["dns"].configure(text=_fmt(dns_status, record.dns_response_time_ms, "ms"))
        self._metric_labels["packet_loss"].configure(text=f"{record.internet_packet_loss}%")
        self._metric_labels["jitter"].configure(
            text=f"{record.jitter_ms} ms" if record.jitter_ms is not None else "-"
        )
        status_code_text = f"HTTP {record.http_status_code}" if record.http_status_code is not None else http_status
        self._metric_labels["http"].configure(text=_fmt(status_code_text, record.http_response_time_ms, "ms"))

    def _append_inline_history_row(self, record) -> None:
        time_text = record.timestamp.split("T")[-1] if "T" in record.timestamp else record.timestamp
        self._history_tree.insert(
            "", "end",
            values=(
                time_text,
                "PASS" if record.gateway_reachable else "FAIL",
                "PASS" if record.internet_reachable else "FAIL",
                f"{record.internet_latency_ms} ms" if record.internet_latency_ms is not None else "-",
                f"{record.internet_packet_loss}%",
                f"{record.jitter_ms} ms" if record.jitter_ms is not None else "-",
                "PASS" if record.dns_success else "FAIL",
                record.http_status_code if record.http_status_code is not None else "FAIL",
            ),
        )
        children = self._history_tree.get_children()
        max_rows = 50
        if len(children) > max_rows:
            for row_id in children[: len(children) - max_rows]:
                self._history_tree.delete(row_id)
        self._history_tree.yview_moveto(1.0)

    def _update_records_stored_label(self) -> None:
        try:
            count = self._database.get_measurement_count()
        except Exception:  # noqa: BLE001
            count = 0
        self._records_stored_label.configure(text=f"Records Stored: {count}")

    

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _open_monitoring_view(self) -> None:
        from gui.monitoring_view import MonitoringView
        if self._monitoring_view is not None:
            try:
                self._monitoring_view.lift()
                self._monitoring_view.focus_force()
                return
            except tk.TclError:
                self._monitoring_view = None
        self._monitoring_view = MonitoringView(self)

    def _open_history_view(self) -> None:
        from gui.history_view import HistoryView
        if self._history_view is not None:
            try:
                self._history_view.refresh()
                self._history_view.lift()
                self._history_view.focus_force()
                return
            except tk.TclError:
                self._history_view = None
        self._history_view = HistoryView(self, self._database)

    def _open_remediation_view(self) -> None:
        from gui.remediation_view import RemediationReviewView
        if self._remediation_view is not None:
            try:
                self._remediation_view.refresh()
                self._remediation_view.lift()
                self._remediation_view.focus_force()
                return
            except tk.TclError:
                self._remediation_view = None
        self._remediation_view = RemediationReviewView(self, self._database)

    def _apply_settings(self, settings: dict) -> None:
        self._monitor_controller.update_settings(settings)
        self._settings = dict(settings)
        self._schedule_auto_refresh()

    def _open_settings_view(self) -> None:
        from gui.settings_view import SettingsView
        if self._settings_view is not None:
            try:
                self._settings_view.lift()
                self._settings_view.focus_force()
                return
            except tk.TclError:
                self._settings_view = None
        self._settings_view = SettingsView(
            self,
            on_saved=self._apply_settings,
            monitoring_running=self._monitor_controller.is_running,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def destroy(self) -> None:
        if self._clock_job is not None:
            try:
                self.after_cancel(self._clock_job)
            except tk.TclError:
                pass
            self._clock_job = None
        if self._auto_refresh_job is not None:
            try:
                self.after_cancel(self._auto_refresh_job)
            except Exception:  # noqa: BLE001
                pass
        self._stop_poll_loop()
        try:
            if self._monitor_controller.is_running():
                self._monitor_controller.stop(final_status="INTERRUPTED")
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping monitor controller during shutdown.")
        try:
            self._database.close()
        except Exception:  # noqa: BLE001
            pass
        super().destroy()
