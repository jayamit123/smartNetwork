"""Read-only recommendation review and decision recording UI.

This page can approve or reject a recommendation plan for review purposes.
It does not execute commands or make network changes.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from database.database import Database
from diagnosis.correlation_engine import correlate_symptoms
from diagnosis.recommendation_engine import generate_recommendations
from diagnosis.temporal_analysis import analyze_measurements
from utils.config_loader import load_settings
from utils.logger import get_logger
from gui.theme import PALETTE, configure_styles, font_family

logger = get_logger(__name__)

_PALETTE = {
    "background": PALETTE["background"],
    "surface": PALETTE["surface"],
    "text": PALETTE["text"],
    "muted": PALETTE["muted"],
    "blue": PALETTE["primary"],
    "green": PALETTE["success"],
    "red": PALETTE["danger"],
    "amber": PALETTE["warning"],
}


def _display(value: Any) -> str:
    return "—" if value is None or value == "" else str(value)


class RemediationReviewView(tk.Toplevel):
    """Review recommendations and persist explicit human decisions."""

    def __init__(self, master: tk.Misc, database: Database):
        super().__init__(master)
        self.title("Remediation plan review")
        self.geometry("1100x760")
        self.minsize(850, 560)
        self.configure(background=_PALETTE["background"])

        self._database = database
        self._settings = load_settings()
        self._sessions: List[Dict[str, Any]] = []
        self._session_by_choice: Dict[str, int] = {}
        self._recommendations: List[Dict[str, Any]] = []
        self._selected_session_id: Optional[int] = None
        self._saved_plan_id: Optional[str] = None

        self._configure_styles()
        self._build_widgets()
        self.refresh()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        configure_styles(style)
        family = font_family(self)
        style.configure("Review.TFrame", background=_PALETTE["background"])
        style.configure(
            "ReviewCard.TFrame",
            background=_PALETTE["surface"],
            relief="solid",
            borderwidth=1,
            bordercolor=PALETTE["border"],
        )
        style.configure(
            "ReviewTitle.TLabel",
            background=_PALETTE["background"],
            foreground=_PALETTE["text"],
            font=(family, 24, "bold"),
        )
        style.configure(
            "ReviewSection.TLabel",
            background=_PALETTE["surface"],
            foreground=_PALETTE["text"],
            font=(family, 15, "bold"),
        )
        style.configure(
            "ReviewMuted.TLabel",
            background=_PALETTE["surface"],
            foreground=_PALETTE["muted"],
            font=(family, 9),
        )
        style.configure(
            "ReviewStatus.TLabel",
            background=_PALETTE["surface"],
            foreground=_PALETTE["amber"],
            font=(family, 11, "bold"),
        )
        style.configure(
            "Review.Treeview",
            rowheight=34,
            background=_PALETTE["surface"],
            fieldbackground=_PALETTE["surface"],
            foreground=PALETTE["body"],
            font=(family, 9),
            bordercolor=PALETTE["border"],
        )
        style.configure(
            "Review.Treeview.Heading",
            background=PALETTE["table_header"],
            foreground=_PALETTE["text"],
            font=(family, 9, "bold"),
            padding=(8, 8),
        )
        style.map(
            "Review.Treeview",
            background=[("selected", PALETTE["selection"])],
            foreground=[("selected", _PALETTE["text"])],
        )
    def _build_widgets(self) -> None:
        scroll_shell = ttk.Frame(self, style="Review.TFrame")
        scroll_shell.pack(fill="both", expand=True)
        scroll_shell.columnconfigure(0, weight=1)
        scroll_shell.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            scroll_shell,
            background=_PALETTE["background"],
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        container = ttk.Frame(canvas, padding=20, style="Review.TFrame")
        window_id = canvas.create_window((0, 0), window=container, anchor="nw")
        container.bind(
            "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width)
        )
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)
        container.rowconfigure(5, weight=1)

        ttk.Label(
            container, text="Remediation plan review", style="ReviewTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            container,
            text=(
                "Review recommendations and record your decision. Approval never executes "
                "commands or changes network settings."
            ),
            style="ReviewMuted.TLabel",
            background=_PALETTE["background"],
            wraplength=950,
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        controls = ttk.Frame(container, style="Review.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(
            controls, text="Monitoring session", style="ReviewMuted.TLabel",
            background=_PALETTE["background"],
        ).pack(side="left", padx=(0, 8))
        self._session_var = tk.StringVar()
        self._session_combo = ttk.Combobox(
            controls, textvariable=self._session_var, state="readonly", width=58
        )
        self._session_combo.pack(side="left", fill="x", expand=True)
        self._session_combo.bind("<<ComboboxSelected>>", self._on_session_selected)
        ttk.Button(
            controls, text="Refresh", style="Secondary.TButton", command=self.refresh
        ).pack(side="left", padx=(8, 0))

        plan_card = ttk.Frame(container, padding=14, style="ReviewCard.TFrame")
        plan_card.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        plan_card.columnconfigure(0, weight=1)
        plan_card.rowconfigure(2, weight=1)
        plan_header = ttk.Frame(plan_card, style="ReviewCard.TFrame")
        plan_header.grid(row=0, column=0, sticky="ew")
        plan_header.columnconfigure(0, weight=1)
        ttk.Label(plan_header, text="Ranked recommendations", style="ReviewSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._plan_status_label = ttk.Label(
            plan_header, text="Awaiting review", style="ReviewStatus.TLabel"
        )
        self._plan_status_label.grid(row=0, column=1, sticky="e")
        ttk.Label(
            plan_card,
            text=(
                "Rank reflects the recommendation engine's returned order, not a separately "
                "computed priority score. Risk is not currently supplied by the backend."
            ),
            style="ReviewMuted.TLabel",
            wraplength=920,
        ).grid(row=1, column=0, sticky="w", pady=(5, 9))

        columns = ("rank", "recommendation", "reason", "risk", "severity")
        self._recommendation_tree = ttk.Treeview(
            plan_card, columns=columns, show="headings", selectmode="browse", style="Review.Treeview"
        )
        for column, heading, width in (
            ("rank", "Rank", 55),
            ("recommendation", "Recommendation", 330),
            ("reason", "Reason / evidence", 420),
            ("risk", "Risk", 190),
            ("severity", "Engine severity", 110),
        ):
            self._recommendation_tree.heading(column, text=heading)
            self._recommendation_tree.column(column, width=width, minwidth=70, anchor="w")
        self._recommendation_tree.grid(row=2, column=0, sticky="nsew")
        recommendation_y = ttk.Scrollbar(
            plan_card, orient="vertical", command=self._recommendation_tree.yview
        )
        recommendation_y.grid(row=2, column=1, sticky="ns")
        recommendation_x = ttk.Scrollbar(
            plan_card, orient="horizontal", command=self._recommendation_tree.xview
        )
        recommendation_x.grid(row=3, column=0, sticky="ew")
        self._recommendation_tree.configure(
            yscrollcommand=recommendation_y.set,
            xscrollcommand=recommendation_x.set,
        )
        self._recommendation_tree.bind("<<TreeviewSelect>>", self._on_recommendation_selected)

        details_card = ttk.Frame(container, padding=14, style="ReviewCard.TFrame")
        details_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        details_card.columnconfigure(0, weight=1)
        ttk.Label(details_card, text="Review details", style="ReviewSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._detail_text = tk.Text(
            details_card,
            height=5,
            wrap="word",
            background=_PALETTE["surface"],
            foreground=_PALETTE["text"],
            relief="flat",
            font=(font_family(self), 10),
            state="disabled",
        )
        self._detail_text.grid(row=1, column=0, sticky="ew", pady=(7, 0))

        verification_card = ttk.Frame(container, padding=14, style="ReviewCard.TFrame")
        verification_card.grid(row=5, column=0, sticky="nsew", pady=(0, 12))
        verification_card.columnconfigure(0, weight=1)
        verification_card.rowconfigure(1, weight=1)
        ttk.Label(
            verification_card, text="Recorded verification results", style="ReviewSection.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(0, 7))
        verification_columns = ("verified_at", "metric", "before", "after", "result")
        self._verification_tree = ttk.Treeview(
            verification_card, columns=verification_columns, show="headings", height=4
        )
        for column, heading, width in (
            ("verified_at", "Verified at", 180),
            ("metric", "Metric", 180),
            ("before", "Before", 160),
            ("after", "After", 160),
            ("result", "Result", 300),
        ):
            self._verification_tree.heading(column, text=heading)
            self._verification_tree.column(column, width=width, minwidth=70, anchor="w")
        self._verification_tree.grid(row=1, column=0, sticky="nsew")
        verification_scroll = ttk.Scrollbar(
            verification_card, orient="vertical", command=self._verification_tree.yview
        )
        verification_scroll.grid(row=1, column=1, sticky="ns")
        self._verification_tree.configure(yscrollcommand=verification_scroll.set)

        actions = ttk.Frame(container, style="Review.TFrame")
        actions.grid(row=6, column=0, sticky="ew")
        self._capability_label = ttk.Label(
            actions,
            text="Review only — no remediation execution capability is connected.",
            style="ReviewMuted.TLabel",
            background=_PALETTE["background"],
        )
        self._capability_label.pack(side="left")
        self._reject_button = ttk.Button(
            actions, text="Reject plan", style="Danger.TButton", command=self._reject_plan
        )
        self._reject_button.pack(side="right", padx=(8, 0))
        self._approve_button = ttk.Button(
            actions, text="Approve plan", style="Primary.TButton", command=self._approve_plan
        )
        self._approve_button.pack(side="right")

    def refresh(self) -> None:
        self._sessions = self._database.get_sessions()
        self._session_by_choice = {}
        choices = []
        for session in self._sessions:
            session_id = int(session["session_id"])
            label = (
                f"Session #{session_id} · {session.get('interface_name') or 'Unknown interface'} "
                f"· {session.get('start_time') or 'Unknown start'} · "
                f"{session.get('final_status') or 'UNKNOWN'}"
            )
            self._session_by_choice[label] = session_id
            choices.append(label)
        self._session_combo.configure(values=choices)
        if not choices:
            self._session_combo.set("")
            self._selected_session_id = None
            self._render_empty_state("No monitoring sessions are available.")
            return

        current = self._session_var.get()
        if current in self._session_by_choice:
            self._selected_session_id = self._session_by_choice[current]
        else:
            self._session_combo.current(0)
            self._selected_session_id = self._session_by_choice[choices[0]]
        self._load_selected_session()

    def _on_session_selected(self, _event=None) -> None:
        self._selected_session_id = self._session_by_choice.get(self._session_var.get())
        self._load_selected_session()

    def _load_selected_session(self) -> None:
        session_id = self._selected_session_id
        if session_id is None:
            self._render_empty_state("Select a session to review recommendations.")
            return

        measurements = self._database.get_session_measurements(session_id)
        if not measurements:
            self._render_empty_state(
                f"Session #{session_id} has no stored measurements. "
                "A recommendation plan cannot be generated without data."
            )
            self._load_verifications(session_id)
            return

        window_size = max(1, int(self._settings.get("analysis_window", 6)))
        rows_newest_first = list(reversed(measurements[-window_size:]))
        try:
            detection = analyze_measurements(rows_newest_first, self._settings)
            correlation = correlate_symptoms(detection, measurements[-1])
            generated = generate_recommendations(correlation)
        except Exception:
            logger.exception("Unable to generate remediation review for session #%s.", session_id)
            self._render_empty_state(
                "Recommendation generation failed. Check application logs; no plan was saved."
            )
            self._load_verifications(session_id)
            return

        reasons = [
            f"Probable category: {correlation.probable_category}",
            f"Diagnosis status: {correlation.status}",
            f"Temporal severity: {detection.severity}",
            *(correlation.evidence or []),
        ]
        if generated.explanation:
            reasons.insert(0, generated.explanation)
        reason = "\n".join(reasons) or "No explanatory evidence was provided by the backend."
        unavailable_risk = "Not provided by recommendation backend; manual review required"
        current = []
        for rank, suggestion in enumerate(generated.suggested_fixes, start=1):
            current.append(
                {
                    "rank": rank,
                    "action_name": str(suggestion),
                    "reason": reason,
                    "risk": unavailable_risk,
                    "severity": generated.severity,
                    "verification_steps": list(generated.verification_steps or []),
                }
            )

        saved_plan = self._latest_saved_plan(session_id)
        if saved_plan:
            self._recommendations = saved_plan["recommendations"]
            self._saved_plan_id = saved_plan["plan_id"]
            self._set_plan_status(
                saved_plan["status"],
                f"Plan {saved_plan['plan_id']} · reviewed {saved_plan['reviewed_at']}",
            )
        else:
            self._recommendations = current
            self._saved_plan_id = None
            self._set_plan_status(
                "AWAITING REVIEW",
                f"Session #{session_id} · not yet persisted",
            )

        self._render_recommendations()
        self._load_verifications(session_id)
        if not self._recommendations:
            self._detail_set(
                "The recommendation backend returned no suggested actions. "
                "There is no plan to approve or reject."
            )
            self._set_decision_controls(False)
        else:
            self._set_decision_controls(True)
            self._select_recommendation(0)

    def _latest_saved_plan(self, session_id: int) -> Optional[Dict[str, Any]]:
        rows = self._database.get_session_remediation_actions(session_id)
        if not rows:
            return None
        latest_plan_id = None
        for row in rows:
            try:
                data = json.loads(row.get("result") or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if data.get("plan_id") and data.get("plan_status") in {"APPROVED", "REJECTED"}:
                latest_plan_id = data["plan_id"]
                break
        if latest_plan_id is None:
            return None

        plan_entries = []
        for row in rows:
            try:
                data = json.loads(row.get("result") or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if data.get("plan_id") == latest_plan_id:
                plan_entries.append((row, data))
        plan_entries.sort(key=lambda item: item[1].get("rank", 0))
        first_data = plan_entries[0][1]
        return {
            "plan_id": latest_plan_id,
            "status": first_data.get("plan_status", "UNKNOWN"),
            "reviewed_at": first_data.get("reviewed_at", "—"),
            "recommendations": [
                {
                    "rank": data.get("rank", index),
                    "action_name": row.get("action_name") or "—",
                    "reason": data.get("reason") or "—",
                    "risk": data.get("risk") or "Not provided by recommendation backend",
                    "severity": data.get("severity") or "—",
                    "verification_steps": data.get("verification_steps") or [],
                }
                for index, (row, data) in enumerate(plan_entries, start=1)
            ],
        }

    def _render_recommendations(self) -> None:
        for row_id in self._recommendation_tree.get_children():
            self._recommendation_tree.delete(row_id)
        for item in self._recommendations:
            self._recommendation_tree.insert(
                "",
                "end",
                iid=str(item["rank"]),
                values=(
                    item["rank"],
                    item["action_name"],
                    item["reason"],
                    item["risk"],
                    item.get("severity") or "—",
                ),
            )

    def _on_recommendation_selected(self, _event=None) -> None:
        selection = self._recommendation_tree.selection()
        if selection:
            try:
                self._show_recommendation(int(selection[0]))
            except ValueError:
                self._detail_set("Recommendation details are unavailable.")

    def _select_recommendation(self, index: int) -> None:
        if index < 0 or index >= len(self._recommendations):
            return
        row_id = str(self._recommendations[index]["rank"])
        self._recommendation_tree.selection_set(row_id)
        self._recommendation_tree.focus(row_id)
        self._show_recommendation(self._recommendations[index]["rank"])

    def _show_recommendation(self, rank: int) -> None:
        item = next((entry for entry in self._recommendations if entry["rank"] == rank), None)
        if item is None:
            return
        verification = item.get("verification_steps") or []
        lines = [
            f"Recommendation {rank}: {item['action_name']}",
            "",
            "Reason / evidence:",
            item.get("reason") or "No reason was supplied by the backend.",
            "",
            "Risk:",
            item.get("risk") or "Not provided by recommendation backend; manual review required.",
            "",
            "Verification guidance:",
            *([f"• {step}" for step in verification] or ["No verification steps supplied."]),
            "",
            "Approval records a review decision only. This application will not execute this recommendation.",
        ]
        self._detail_set("\n".join(lines))

    def _detail_set(self, text: str) -> None:
        self._detail_text.configure(state="normal")
        self._detail_text.delete("1.0", "end")
        self._detail_text.insert("1.0", text)
        self._detail_text.configure(state="disabled")

    def _set_plan_status(self, status: str, extra: str = "") -> None:
        color = {
            "APPROVED": _PALETTE["green"],
            "REJECTED": _PALETTE["red"],
        }.get(status, _PALETTE["amber"])
        text = status.replace("_", " ")
        self._plan_status_label.configure(
            text=f"{text} · {extra}" if extra else text,
            foreground=color,
        )

    def _set_decision_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._approve_button.configure(state=state)
        self._reject_button.configure(state=state)

    def _approve_plan(self) -> None:
        self._record_decision("APPROVED")

    def _reject_plan(self) -> None:
        self._record_decision("REJECTED")

    def _record_decision(self, decision: str) -> None:
        if self._selected_session_id is None or not self._recommendations:
            return
        prompt = (
            f"Record this recommendation plan as {decision.lower()}?\n\n"
            "This records your decision only; no network changes will be executed."
        )
        if not messagebox.askyesno("Confirm plan decision", prompt, parent=self):
            return
        try:
            plan_id = self._database.record_remediation_review(
                self._selected_session_id,
                [
                    {
                        "action_name": item["action_name"],
                        "reason": item.get("reason"),
                        "risk": item.get("risk"),
                        "severity": item.get("severity"),
                        "verification_steps": item.get("verification_steps", []),
                    }
                    for item in self._recommendations
                ],
                decision,
            )
        except (ValueError, TypeError) as exc:
            logger.error("Invalid remediation review decision: %s", exc)
            messagebox.showerror(
                "Could not save review",
                f"The review decision was invalid:\n{exc}",
                parent=self,
            )
            return
        if plan_id is None:
            messagebox.showerror(
                "Could not save review",
                "The review decision could not be saved. Check the application log.",
                parent=self,
            )
            return
        self._load_selected_session()
        self._set_plan_status(
            decision,
            f"Plan {plan_id} · saved; no action executed",
        )

    def _load_verifications(self, session_id: int) -> None:
        for row_id in self._verification_tree.get_children():
            self._verification_tree.delete(row_id)
        results = self._database.get_session_verification_results(session_id)
        for result in results:
            self._verification_tree.insert(
                "",
                "end",
                values=(
                    _display(result.get("verified_at")),
                    _display(result.get("metric")),
                    _display(result.get("before_value")),
                    _display(result.get("after_value")),
                    _display(result.get("result")),
                ),
            )
        if not results:
            self._verification_tree.insert(
                "",
                "end",
                values=("—", "No verification results recorded", "—", "—", "—"),
            )

    def _render_empty_state(self, message: str) -> None:
        self._recommendations = []
        self._saved_plan_id = None
        for row_id in self._recommendation_tree.get_children():
            self._recommendation_tree.delete(row_id)
        self._set_plan_status("NOT AVAILABLE", message)
        self._detail_set(message)
        self._set_decision_controls(False)
