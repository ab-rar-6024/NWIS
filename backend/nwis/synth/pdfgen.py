"""Render synthetic DDR/WCR content to PDF (text PDFs, plus rasterised 'scanned' variants)."""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .docs_text import DayReport
from .wellgen import Well

_styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.8, leading=11)
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, spaceBefore=10, spaceAfter=4)


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _grid(data, widths, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def write_ddr_pdf(path: Path, well: Well, days: list[DayReport], rng: np.random.Generator) -> int:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"DDR {well.name}", author="Synthetic demo data")
    story = []
    for i, d in enumerate(days):
        story.append(Paragraph("DAILY DRILLING REPORT", H1))
        story.append(_grid([
            ["Well", well.name, "Field", well.field],
            ["Report No", str(d.report_no), "Date", d.date.isoformat()],
            ["Depth (24:00)", f"{d.depth_md:,.0f} m MD", "Formation", d.formation],
            ["Hole size", d.hole, "Mud weight", f"{d.mw:.2f} SG"],
            ["Rig", well.rig, "Days from spud", str(d.report_no)],
        ], [32 * mm, 52 * mm, 32 * mm, 52 * mm], header=False))
        story.append(Paragraph("OPERATIONS SUMMARY (00:00 - 24:00)", H2))
        n = max(1, len(d.sentences))
        cuts = np.sort(rng.choice(np.arange(1, 96), size=min(n - 1, 94), replace=False)) if n > 1 else np.array([])
        edges = [0] + [int(c) for c in cuts] + [96]
        rows = [["From", "To", "Activity"]]
        for k, s in enumerate(d.sentences):
            a, b = edges[k], edges[k + 1] if k + 1 < len(edges) else 96
            fmt = lambda q: f"{(q * 15) // 60:02d}:{(q * 15) % 60:02d}"
            rows.append([fmt(a), fmt(b if b > a else min(a + 1, 96)), Paragraph(_esc(s), CELL)])
        story.append(_grid(rows, [16 * mm, 16 * mm, 132 * mm]))
        if i < len(days) - 1:
            story.append(PageBreak())
    doc.build(story)
    return len(days)


def write_wcr_pdf(path: Path, well: Well, blocks: list[tuple]) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"WCR {well.name}", author="Synthetic demo data")
    story = []
    for b in blocks:
        kind = b[0]
        if kind == "title":
            story.append(Paragraph(_esc(b[1]), H1))
        elif kind == "h":
            story.append(Paragraph(_esc(b[1]), H2))
        elif kind == "kv":
            data = [[k, v] for k, v in b[1]]
            story.append(_grid(data, [55 * mm, 110 * mm], header=False))
        elif kind == "table":
            hdr, rows = b[1], b[2]
            w = 165 * mm / len(hdr)
            story.append(_grid([hdr] + rows, [w] * len(hdr)))
        elif kind == "p":
            story.append(Paragraph(_esc(b[1]), BODY))
            story.append(Spacer(1, 3))
    doc.build(story)


def rasterise_to_scan(src: Path, dst: Path, rng: np.random.Generator, dpi: int = 220) -> None:
    """Turn a text PDF into an image-only PDF with mild rotation/blur/noise (simulated scan)."""
    src_doc = pymupdf.open(src)
    out = pymupdf.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = img.rotate(float(rng.uniform(-0.4, 0.4)), resample=Image.BICUBIC, fillcolor=255)
        arr = np.asarray(img).astype(np.int16) + rng.normal(0, 6, (img.height, img.width)).astype(np.int16)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())
    out.save(dst)
    out.close()
    src_doc.close()
