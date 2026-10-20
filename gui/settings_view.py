"""Settings editor for values supported by config/settings.json."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict

from gui.theme import PALETTE, configure_styles, font_family
from utils.config_loader import load_settings, save_settings, validate_settings
from utils.logger import get_logger

logger = get_logger(__name__)

_GROUPS = (
    (
        "Monitoring",
        (
            ("monitoring_interval", "Monitoring interval (seconds)", "integer"),
            ("gateway_ping_count", "Gateway pings per cycle", "integer"),
            ("internet_ping_count", "Internet pings per cycle", "integer"),
            ("network_info_refresh_seconds", "Network info refresh (seconds)", "integer"),
        ),
    ),
    (
        "Targets and timeouts",
        (
            ("internet_host", "Internet test host", "text"),
            ("dns_test_domain", "DNS test domain", "text"),
            ("http_test_url", "HTTP test URL", "text"),
            ("ping_timeout_seconds", "Ping timeout (seconds)", "integer"),
            ("dns_timeout", "DNS timeout (seconds)", "integer"),
            ("http_timeout", "HTTP timeout (seconds)", "integer"),
        ),
    ),
    (
        "Analysis",
        (("analysis_window", "Analysis window (measurements)", "integer"),),
    ),
    (
        "Live status warning thresholds",
        (
            ("warning_thresholds.latency_ms", "Latency (ms)", "number"),
            ("warning_thresholds.packet_loss_percent", "Packet loss (%)", "number"),
            ("warning_thresholds.jitter_ms", "Jitter (ms)", "number"),
        ),
    ),
    (
        "Temporal analysis thresholds",
        (
            ("thresholds.high_latency_ms", "High latency (ms)", "number"),
            ("thresholds.critical_latency_ms", "Critical latency (ms)", "number"),
            ("thresholds.packet_loss_percent", "Packet loss (%)", "number"),
            ("thresholds.critical_packet_loss_percent", "Critical packet loss (%)", "number"),
            ("thresholds.high_jitter_ms", "High jitter (ms)", "number"),
            ("thresholds.high_dns_response_ms", "High DNS response (ms)", "number"),
            ("thresholds.high_http_response_ms", "High HTTP response (ms)", "number"),
        ),
    ),
)

_BG = PALETTE["background"]
_SURFACE = PALETTE["surface"]
_TEXT = PALETTE["text"]
_MUTED = PALETTE["muted"]


class SettingsView(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        on_saved: Callable[[Dict[str, Any]], None],
        monitoring_running: Callable[[], bool],
    ):
        super().__init__(master)
        self.title("Settings")
        self.geometry("900x780")
        self.minsize(680, 560)
        self.configure(background=_BG)
        self._on_saved = on_saved
        self._monitoring_running = monitoring_running
        self._variables: Dict[str, tk.StringVar] = {}
        self._types: Dict[str, str] = {}

        self._configure_styles()
        self._build_widgets()
        self._load_values()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        configure_styles(style)
        family = font_family(self)
        style.configure("Settings.TFrame", background=_BG)
        style.configure(
            "SettingsCard.TFrame",
            background=_SURFACE,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "SettingsTitle.TLabel",
            background=_BG,
            foreground=_TEXT,
            font=(family, 24, "bold"),
        )
        style.configure(
            "SettingsSection.TLabel",
            background=_SURFACE,
            foreground=_TEXT,
            font=(family, 15, "bold"),
        )
        style.configure(
            "SettingsMuted.TLabel",
            background=_BG,
            foreground=_MUTED,
            font=(family, 9),
        )
        style.configure(
            "SettingsCardMuted.TLabel",
            background=_SURFACE,
            foreground=_MUTED,
            font=(family, 9),
        )
        style.configure(
            "Settings.TEntry",
            padding=(8, 6),
            fieldbackground=_SURFACE,
            foreground=PALETTE["body"],
            bordercolor=PALETTE["border"],
        )

    def _build_widgets(self) -> None:
        shell = ttk.Frame(self, style="Settings.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        header = ttk.Frame(shell, padding=(22, 18, 22, 12), style="Settings.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Settings", style="SettingsTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "These are the application settings supported by the monitoring and diagnosis "
                "backend. Stop monitoring before saving changes."
            ),
            style="SettingsMuted.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(shell, style="Settings.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(body, background=_BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._content = ttk.Frame(self._canvas, padding=(22, 4, 22, 18), style="Settings.TFrame")
        self._content.columnconfigure(0, weight=1)
        self._window = self._canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind(
            "<Configure>", lambda _event: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas.bind(
            "<Configure>", lambda event: self._canvas.itemconfigure(self._window, width=event.width)
        )
        for row, (title, fields) in enumerate(_GROUPS):
            card = ttk.Frame(self._content, padding=(16, 14), style="SettingsCard.TFrame")
            card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
            card.columnconfigure(1, weight=1)
            ttk.Label(card, text=title, style="SettingsSection.TLabel").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 9)
            )
            for field_row, (key, label, value_type) in enumerate(fields, start=1):
                ttk.Label(card, text=label, style="SettingsCardMuted.TLabel").grid(
                    row=field_row, column=0, sticky="w", padx=(0, 18), pady=5
                )
                variable = tk.StringVar()
                entry = ttk.Entry(card, textvariable=variable, style="Settings.TEntry")
                entry.grid(row=field_row, column=1, sticky="ew", pady=4)
                self._variables[key] = variable
                self._types[key] = value_type

        footer = ttk.Frame(shell, padding=(22, 10, 22, 16), style="Settings.TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        self._status_label = ttk.Label(footer, text="", style="SettingsMuted.TLabel")
        self._status_label.pack(side="left", fill="x", expand=True)
        ttk.Button(
            footer, text="Cancel", style="Secondary.TButton", command=self.destroy
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer,
            text="Validate and save",
            style="Primary.TButton",
            command=self._save,
        ).pack(side="right")

    def _load_values(self) -> None:
        settings = load_settings()
        for dotted_key, variable in self._variables.items():
            value: Any = settings
            for segment in dotted_key.split("."):
                if not isinstance(value, dict) or segment not in value:
                    value = ""
                    break
                value = value[segment]
            variable.set(str(value))

    def _collect_values(self) -> Dict[str, Any]:
        settings = load_settings()
        for dotted_key, variable in self._variables.items():
            value = variable.get().strip()
            if self._types[dotted_key] == "integer":
                try:
                    settings_value: Any = int(value)
                except ValueError:
                    settings_value = value
            elif self._types[dotted_key] == "number":
                try:
                    settings_value = float(value)
                except ValueError:
                    settings_value = value
            else:
                settings_value = value
            path = dotted_key.split(".")
            target = settings
            for segment in path[:-1]:
                if not isinstance(target.get(segment), dict):
                    target[segment] = {}
                target = target[segment]
            target[path[-1]] = settings_value
        return settings

    def _save(self) -> None:
        try:
            settings = validate_settings(self._collect_values())
        except ValueError as exc:
            messagebox.showerror(
                "Invalid settings",
                f"Please correct these settings before saving:\n\n{exc}",
                parent=self,
            )
            return

        if self._monitoring_running():
            messagebox.showerror(
                "Monitoring is running",
                "Stop monitoring before saving settings. This prevents changing the active "
                "monitoring configuration mid-session.",
                parent=self,
            )
            return

        if not save_settings(settings):
            messagebox.showerror(
                "Could not save settings",
                "The settings could not be written to config/settings.json. "
                "Check the application log and file permissions.",
                parent=self,
            )
            return

        try:
            self._on_saved(settings)
        except Exception as exc:
            logger.exception("Settings were saved but could not be applied to the dashboard.")
            messagebox.showerror(
                "Settings saved but not applied",
                f"Settings were written, but the running dashboard could not apply them:\n{exc}",
                parent=self,
            )
            return
        self._status_label.configure(text="Settings validated and saved.")
        messagebox.showinfo(
            "Settings saved",
            "Settings were validated and saved. New monitoring sessions will use these values.",
            parent=self,
        )
        self.destroy()
