"""
app.py

Entry point for the Smart Network Diagnosis System.

Phase 1 scope: launch the desktop GUI and show the machine's current,
auto-detected network configuration (interface, IPv4, gateway, DNS,
status). Nothing is hardcoded -- gui/dashboard.py calls into
monitoring/interface_monitor.py -> utils/network_utils.py to detect the
real configuration at run time.

Run with:
    python app.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox, ttk

from gui.dashboard import Dashboard
from gui.theme import PALETTE, configure_styles
from utils.logger import get_logger

logger = get_logger(__name__)

APP_TITLE = "Smart Network Diagnosis System"
MIN_WIDTH = 720
MIN_HEIGHT = 780


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        # Happens when there is no display available (e.g. running the
        # app on a headless machine/CI runner by mistake).
        logger.error("Could not start the GUI (no display available?): %s", exc)
        print(
            "ERROR: Could not start the graphical interface.\n"
            "This application must be run on a desktop session with a display.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    style = ttk.Style(root)
    configure_styles(style)
    root.configure(bg=PALETTE["background"])

    root.title(APP_TITLE)
    root.minsize(MIN_WIDTH, MIN_HEIGHT)
    root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")

    try:
        dashboard = Dashboard(root)
        dashboard.pack(fill="both", expand=True)
    except Exception as exc:  # noqa: BLE001 - last line of defense
        logger.exception("Fatal error while building the dashboard: %s", exc)
        messagebox.showerror(
            APP_TITLE,
            f"A fatal error occurred while starting the application:\n\n{exc}",
        )
        return 1

    def _on_close():
        logger.info("Application closing.")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    logger.info("Application started.")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
