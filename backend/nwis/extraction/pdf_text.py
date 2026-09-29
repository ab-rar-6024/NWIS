"""PDF -> line-oriented text, with automatic OCR fallback for pages that have no text layer."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from threading import Lock

import pymupdf

OCR_DPI = 220
MIN_TEXT_CHARS = 40  # below this a page is treated as a scan and sent to OCR

_ocr_engine = None
_ocr_lock = Lock()


@dataclass
class PageText:
    number: int
    lines: list[str]
    ocr: bool = False
    confidence: float | None = None  # mean OCR confidence, None for native text


@dataclass
class ExtractedDoc:
    path: str
    pages: list[PageText] = field(default_factory=list)
    ocr_available: bool = True

    @property
    def ocr_used(self) -> bool:
        return any(p.ocr for p in self.pages)

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.ocr]

    @property
    def mean_confidence(self) -> float | None:
        c = [p.confidence for p in self.pages if p.confidence is not None]
        return sum(c) / len(c) if c else None

    def text(self) -> str:
        return "\n".join(line for p in self.pages for line in p.lines)


_QUOTES = {"″": '"', "”": '"', "“": '"', "’": "'", "‘": "'", "ʺ": '"'}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for k, v in _QUOTES.items():
        s = s.replace(k, v)
    s = s.replace("''", '"')
    return re.sub(r"[ \t]+", " ", s).strip()


def _get_ocr():
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR  # heavy import, load lazily

            _ocr_engine = RapidOCR()
    return _ocr_engine


def _group_lines(items: list[tuple[float, float, float, float, str]], gap_factor: float) -> list[str]:
    """Cluster text fragments into visual lines; big horizontal gaps become ' | ' (table cell separators)."""
    if not items:
        return []
    heights = [max(1.0, y1 - y0) for _, y0, _, y1, _ in items]
    tol = 0.6 * median(heights)
    items = sorted(items, key=lambda t: ((t[1] + t[3]) / 2, t[0]))
    rows: list[list[tuple]] = []
    for it in items:
        cy = (it[1] + it[3]) / 2
        if rows and abs(cy - rows[-1][0]) <= tol:
            rows[-1][1].append(it)
            rows[-1][0] = (rows[-1][0] * (len(rows[-1][1]) - 1) + cy) / len(rows[-1][1])
        else:
            rows.append([cy, [it]])
    out = []
    for _, frags in rows:
        frags.sort(key=lambda t: t[0])
        parts = [frags[0][4]]
        for prev, cur in zip(frags, frags[1:]):
            gap = cur[0] - prev[2]
            h = max(1.0, prev[3] - prev[1])
            parts.append(" | " if gap > gap_factor * h else " ")
            parts.append(cur[4])
        out.append(normalize("".join(parts)))
    return [ln for ln in out if ln]


def _native_lines(page: pymupdf.Page) -> list[str]:
    words = page.get_text("words")
    items = [(w[0], w[1], w[2], w[3], w[4]) for w in words]
    return _group_lines(items, gap_factor=1.1)


def _ocr_lines(page: pymupdf.Page) -> tuple[list[str], float | None]:
    pix = page.get_pixmap(dpi=OCR_DPI)
    result, _ = _get_ocr()(pix.tobytes("png"))
    if not result:
        return [], None
    items, confs = [], []
    for box, text, conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append((min(xs), min(ys), max(xs), max(ys), text))
        try:
            confs.append(float(conf))
        except (TypeError, ValueError):
            pass
    return _group_lines(items, gap_factor=1.5), (sum(confs) / len(confs) if confs else None)


def extract_pdf(path: str | Path, allow_ocr: bool = True) -> ExtractedDoc:
    path = Path(path)
    doc = ExtractedDoc(path=str(path))
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf, start=1):
            native = page.get_text("text").strip()
            if len(native) >= MIN_TEXT_CHARS:
                doc.pages.append(PageText(i, _native_lines(page)))
            elif allow_ocr:
                try:
                    lines, conf = _ocr_lines(page)
                    doc.pages.append(PageText(i, lines, ocr=True, confidence=conf))
                except Exception:  # OCR engine unavailable/failed: keep going with an empty page
                    doc.ocr_available = False
                    doc.pages.append(PageText(i, [], ocr=True, confidence=0.0))
            else:
                doc.pages.append(PageText(i, []))
    return doc
