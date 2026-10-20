"""Shared visual theme and small Tkinter components."""

from __future__ import annotations

from tkinter import ttk
from tkinter import font as tkfont
from typing import Optional, Tuple

PALETTE = {
    "background": "#0B1726",
    "surface": "#192C3E",
    "text": "#F8FAFC",
    "body": "#D6E2EF",
    "muted": "#9EB2C8",
    "border": "#31465A",
    "primary": "#3563E9",
    "primary_dark": "#2D55D8",
    "secondary": "#24384A",
    "secondary_hover": "#30485E",
    "sidebar": "#0B1726",
    "sidebar_muted": "#C6D5E4",
    "sidebar_hover": "#192C3E",
    "sidebar_active": "#203A56",
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
    "danger_dark": "#B91C1C",
    "info": "#3563E9",
    "table_header": "#20364A",
    "selection": "#294C70",
    "disabled": "#50657A",
    "disabled_text": "#CBD5E1",
}


def font_family(master=None) -> str:
    """Prefer Segoe UI while retaining the platform's default font as fallback."""
    try:
        available = set(tkfont.families(master))
        if "Segoe UI" in available:
            return "Segoe UI"
        if "Arial" in available:
            return "Arial"
        return str(tkfont.nametofont("TkDefaultFont", root=master).actual("family"))
    except Exception:
        return "Arial"


