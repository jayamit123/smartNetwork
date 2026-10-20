"""PDF generation for diagnosis, measurements, remediation and verification."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


_NAVY = colors.HexColor("#17365D")
_BLUE = colors.HexColor("#1679B8")
_LIGHT_BLUE = colors.HexColor("#EAF3F8")
_LIGHT_GREY = colors.HexColor("#F2F4F7")
_TEXT = colors.HexColor("#263238")


def _text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return escape(str(value)).replace("\n", "<br/>")


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_text(value), style)


def _section(title: str, styles: Dict[str, ParagraphStyle], content: List[Any]) -> None:
    content.append(Spacer(1, 10))
    content.append(Paragraph(escape(title), styles["ReportSection"]))


def _key_value_table(rows: List[List[Any]], width: float) -> Table:
    table = Table(rows, colWidths=[1.65 * inch, width - 1.65 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), _LIGHT_GREY),
                ("TEXTCOLOR", (0, 0), (-1, -1), _TEXT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D6DCE4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def build_diagnostic_pdf(report: Dict[str, Any]) -> bytes:
    """Build a readable, paginated PDF diagnostic report."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.5 * inch,
        title="Network Diagnostic Report",
        author="Smart Network Diagnosis",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=_NAVY,
            alignment=TA_CENTER,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSubtitle",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#566575"),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=_NAVY,
            spaceBefore=4,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=_TEXT,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportCellHeader",
            parent=styles["ReportCell"],
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSmall",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
            textColor=_TEXT,
        )
    )
    content: List[Any] = [
        Paragraph("Network Diagnostic Report", styles["ReportTitle"]),
        Paragraph(
            f"Generated: {_text(report.get('generated_at'))} &nbsp; | &nbsp; "
            "Source: local endpoint measurements",
            styles["ReportSubtitle"],
        ),
    ]
    page_width = landscape(letter)[0] - document.leftMargin - document.rightMargin

    diagnosis = report.get("diagnosis") or {}
    detection = diagnosis.get("detection") or {}
    correlation = diagnosis.get("correlation") or {}
    recommendations = diagnosis.get("recommendations") or {}
    _section("Diagnosis summary", styles, content)
    content.append(
        _key_value_table(
            [
                ["Assessment", _paragraph(recommendations.get("root_cause"), styles["ReportSmall"])],
                ["Explanation", _paragraph(recommendations.get("explanation"), styles["ReportSmall"])],
                ["Probable category", _paragraph(correlation.get("probable_category"), styles["ReportSmall"])],
                ["Severity", _paragraph(detection.get("severity"), styles["ReportSmall"])],
                ["Checks analyzed", _paragraph(detection.get("measurements_analyzed"), styles["ReportSmall"])],
                ["Analysis pattern", _paragraph(
                    "Persistent" if detection.get("persistent") else
                    "Intermittent" if detection.get("intermittent") else "No persistent pattern",
                    styles["ReportSmall"],
                )],
                ["Supporting evidence", _paragraph("; ".join(correlation.get("evidence") or []), styles["ReportSmall"])],
                ["Recommended next steps", _paragraph("; ".join(recommendations.get("suggested_fixes") or []), styles["ReportSmall"])],
            ],
            page_width,
        )
    )

    session = report.get("session")
    if session:
        _section("Monitoring session", styles, content)
        content.append(
            _key_value_table(
                [
                    ["Session", _paragraph(session.get("session_id"), styles["ReportSmall"])],
                    ["Started", _paragraph(session.get("start_time"), styles["ReportSmall"])],
                    ["Ended", _paragraph(session.get("end_time"), styles["ReportSmall"])],
                    ["Interface / address", _paragraph(
                        f"{session.get('interface_name') or '—'} / {session.get('ipv4_address') or '—'}",
                        styles["ReportSmall"],
                    )],
                    ["Measurements saved", _paragraph(session.get("measurement_count"), styles["ReportSmall"])],
                    ["Final status", _paragraph(session.get("final_status"), styles["ReportSmall"])],
                ],
                page_width,
            )
        )

    measurements = report.get("measurements") or []
    _section(f"Measurements ({len(measurements)})", styles, content)
    if measurements:
        columns = [
            ("timestamp", "Time"),
            ("overall_status", "Status"),
            ("gateway_latency_ms", "Gateway ms"),
            ("gateway_packet_loss", "Gateway loss %"),
            ("internet_latency_ms", "Internet ms"),
            ("internet_packet_loss", "Internet loss %"),
            ("jitter_ms", "Jitter ms"),
            ("dns_success", "DNS"),
            ("http_status_code", "HTTP"),
        ]
        table_data = [
            [_paragraph(label, styles["ReportCellHeader"]) for _, label in columns]
        ]
        for measurement in measurements:
            row = []
            for key, _ in columns:
                value = measurement.get(key)
                if key == "dns_success":
                    value = "PASS" if value == 1 else "FAIL" if value == 0 else "—"
                elif key == "timestamp" and value:
                    value = str(value).replace("T", " ")
                row.append(_paragraph(value, styles["ReportCell"]))
            table_data.append(row)
        column_widths = [1.45 * inch, 0.82 * inch, 0.82 * inch, 0.88 * inch, 0.82 * inch, 0.88 * inch, 0.72 * inch, 0.5 * inch, 0.48 * inch]
        table = Table(table_data, colWidths=column_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_BLUE]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5DCE5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        content.append(table)
    else:
        content.append(Paragraph("No measurements are available.", styles["ReportSmall"]))

    actions = report.get("remediation_actions") or []
    _section(f"Remediation history ({len(actions)})", styles, content)
    if actions:
        action_rows = [[
            _paragraph(label, styles["ReportCellHeader"])
            for label in ("Action", "Executed", "Result")
        ]]
        for action in actions:
            action_rows.append([
                _paragraph(action.get("action_name"), styles["ReportCell"]),
                _paragraph(action.get("executed_at"), styles["ReportCell"]),
                _paragraph(action.get("result"), styles["ReportCell"]),
            ])
        action_table = Table(action_rows, colWidths=[2.2 * inch, 1.8 * inch, page_width - 4 * inch], repeatRows=1)
        action_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GREY]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5DCE5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        content.append(action_table)
    else:
        content.append(Paragraph("No remediation actions were recorded.", styles["ReportSmall"]))

    verifications = report.get("verification_results") or []
    _section(f"Post-remediation verification ({len(verifications)})", styles, content)
    if verifications:
        verification_rows = [[
            _paragraph(label, styles["ReportCellHeader"])
            for label in ("Metric", "Before", "After", "Outcome", "Verified")
        ]]
        for verification in verifications:
            verification_rows.append([
                _paragraph(verification.get("metric"), styles["ReportCell"]),
                _paragraph(verification.get("before_value"), styles["ReportCell"]),
                _paragraph(verification.get("after_value"), styles["ReportCell"]),
                _paragraph(verification.get("result"), styles["ReportCell"]),
                _paragraph(verification.get("verified_at"), styles["ReportCell"]),
            ])
        verification_table = Table(
            verification_rows,
            colWidths=[1.2 * inch, 1.25 * inch, 2.1 * inch, 1.5 * inch, page_width - 6.05 * inch],
            repeatRows=1,
        )
        verification_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_BLUE]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5DCE5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        content.append(verification_table)
    else:
        content.append(Paragraph("No post-remediation verification results were recorded.", styles["ReportSmall"]))

    def footer(canvas, _document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D5DCE5"))
        canvas.line(document.leftMargin, 0.37 * inch, landscape(letter)[0] - document.rightMargin, 0.37 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#647386"))
        canvas.drawString(document.leftMargin, 0.22 * inch, "Smart Network Diagnosis · Evidence-based local report")
        canvas.drawRightString(landscape(letter)[0] - document.rightMargin, 0.22 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    document.build(content, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
