"""
Live monitoring window.

The dashboard drains MonitorController's background queue on the Tkinter
thread and forwards each record here. All widget and chart updates therefore
remain on the UI thread; chart redraws are coalesced with ``after()``.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from monitoring.monitor_controller import MeasurementRecord  # noqa: E402
from utils.logger import get_logger  # noqa: E402
from gui.theme import PALETTE, configure_styles, font_family  # noqa: E402

logger = get_logger(__name__)

MAX_POINTS = 60
MAX_TABLE_ROWS = 200
CHART_REDRAW_DELAY_MS = 180

_COLORS = {
    "background": PALETTE["background"],
    "surface": PALETTE["surface"],
    "text": PALETTE["text"],
    "muted": PALETTE["muted"],
    "blue": PALETTE["primary"],
    "purple": PALETTE["primary_dark"],
    "red": PALETTE["danger"],
    "orange": PALETTE["warning"],
    "green": PALETTE["success"],
    "teal": PALETTE["info"],
    "border": PALETTE["border"],
}


class MonitoringView(tk.Toplevel):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.title("Live Network Monitoring")
        self.geometry("1240x850")
        self.minsize(900, 620)
        self.configure(background=_COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._timestamps: List[str] = []
        self._series: Dict[str, List[float]] = {
            "gateway_latency": [],
            "internet_latency": [],
            "gateway_packet_loss": [],
            "internet_packet_loss": [],
            "jitter": [],
            "dns_latency": [],
            "http_latency": [],
        }
        self._sample_count = 0
        self._redraw_job: Optional[str] = None

        self._configure_styles()
        self._build_widgets()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        configure_styles(style)
        family = font_family(self)
        style.configure("Monitor.TFrame", background=_COLORS["background"])
        style.configure(
            "MonitorCard.TFrame",
            background=_COLORS["surface"],
            relief="solid",
            borderwidth=1,
            bordercolor=_COLORS["border"],
        )
        style.configure(
            "MonitorTitle.TLabel",
            background=_COLORS["background"],
            foreground=_COLORS["text"],
            font=(family, 24, "bold"),
        )
        style.configure(
            "MonitorSubtitle.TLabel",
            background=_COLORS["background"],
            foreground=_COLORS["muted"],
            font=(family, 9),
        )
        style.configure(
            "MonitorSection.TLabel",
            background=_COLORS["surface"],
            foreground=_COLORS["text"],
            font=(family, 15, "bold"),
        )
        style.configure(
            "MonitorMuted.TLabel",
            background=_COLORS["surface"],
            foreground=_COLORS["muted"],
            font=(family, 9),
        )
        style.configure(
            "MonitorValue.TLabel",
            background=_COLORS["surface"],
            foreground=_COLORS["text"],
            font=(family, 18, "bold"),
        )
        style.configure(
            "Monitor.Treeview",
            rowheight=32,
            background=_COLORS["surface"],
            fieldbackground=_COLORS["surface"],
            foreground=_COLORS["text"],
            font=(family, 9),
            bordercolor=_COLORS["border"],
        )
        style.configure(
            "Monitor.Treeview.Heading",
            background=PALETTE["table_header"],
            foreground=_COLORS["text"],
            font=(family, 9, "bold"),
            padding=(8, 8),
        )
        style.map(
            "Monitor.Treeview",
            background=[("selected", PALETTE["selection"])],
            foreground=[("selected", _COLORS["text"])],
        )

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=(20, 18), style="Monitor.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer, style="Monitor.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Live monitoring", style="MonitorTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Connectivity measurements update as each monitoring cycle completes.",
            style="MonitorSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._activity_label = ttk.Label(
            header, text="Waiting for first measurement", style="MonitorSubtitle.TLabel"
        )
        self._activity_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=(14, 0))

        summary = ttk.Frame(outer, style="Monitor.TFrame")
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for column in range(3):
            summary.columnconfigure(column, weight=1, uniform="summary")
        self._summary_values = {}
        summary_items = (
            ("overall", "OVERALL STATUS"),
            ("gateway", "GATEWAY"),
            ("internet", "INTERNET"),
            ("packet_loss", "PACKET LOSS"),
            ("dns", "DNS RESPONSE"),
            ("http", "HTTP RESPONSE"),
        )
        for index, (key, title) in enumerate(summary_items):
            row, column = divmod(index, 3)
            card = ttk.Frame(summary, style="MonitorCard.TFrame", padding=(12, 11))
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 5, 0),
                pady=(0 if row == 0 else 8, 0),
            )
            ttk.Label(card, text=title, style="MonitorMuted.TLabel").pack(anchor="w")
            value = ttk.Label(card, text="—", style="MonitorValue.TLabel")
            value.pack(anchor="w", pady=(6, 0))
            self._summary_values[key] = value

        paned = ttk.Panedwindow(outer, orient="vertical")
        paned.grid(row=2, column=0, sticky="nsew")

        table_frame = ttk.Frame(paned, padding=(12, 10), style="MonitorCard.TFrame")
        paned.add(table_frame, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        ttk.Label(table_frame, text="Measurement records", style="MonitorSection.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        columns = (
            "timestamp",
            "interface",
            "gateway",
            "gateway_latency",
            "gateway_loss",
            "internet",
            "internet_latency",
            "internet_loss",
            "jitter",
            "dns",
            "dns_latency",
            "http_status",
            "http_latency",
            "overall",
            "bytes",
        )
        headings = {
            "timestamp": "Timestamp",
            "interface": "Interface",
            "gateway": "Gateway",
            "gateway_latency": "GW latency (ms)",
            "gateway_loss": "GW loss (%)",
            "internet": "Internet",
            "internet_latency": "Internet latency (ms)",
            "internet_loss": "Internet loss (%)",
            "jitter": "Jitter (ms)",
            "dns": "DNS",
            "dns_latency": "DNS response (ms)",
            "http_status": "HTTP status",
            "http_latency": "HTTP response (ms)",
            "overall": "Overall",
            "bytes": "Est. bytes",
        }
        widths = {
            "timestamp": 155,
            "interface": 115,
            "gateway": 78,
            "gateway_latency": 110,
            "gateway_loss": 92,
            "internet": 78,
            "internet_latency": 130,
            "internet_loss": 105,
            "jitter": 95,
            "dns": 65,
            "dns_latency": 120,
            "http_status": 90,
            "http_latency": 120,
            "overall": 105,
            "bytes": 90,
        }
        self._tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=7, style="Monitor.Treeview"
        )
        for column in columns:
            self._tree.heading(column, text=headings[column])
            self._tree.column(
                column,
                width=widths[column],
                minwidth=70,
                anchor="center",
                stretch=False,
            )
        self._tree.grid(row=1, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self._tree.xview)
        x_scroll.grid(row=2, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self._tree.tag_configure("normal", foreground=_COLORS["green"])
        self._tree.tag_configure("degraded", foreground=_COLORS["orange"])
        self._tree.tag_configure("disconnected", foreground=_COLORS["red"])

        charts_frame = ttk.Frame(paned, padding=(12, 10), style="MonitorCard.TFrame")
        paned.add(charts_frame, weight=2)
        charts_frame.rowconfigure(1, weight=1)
        charts_frame.columnconfigure(0, weight=1)
        ttk.Label(charts_frame, text="Measurement trends", style="MonitorSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        chart_font = font_family(self)
        self._figure = Figure(figsize=(11, 5.5), dpi=90, facecolor=_COLORS["surface"])
        chart_specs = (
            ("gateway_latency", "Gateway latency", "ms", _COLORS["purple"]),
            ("internet_latency", "Internet latency", "ms", _COLORS["blue"]),
            ("packet_loss", "Packet loss (gateway / internet)", "%", _COLORS["red"]),
            ("jitter", "Jitter", "ms", _COLORS["orange"]),
            ("dns_latency", "DNS response time", "ms", _COLORS["green"]),
            ("http_latency", "HTTP response time", "ms", _COLORS["teal"]),
        )
        self._axes = {}
        self._lines = {}
        self._chart_series = {}
        self._empty_labels = {}
        for index, (key, title, unit, color) in enumerate(chart_specs, start=1):
            axis = self._figure.add_subplot(2, 3, index)
            axis.set_facecolor(_COLORS["surface"])
            axis.set_title(title, fontsize=9, color=_COLORS["text"], pad=7, fontfamily=chart_font)
            axis.set_ylabel(unit, fontsize=8, color=_COLORS["muted"], fontfamily=chart_font)
            axis.tick_params(axis="both", labelsize=7, colors=_COLORS["muted"])
            for tick_label in (*axis.get_xticklabels(), *axis.get_yticklabels()):
                tick_label.set_fontfamily(chart_font)
            axis.grid(True, color=_COLORS["border"], linewidth=0.7)
            axis.spines[["top", "right"]].set_visible(False)
            axis.spines[["left", "bottom"]].set_color(_COLORS["border"])
            if key == "packet_loss":
                internet_line, = axis.plot(
                    [], [], color=color, linewidth=1.6, marker="o", markersize=2.5, label="Internet"
                )
                gateway_line, = axis.plot(
                    [],
                    [],
                    color=_COLORS["purple"],
                    linewidth=1.3,
                    linestyle="--",
                    marker=".",
                    markersize=3,
                    label="Gateway",
                )
                axis.legend(
                    loc="upper left",
                    fontsize=6,
                    frameon=False,
                    prop={"family": chart_font, "size": 6},
                )
                lines = (internet_line, gateway_line)
                series_keys = ("internet_packet_loss", "gateway_packet_loss")
            else:
                line, = axis.plot([], [], color=color, linewidth=1.6, marker="o", markersize=2.5)
                lines = (line,)
                series_keys = (key,)
            empty_label = axis.text(
                0.5,
                0.5,
                "Waiting for data",
                transform=axis.transAxes,
                ha="center",
                va="center",
                fontsize=8,
                color=_COLORS["muted"],
                fontfamily=chart_font,
            )
            self._axes[key] = axis
            self._lines[key] = lines
            self._chart_series[key] = series_keys
            self._empty_labels[key] = empty_label
        self._figure.tight_layout(pad=2.0)
        self._canvas = FigureCanvasTkAgg(self._figure, master=charts_frame)
        self._canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self._canvas.draw()

    @staticmethod
    def _format_number(value, precision: int = 1) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if not math.isfinite(number):
            return "—"
        return f"{number:.{precision}f}"

    @staticmethod
    def _timestamp_label(timestamp) -> str:
        if not timestamp:
            return "—"
        timestamp = str(timestamp)
        return timestamp.replace("T", " ")

    def push_record(self, record: MeasurementRecord) -> bool:
        """Render one record; called by the dashboard's Tkinter-thread poll."""
        try:
            if not self.winfo_exists() or not self._tree.winfo_exists():
                return False

            self._append_table_row(record)
            self._append_graph_point(record)
            self._update_summary(record)
            self._sample_count += 1
            self._activity_label.configure(
                text=f"{self._sample_count} samples · latest {self._timestamp_label(getattr(record, 'timestamp', None))}"
            )
            self._schedule_graph_redraw()
            return True
        except tk.TclError:
            return False
        except Exception:
            logger.exception("Failed to render live measurement.")
            return True

    def _append_table_row(self, record: MeasurementRecord) -> None:
        def shown(value, precision=1):
            return self._format_number(value, precision)

        gateway_reachable = getattr(record, "gateway_reachable", None)
        internet_reachable = getattr(record, "internet_reachable", None)
        dns_success = getattr(record, "dns_success", None)
        http_status = getattr(record, "http_status_code", None)
        overall_status = str(getattr(record, "overall_status", "UNKNOWN") or "UNKNOWN")
        values = (
            self._timestamp_label(getattr(record, "timestamp", None)),
            getattr(record, "interface_name", None) or "—",
            self._reachability(gateway_reachable),
            shown(getattr(record, "gateway_latency_ms", None)),
            shown(getattr(record, "gateway_packet_loss", None)),
            self._reachability(internet_reachable),
            shown(getattr(record, "internet_latency_ms", None)),
            shown(getattr(record, "internet_packet_loss", None)),
            shown(getattr(record, "jitter_ms", None)),
            self._reachability(dns_success),
            shown(getattr(record, "dns_response_time_ms", None)),
            str(http_status) if http_status is not None else "—",
            shown(getattr(record, "http_response_time_ms", None)),
            overall_status,
            shown(getattr(record, "bytes_used", None), precision=0),
        )
        tag = overall_status.lower()
        if tag not in ("normal", "degraded", "disconnected"):
            tag = ""
        self._tree.insert("", "end", values=values, tags=(tag,) if tag else ())
        children = self._tree.get_children()
        if len(children) > MAX_TABLE_ROWS:
            for row_id in children[: len(children) - MAX_TABLE_ROWS]:
                self._tree.delete(row_id)
        self._tree.yview_moveto(1.0)

    @staticmethod
    def _reachability(value) -> str:
        if value is None:
            return "—"
        try:
            return "PASS" if bool(int(value)) else "FAIL"
        except (TypeError, ValueError):
            return "—"

    def _append_graph_point(self, record: MeasurementRecord) -> None:
        timestamp = getattr(record, "timestamp", None)
        self._timestamps.append(self._timestamp_label(timestamp).split(" ")[-1])
        self._series["gateway_latency"].append(
            self._numeric_value(getattr(record, "gateway_latency_ms", None))
        )
        self._series["internet_latency"].append(
            self._numeric_value(getattr(record, "internet_latency_ms", None))
        )
        self._series["gateway_packet_loss"].append(
            self._numeric_value(getattr(record, "gateway_packet_loss", None))
        )
        self._series["internet_packet_loss"].append(
            self._numeric_value(getattr(record, "internet_packet_loss", None))
        )
        self._series["jitter"].append(self._numeric_value(getattr(record, "jitter_ms", None)))
        self._series["dns_latency"].append(
            self._numeric_value(getattr(record, "dns_response_time_ms", None))
        )
        self._series["http_latency"].append(
            self._numeric_value(getattr(record, "http_response_time_ms", None))
        )
        for values in (self._timestamps, *self._series.values()):
            del values[: max(0, len(values) - MAX_POINTS)]

    @staticmethod
    def _numeric_value(value) -> float:
        if value is None:
            return float("nan")
        try:
            number = float(value)
        except (TypeError, ValueError):
            return float("nan")
        return number if math.isfinite(number) else float("nan")

    def _update_summary(self, record: MeasurementRecord) -> None:
        status = str(getattr(record, "overall_status", None) or "—").upper()
        status_color = {
            "NORMAL": _COLORS["green"],
            "DEGRADED": _COLORS["orange"],
            "DISCONNECTED": _COLORS["red"],
        }.get(status, _COLORS["text"])
        self._summary_values["overall"].configure(text=status, foreground=status_color)

        gateway = self._reachability(getattr(record, "gateway_reachable", None))
        internet = self._reachability(getattr(record, "internet_reachable", None))
        self._summary_values["gateway"].configure(
            text=f"{gateway}  ·  {self._append_unit(getattr(record, 'gateway_latency_ms', None), 'ms')}"
        )
        self._summary_values["internet"].configure(
            text=f"{internet}  ·  {self._append_unit(getattr(record, 'internet_latency_ms', None), 'ms')}"
        )
        internet_loss = self._format_number(getattr(record, "internet_packet_loss", None))
        self._summary_values["packet_loss"].configure(text=f"{internet_loss}%")
        self._summary_values["dns"].configure(
            text=self._append_unit(getattr(record, "dns_response_time_ms", None), "ms")
        )
        http_status = getattr(record, "http_status_code", None)
        http_time = self._append_unit(getattr(record, "http_response_time_ms", None), "ms")
        self._summary_values["http"].configure(
            text=f"HTTP {http_status if http_status is not None else '—'}  ·  {http_time}"
        )

    def _schedule_graph_redraw(self) -> None:
        if self._redraw_job is None:
            self._redraw_job = self.after(CHART_REDRAW_DELAY_MS, self._redraw_graphs)

    def _redraw_graphs(self) -> None:
        self._redraw_job = None
        if not self.winfo_exists():
            return

        x_positions = list(range(len(self._timestamps)))
        for key, axis in self._axes.items():
            values_by_series = [self._series[series_key] for series_key in self._chart_series[key]]
            for line, values in zip(self._lines[key], values_by_series):
                line.set_data(x_positions, values)
            has_data = any(
                math.isfinite(value) for values in values_by_series for value in values
            )
            self._empty_labels[key].set_visible(not has_data)
            if has_data:
                axis.relim()
                axis.autoscale_view()
                axis.set_xlim(max(-0.5, len(x_positions) - MAX_POINTS - 0.5), max(0.5, len(x_positions) - 0.5))
                step = max(1, len(x_positions) // 5)
                ticks = x_positions[::step]
                axis.set_xticks(ticks)
                axis.set_xticklabels(
                    [self._timestamps[index] for index in ticks],
                    rotation=25,
                    ha="right",
                    fontsize=6,
                )
            else:
                axis.set_xlim(-0.5, max(0.5, len(x_positions) - 0.5))
                axis.set_ylim(0, 1)
                axis.set_xticks([])
        self._canvas.draw_idle()

    @staticmethod
    def _append_unit(value, unit: str) -> str:
        formatted = MonitoringView._format_number(value)
        return f"{formatted} {unit}" if formatted != "—" else "—"

    def destroy(self) -> None:
        if self._redraw_job is not None:
            try:
                self.after_cancel(self._redraw_job)
            except tk.TclError:
                pass
            self._redraw_job = None
        super().destroy()