def configure_styles(style: ttk.Style) -> None:
    """Configure the shared ttk styles used by the application pages."""
    if "clam" in style.theme_names():
        style.theme_use("clam")
    family = font_family(style.master)

    style.configure(".", font=(family, 10), foreground=PALETTE["body"])
    style.configure("TEntry", padding=(8, 6), fieldbackground=PALETTE["surface"])
    style.configure(
        "TCombobox",
        padding=(8, 6),
        fieldbackground=PALETTE["surface"],
        background=PALETTE["surface"],
        foreground=PALETTE["body"],
        arrowcolor=PALETTE["muted"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PALETTE["surface"])],
        foreground=[("readonly", PALETTE["body"])],
    )
    style.configure(
        "TButton",
        font=(family, 9, "bold"),
        padding=(13, 8),
        background=PALETTE["secondary"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["secondary"],
        darkcolor=PALETTE["secondary"],
        relief="flat",
        focusthickness=1,
        focuscolor=PALETTE["primary"],
    )
    style.map(
        "TButton",
        background=[
            ("disabled", PALETTE["secondary"]),
            ("pressed", PALETTE["secondary_hover"]),
            ("active", PALETTE["secondary_hover"]),
        ],
        foreground=[("disabled", PALETTE["muted"]), ("active", PALETTE["text"])],
        bordercolor=[("focus", PALETTE["primary"])],
    )
    style.configure(
        "Primary.TButton",
        font=(family, 9, "bold"),
        padding=(14, 9),
        background=PALETTE["primary"],
        foreground=PALETTE["surface"],
        bordercolor=PALETTE["primary"],
        lightcolor=PALETTE["primary"],
        darkcolor=PALETTE["primary"],
        relief="flat",
    )
    style.map(
        "Primary.TButton",
        background=[
            ("disabled", PALETTE["disabled"]),
            ("pressed", PALETTE["primary_dark"]),
            ("active", PALETTE["primary_dark"]),
        ],
        foreground=[("disabled", PALETTE["disabled_text"]), ("active", PALETTE["surface"])],
    )
    style.configure(
        "Secondary.TButton",
        font=(family, 9, "bold"),
        padding=(12, 8),
        background=PALETTE["secondary"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["secondary"],
        darkcolor=PALETTE["secondary"],
        relief="flat",
    )
    style.map(
        "Secondary.TButton",
        background=[
            ("disabled", PALETTE["secondary"]),
            ("pressed", PALETTE["secondary_hover"]),
            ("active", PALETTE["secondary_hover"]),
        ],
        foreground=[("disabled", PALETTE["muted"])],
    )
    style.configure(
        "Danger.TButton",
        font=(family, 9, "bold"),
        padding=(14, 9),
        background=PALETTE["danger"],
        foreground=PALETTE["surface"],
        bordercolor=PALETTE["danger"],
        lightcolor=PALETTE["danger"],
        darkcolor=PALETTE["danger"],
        relief="flat",
    )
    style.map(
        "Danger.TButton",
        background=[
            ("disabled", PALETTE["disabled"]),
            ("pressed", PALETTE["danger_dark"]),
            ("active", PALETTE["danger_dark"]),
        ],
        foreground=[("disabled", PALETTE["disabled_text"])],
    )

    style.configure("Dashboard.TFrame", background=PALETTE["background"])
    style.configure("Card.TFrame", background=PALETTE["surface"], relief="flat")
    style.configure(
        "CardOuter.TFrame",
        background=PALETTE["surface"],
        relief="solid",
        borderwidth=1,
        bordercolor=PALETTE["border"],
    )
    style.configure(
        "Dashboard.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(family, 10),
    )
    style.configure(
        "Card.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["body"],
        font=(family, 10),
    )
    style.configure(
        "Muted.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["muted"],
        font=(family, 9),
    )
    style.configure(
        "CardMuted.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["muted"],
        font=(family, 9),
    )
    style.configure(
        "PageTitle.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(family, 24, "bold"),
    )
    style.configure(
        "SectionTitle.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=(family, 15, "bold"),
    )
    style.configure(
        "MetricValue.TLabel",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        font=(family, 18, "bold"),
    )
    style.configure(
        "Treeview",
        rowheight=32,
        background=PALETTE["surface"],
        fieldbackground=PALETTE["surface"],
        foreground=PALETTE["body"],
        font=(family, 9),
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
    )
    style.configure(
        "Treeview.Heading",
        background=PALETTE["table_header"],
        foreground=PALETTE["text"],
        font=(family, 9, "bold"),
        padding=(8, 8),
    )
    style.map(
        "Treeview",
        background=[("selected", PALETTE["selection"])],
        foreground=[("selected", PALETTE["text"])],
    )
    style.configure(
        "Sidebar.TFrame",
        background=PALETTE["sidebar"],
    )
    style.configure(
        "SidebarBrand.TLabel",
        background=PALETTE["sidebar"],
        foreground=PALETTE["surface"],
        font=(family, 12, "bold"),
    )
    style.configure(
        "SidebarCaption.TLabel",
        background=PALETTE["sidebar"],
        foreground=PALETTE["sidebar_muted"],
        font=(family, 8),
    )
    style.configure(
        "SidebarSection.TLabel",
        background=PALETTE["sidebar"],
        foreground=PALETTE["muted"],
        font=(family, 8, "bold"),
    )
    style.configure(
        "SidebarNav.TButton",
        background=PALETTE["sidebar"],
        foreground=PALETTE["sidebar_muted"],
        anchor="w",
        font=(family, 10),
        padding=(13, 11),
        borderwidth=0,
        focusthickness=0,
        relief="flat",
    )
    style.map(
        "SidebarNav.TButton",
        background=[("active", PALETTE["sidebar_hover"])],
        foreground=[("active", PALETTE["surface"])],
    )
    style.configure(
        "SidebarActive.TButton",
        background=PALETTE["sidebar_active"],
        foreground=PALETTE["surface"],
        anchor="w",
        font=(family, 10, "bold"),
        padding=(13, 11),
        borderwidth=1,
        focusthickness=0,
        relief="flat",
        bordercolor=PALETTE["primary"],
        lightcolor=PALETTE["sidebar_active"],
        darkcolor=PALETTE["sidebar_active"],
    )
    style.map(
        "SidebarActive.TButton",
        background=[("active", PALETTE["sidebar_active"])],
        foreground=[("active", PALETTE["surface"])],
        bordercolor=[("focus", PALETTE["primary"])],
    )
    style.configure(
        "AppHeader.TFrame",
        background=PALETTE["background"],
    )
    style.configure(
        "AppHeaderTitle.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["text"],
        font=(family, 10, "bold"),
    )
    style.configure(
        "AppHeaderMuted.TLabel",
        background=PALETTE["background"],
        foreground=PALETTE["muted"],
        font=(family, 9),
    )
    style.configure("Notebook", background=PALETTE["background"], bordercolor=PALETTE["border"])
    style.configure(
        "Notebook.Tab",
        background=PALETTE["secondary"],
        foreground=PALETTE["muted"],
        padding=(12, 7),
        font=(family, 9, "bold"),
    )
    style.map(
        "Notebook.Tab",
        background=[("selected", PALETTE["surface"]), ("active", PALETTE["secondary_hover"])],
        foreground=[("selected", PALETTE["primary"]), ("active", PALETTE["text"])],
    )


def create_card(
    parent: ttk.Frame,
    title: str,
    subtitle: Optional[str] = None,
    padding: Tuple[int, int] = (18, 16),
    wraplength: int = 780,
) -> tuple[ttk.Frame, ttk.Frame]:
    """Build a consistently styled dashboard card and return its body."""
    card = ttk.Frame(parent, style="CardOuter.TFrame", padding=padding)
    header = ttk.Frame(card, style="Card.TFrame")
    header.pack(fill="x")
    ttk.Label(header, text=title, style="SectionTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(
            header,
            text=subtitle,
            style="CardMuted.TLabel",
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))
    body = ttk.Frame(card, style="Card.TFrame")
    body.pack(fill="both", expand=True)
    return card, body
