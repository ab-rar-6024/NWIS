"""Structure parsers for Well Completion Reports (WCR) and Daily Drilling Reports (DDR)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date

from ..config import FORMATION_LEXICON
from .events import RawEvent, extract_events, split_recommendations, split_sentences
from .pdf_text import ExtractedDoc


@dataclass
class WCRData:
    header: dict = field(default_factory=dict)
    tops: list[dict] = field(default_factory=list)
    casing: list[dict] = field(default_factory=list)
    mud: list[dict] = field(default_factory=list)
    events: list[RawEvent] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)


@dataclass
class DDRDay:
    well: str | None
    field: str | None
    page: int
    report_no: int | None
    date: str | None
    depth_md: float | None
    formation: str | None
    hole: str | None
    mw: float | None
    sentences: list[str]
    events: list[RawEvent] = field(default_factory=list)


def classify(doc: ExtractedDoc, filename: str = "") -> str:
    head = re.sub(r"[^A-Z]", "", " ".join(doc.pages[0].lines[:6]).upper()) if doc.pages else ""
    if "WELLCOMPLETIONREPORT" in head or "WCR" in filename.upper():
        return "WCR"
    if "DAILYDRILLINGREPORT" in head or "DDR" in filename.upper():
        return "DDR"
    if "SUMMARYREPORT" in head and "WELLBORE" in head:  # Equinor Volve daily report layout
        return "DDR"
    return "UNKNOWN"


def _num(s: str) -> float:
    return float(s.replace(",", "").strip())


def _fix_well_name(s: str) -> str:
    s = re.sub(r"\s+", "", s.upper())
    m = re.match(r"([A-Z]{3})-?([0-9OIl]{2,3})$", s)
    if m:  # OCR confuses O/0 and I/1 in numeric part
        return f"{m.group(1)}-{m.group(2).replace('O', '0').replace('I', '1').replace('L', '1')}"
    return s


def _kv(flat: str, key_rx: str, value_rx: str) -> str | None:
    m = re.search(key_rx + r"[\s|:]*" + value_rx, flat, re.I)
    return m.group(1).strip() if m else None


def _section(flat: str, start_rx: str, end_rx: str | None) -> str:
    m = re.search(start_rx, flat, re.I)
    if not m:
        return ""
    rest = flat[m.end():]
    if end_rx:
        e = re.search(end_rx, rest, re.I)
        if e:
            rest = rest[: e.start()]
    return rest


ROW_SEP = r"[\s|]+"


def parse_wcr(doc: ExtractedDoc) -> WCRData:
    flat = doc.text()
    data = WCRData()
    conf = doc.mean_confidence if doc.ocr_used else None
    h = data.header
    name = _kv(flat, r"Well\s*Name", r"([A-Z]{3}\s*-\s*[0-9OIl]{2,3})")
    if name:
        h["name"] = _fix_well_name(name)
    h["field"] = _kv(flat, r"Field", r"([A-Z][A-Za-z]+)")
    lat = _kv(flat, r"Latitude", r"(\d{1,2}\.\d+)")
    lon = _kv(flat, r"Longitude", r"(\d{1,3}\.\d+)")
    h["lat"] = float(lat) if lat else None
    h["lon"] = float(lon) if lon else None
    h["spud_date"] = _kv(flat, r"Spud\s*Date", r"(\d{4}-\d{2}-\d{2})")
    h["rig"] = _kv(flat, r"Rig", r"([A-Z][A-Z0-9\-]+)")
    kb = _kv(flat, r"KB\s*Elevation", r"(\d+(?:\.\d+)?)")
    h["kb_m"] = float(kb) if kb else None
    tdmd = _kv(flat, r"Total\s*Depth\s*\(MD\)", r"([\d,]+)")
    tdtvd = _kv(flat, r"Total\s*Depth\s*\(TVD\)", r"([\d,]+)")
    h["td_md"] = _num(tdmd) if tdmd else None
    h["td_tvd"] = _num(tdtvd) if tdtvd else None
    wt = _kv(flat, r"Well\s*Type", r"(Directional|Vertical|Horizontal)")
    h["directional"] = bool(wt and wt.lower() != "vertical")
    h["status"] = (_kv(flat, r"Status", r"(Completed|Active|Suspended|Abandoned)") or "COMPLETED").upper()

    tops_txt = _section(flat, r"FORMATION\s*TOPS", r"CASING\s*PROGRAM")
    for line in tops_txt.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z\- ]*[A-Za-z])" + ROW_SEP + r"(\d[\d,]*)" + ROW_SEP + r"(\d[\d,]*)\s*$", line)
        if m:
            data.tops.append({"formation": canonical_formation(m.group(1)), "md": _num(m.group(2)), "tvd": _num(m.group(3))})

    cas_txt = _section(flat, r"CASING\s*PROGRAM", r"MUD\s*PROGRAM")
    for line in cas_txt.splitlines():
        m = re.match(r'^\s*(\d+(?:-\d/\d)?")' + ROW_SEP + r'(\d+(?:-\d/\d)?")' + ROW_SEP + r"([\d,]+)" + ROW_SEP + r"([A-Z]-?\d+)" + ROW_SEP + r"([\d,]+)\s*$", line)
        if m:
            data.casing.append({"size": m.group(1), "hole": m.group(2), "shoe_md": _num(m.group(3)), "grade": m.group(4), "toc_md": _num(m.group(5))})

    mud_txt = _section(flat, r"MUD\s*PROGRAM", r"DRILLING\s*PROBLEMS")
    for line in mud_txt.splitlines():
        m = re.match(r'^\s*(\d+(?:-\d/\d)?")' + ROW_SEP + r"([\d,]+)\s*-\s*([\d,]+)" + ROW_SEP + r"(.+?)" + ROW_SEP + r"(\d\.\d\d)\s*-\s*(\d\.\d\d)\s*$", line)
        if m:
            data.mud.append({"hole": m.group(1), "from_md": _num(m.group(2)), "to_md": _num(m.group(3)),
                             "mud_type": m.group(4).strip(" |"), "mw_min": float(m.group(5)), "mw_max": float(m.group(6))})

    prob_txt = _section(flat, r"DRILLING\s*PROBLEMS[A-Z\s]*LEARNED", r"RECOMMENDATIONS")
    sents = split_sentences(prob_txt.replace("\n", " "))
    data.events = extract_events(sents, day_depth=None, ocr_conf=conf, allow_day_depth=False)

    rec_txt = _section(flat, r"5\.?\s*RECOMMENDATIONS|RECOMMENDATIONS", None)
    for s in split_recommendations(split_sentences(rec_txt.replace("\n", " "))):
        data.recommendations.append({"text": s, "formation": _formation_in(s)})
    return data


_LEX_KEYS = {re.sub(r"[^a-z]", "", f.lower()): f for f in FORMATION_LEXICON}


def canonical_formation(name: str | None) -> str | None:
    """Map a possibly OCR-damaged formation name onto the stratigraphic lexicon."""
    if not name:
        return name
    key = re.sub(r"[^a-z]", "", name.lower())
    if key in _LEX_KEYS:
        return _LEX_KEYS[key]
    close = difflib.get_close_matches(key, list(_LEX_KEYS), n=1, cutoff=0.86)
    return _LEX_KEYS[close[0]] if close else re.sub(r"\s+", " ", name).strip()


def _formation_in(text: str) -> str | None:
    t = re.sub(r"\s+", "", text).lower()
    for f in FORMATION_LEXICON:
        if re.sub(r"\s+", "", f).lower() in t:
            return f
    return None


TIME_ROW = re.compile(r"^\s*\d{2}:\d{2}[\s|]+\d{2}:\d{2}[\s|]*(.*)$")


_VOLVE_ROW = re.compile(r"^\s*(\d\d:\d\d)\s*\|\s*(\d\d:\d\d)[\s|]*(-?\d+(?:\.\d+)?)?\s*\|")
_VOLVE_END = re.compile(r"^\s*(?:Drilling\s*Fluid|Pore\s*Pressure|Lithology|Gas\s*Reading|Casing|Sur\s*vey|Status\s*info)\b")  # case-sensitive: 'survey' also appears as a wrapped activity word
_VOLVE_STATE_WORDS = {"trip", "drill", "survey", "circulating", "conditioning", "reaming", "other", "activity", "sub", "state"}


def _volve_kv(head: str, key: str, value_rx: str) -> str | None:
    m = re.search(key + r"[^|\n:]*:\s*" + value_rx, head, re.I)
    return m.group(1).strip() if m else None


def parse_summary_report(doc: ExtractedDoc) -> DDRDay | None:
    """Parse the 'Summary report' daily layout (header block, activity summary, operations table).

    The operations table wraps cells across lines, sometimes mid-word, so continuation fragments are glued back on.
    A report is one day for one wellbore, possibly spread over several pages."""
    lines = [ln for p in doc.pages for ln in p.lines]
    flat = "\n".join(lines)
    if not re.match(r"\s*Summary\s*report", flat, re.I) or not re.search(r"Wellbore\s*:", flat):
        return None
    head = flat.split("Operations", 1)[0]
    well = _volve_kv(head, r"Wellbore", r"([0-9]+/[0-9]+-[0-9A-Za-z]+(?:\s[A-Z])?)")
    period = re.search(r"Period\s*:\s*\d{4}-\d\d-\d\d[\d: ]*-\s*(\d{4}-\d\d-\d\d)", head)
    rno = _volve_kv(head, r"Report\s*number", r"(\d+)")
    hole = _volve_kv(head, r"Hole\s*Dia", r"(\d+(?:\.\d+)?)")
    hdepth = _volve_kv(head, r"Depth\s*mMd", r"(-?\d+(?:\.\d+)?)")

    remarks: list[str] = []
    depths: list[float] = []
    in_ops = False
    for ln in lines:
        if not in_ops:
            if re.match(r"^\s*Operations\s*$", ln):
                in_ops = True
            continue
        if _VOLVE_END.match(ln):
            break
        m = _VOLVE_ROW.match(ln)
        if m:
            if m.group(3):
                depths.append(float(m.group(3)))
            remarks.append(ln.rsplit("|", 1)[-1].strip())
            continue
        if not remarks:
            continue  # table header lines
        frag = ln.rsplit("|", 1)[-1].strip() if "|" in ln else ln.strip()
        if not frag or frag.lower() in _VOLVE_STATE_WORDS:
            continue
        remarks[-1] += frag if (frag[:1].isalpha() and remarks[-1][-1:].isalpha()) else " " + frag

    if not remarks:  # no operations table: fall back to the activity summary paragraph
        m = re.search(r"Summar\s*y of activities \(24 Hours\)\n(.*?)Summar\s*y of planned", flat, re.S | re.I)
        summary = " ".join(m.group(1).split()) if m else ""
        remarks = [] if summary.upper() in ("", "NONE") else [summary]

    sentences = split_sentences(" ".join(remarks))
    hd = float(hdepth) if hdepth and float(hdepth) > 0 else None
    depth = hd if hd is not None else (max(depths) if depths else None)
    day = DDRDay(well, None, 1, int(rno) if rno else None, period.group(1) if period else None, depth, None,
                 hole, None, sentences)
    day.events = _merge_same_incident(extract_events(sentences, day_depth=depth, page=1))
    return day


def _merge_same_incident(events: list[RawEvent], tol_m: float = 30.0) -> list[RawEvent]:
    """A report often re-describes one incident over several sentences; keep one event per type within tol_m."""
    out: list[RawEvent] = []
    for e in events:
        twin = next((o for o in out if o.type == e.type and o.md is not None and e.md is not None and abs(o.md - e.md) <= tol_m), None)
        if twin is None:
            out.append(e)
        else:
            twin.sentences.extend(e.sentences)
    return out


def parse_ddr(doc: ExtractedDoc) -> list[DDRDay]:
    vol = parse_summary_report(doc)
    if vol is not None:
        return [vol]
    days: list[DDRDay] = []
    conf = doc.mean_confidence if doc.ocr_used else None
    for page in doc.pages:
        flat = "\n".join(page.lines)
        if not re.search(r"OPERATIONS\s*SUMMARY", flat, re.I):
            continue
        parts = re.split(r"OPERATIONS\s*SUMMARY[^\n]*\n?", flat, maxsplit=1, flags=re.I)
        head, body = parts[0], parts[1] if len(parts) > 1 else ""
        wname = _kv(head, r"Well", r"([A-Z]{3}\s*-\s*[0-9OIl]{2,3})")
        wfield = _kv(head, r"Field", r"([A-Z][A-Za-z]+)")
        rno = _kv(head, r"Report\s*No", r"(\d+)")
        dt = _kv(head, r"Date", r"(\d{4}-\d{2}-\d{2})")
        depth = _kv(head, r"Depth\s*\(24:00\)", r"([\d,]+)")
        fm = _kv(head, r"Formation", r"([A-Z][A-Za-z\- ]*[a-z])")
        hole = _kv(head, r"Hole\s*size", r'(\d+(?:-\d/\d)?")')
        mw = _kv(head, r"Mud\s*weight", r"(\d\.\d\d)")
        acts: list[str] = []
        for line in body.splitlines():
            if re.match(r"^\s*From[\s|]+To[\s|]+Activity", line, re.I):
                continue
            m = TIME_ROW.match(line)
            if m:
                acts.append(m.group(1).strip(" |"))
            elif acts and line.strip():
                acts[-1] += " " + line.strip(" |")
        sentences = split_sentences(" ".join(acts))
        day = DDRDay(_fix_well_name(wname) if wname else None, wfield, page.number, int(rno) if rno else None, dt, _num(depth) if depth else None, canonical_formation(fm.strip()) if fm else None,
                     hole, float(mw) if mw else None, sentences)
        day.events = extract_events(sentences, day_depth=day.depth_md, ocr_conf=conf, page=page.number)
        days.append(day)
    return days
