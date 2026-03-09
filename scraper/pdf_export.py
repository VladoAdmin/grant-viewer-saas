"""PDF Export — generates summary PDF for a grant call.

Creates a structured PDF with:
- Header with call title and source
- Key attributes (provider, allocation, deadline, eligible applicants)
- Call description and objectives
- Contact info (if available)

Uses reportlab for PDF generation.
"""

import io
import logging
from datetime import datetime
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


def _try_import_reportlab():
    """Try importing reportlab, return None if not available."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm, mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, PageBreak
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
        return True
    except ImportError:
        return False


def generate_call_pdf(call: Dict, attributes: Dict[str, str],
                      attachments: Optional[List[Dict]] = None) -> Optional[bytes]:
    """Generate a PDF summary for a grant call.

    Args:
        call: Grant call record from DB
        attributes: Key-value attributes
        attachments: List of attachment records

    Returns:
        PDF bytes or None if reportlab is not available
    """
    if not _try_import_reportlab():
        log.warning("reportlab not installed. Install with: pip install reportlab")
        return _generate_simple_pdf(call, attributes, attachments)

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CallTitle", parent=styles["Heading1"],
        fontSize=16, leading=20, spaceAfter=6,
        textColor=HexColor("#1a365d"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=12,
        textColor=HexColor("#4a5568"),
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"],
        fontSize=13, leading=16, spaceBefore=12, spaceAfter=6,
        textColor=HexColor("#2d3748"),
    )
    body_style = ParagraphStyle(
        "BodyText", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=6,
        alignment=TA_JUSTIFY,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"],
        fontSize=9, leading=12,
        textColor=HexColor("#718096"),
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"],
        fontSize=10, leading=14,
        textColor=HexColor("#1a202c"),
    )

    elements = []

    # Header
    title = call.get("title", "Bez názvu")
    elements.append(Paragraph(title, title_style))

    source = call.get("source", "")
    status = call.get("status", "")
    elements.append(Paragraph(
        f"Zdroj: {source} | Stav: {status}", subtitle_style
    ))

    elements.append(HRFlowable(width="100%", thickness=1,
                                color=HexColor("#e2e8f0"), spaceAfter=12))

    # Key information table
    elements.append(Paragraph("Základné informácie", section_style))

    table_data = []
    key_fields = [
        ("Vyhlasovateľ", call.get("provider") or attributes.get("Vyhlasovateľ výzvy", "")),
        ("Kód výzvy", attributes.get("Kód výzvy", "")),
        ("Program", attributes.get("Program", "")),
        ("Druh výzvy", attributes.get("Druh výzvy", call.get("call_type", ""))),
        ("Dátum vyhlásenia", _format_date(call.get("announced_at"))),
        ("Deadline", _format_date(call.get("deadline_at"))),
        ("Alokácia EÚ", attributes.get("Alokácia EÚ", call.get("total_allocation", ""))),
        ("Alokácia spolu", attributes.get("Alokácia spolu", "")),
        ("Miesto realizácie", attributes.get("Miesto realizácie", "")),
    ]

    for label, value in key_fields:
        if value:
            table_data.append([
                Paragraph(f"<b>{label}:</b>", label_style),
                Paragraph(str(value), value_style),
            ])

    if table_data:
        t = Table(table_data, colWidths=[5 * cm, 12 * cm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#edf2f7")),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 12))

    # Eligible applicants
    elig = attributes.get("opravneni_ziadatelia") or call.get("eligible_applicants")
    if elig:
        elements.append(Paragraph("Oprávnení žiadatelia", section_style))
        elements.append(Paragraph(elig[:3000], body_style))
        elements.append(Spacer(1, 8))

    # Specific objectives
    ciele = attributes.get("Špecifický cieľ", "")
    if ciele:
        elements.append(Paragraph("Špecifický cieľ", section_style))
        elements.append(Paragraph(ciele[:3000], body_style))
        elements.append(Spacer(1, 8))

    # Other attributes
    shown_keys = {
        "Vyhlasovateľ výzvy", "Kód výzvy", "Program", "Druh výzvy", "Typ výzvy",
        "Miesto realizácie", "Alokácia EÚ", "Alokácia ŠR", "Alokácia spolu",
        "Špecifický cieľ", "opravneni_ziadatelia", "vyhlasovatel_vyzvy", "alokacia_eu",
    }
    other_attrs = {k: v for k, v in attributes.items() if k not in shown_keys and v}
    if other_attrs:
        elements.append(Paragraph("Ďalšie informácie", section_style))
        for key, value in other_attrs.items():
            elements.append(Paragraph(f"<b>{key}:</b> {value[:500]}", body_style))

    # Attachments
    if attachments:
        elements.append(Paragraph("Prílohy", section_style))
        for att in attachments:
            name = att.get("name", "")
            url = att.get("url", "")
            elements.append(Paragraph(f"• {name}", body_style))

    # Footer
    elements.append(Spacer(1, 24))
    elements.append(HRFlowable(width="100%", thickness=0.5,
                                color=HexColor("#e2e8f0"), spaceAfter=6))
    elements.append(Paragraph(
        f"Vygenerované: {datetime.now().strftime('%d.%m.%Y %H:%M')} | "
        f"Grant Viewer SaaS | grant-viewer.stormlevel.sk",
        ParagraphStyle("Footer", parent=styles["Normal"],
                        fontSize=8, textColor=HexColor("#a0aec0"),
                        alignment=TA_CENTER),
    ))

    doc.build(elements)
    return buffer.getvalue()


def _generate_simple_pdf(call: Dict, attributes: Dict[str, str],
                         attachments: Optional[List[Dict]] = None) -> Optional[bytes]:
    """Fallback: generate a simple text-based PDF without reportlab.

    Uses FPDF2 as lightweight alternative, or returns None.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        log.error("Neither reportlab nor fpdf2 is installed. Cannot generate PDF.")
        return None

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Use built-in font (no Unicode support, but functional)
    pdf.set_font("Helvetica", "B", 16)
    title = call.get("title", "Bez nazvu")
    # Replace Slovak chars for built-in font
    pdf.cell(0, 10, _strip_diacritics(title[:80]), ln=True)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Zdroj: {call.get('source', '')} | Stav: {call.get('status', '')}", ln=True)
    pdf.ln(5)

    # Key fields
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Zakladne informacie", ln=True)
    pdf.set_font("Helvetica", "", 10)

    fields = [
        ("Vyhlasovatel", call.get("provider", "")),
        ("Deadline", _format_date(call.get("deadline_at"))),
        ("Alokacia", call.get("total_allocation", "")),
    ]
    for label, value in fields:
        if value:
            pdf.cell(0, 6, f"{label}: {_strip_diacritics(str(value)[:100])}", ln=True)

    # Attributes
    for key, value in list(attributes.items())[:20]:
        pdf.cell(0, 6, f"{_strip_diacritics(key)}: {_strip_diacritics(str(value)[:100])}", ln=True)

    return pdf.output()


def _format_date(date_str: Optional[str]) -> str:
    """Format date string to Slovak format."""
    if not date_str:
        return ""
    try:
        if "T" in str(date_str):
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(date_str)[:10]


def _strip_diacritics(text: str) -> str:
    """Strip Slovak diacritics for basic PDF fonts."""
    mapping = {
        "á": "a", "ä": "a", "č": "c", "ď": "d", "é": "e", "í": "i",
        "ĺ": "l", "ľ": "l", "ň": "n", "ó": "o", "ô": "o", "ŕ": "r",
        "š": "s", "ť": "t", "ú": "u", "ý": "y", "ž": "z",
        "Á": "A", "Ä": "A", "Č": "C", "Ď": "D", "É": "E", "Í": "I",
        "Ĺ": "L", "Ľ": "L", "Ň": "N", "Ó": "O", "Ô": "O", "Ŕ": "R",
        "Š": "S", "Ť": "T", "Ú": "U", "Ý": "Y", "Ž": "Z",
    }
    return "".join(mapping.get(c, c) for c in text)
