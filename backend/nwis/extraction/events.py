"""Rule-based NLP extraction of drilling events from report sentences.

Design notes
- Trigger patterns identify an *event*; mitigation/outcome sentences that follow are attached to the open event
  (a cluster of up to CLUSTER_WINDOW sentences), so "Kick taken ... / Killed well ... / Well stable" is one record.
- Negations ("No losses observed", "Mud losses: nil") and contingency statements ("kept LCM ready as precaution
  against losses") are rejected, which is where naive keyword matching fails on real reports.
- Patterns tolerate missing spaces because OCR output frequently drops them.
- Every event carries a confidence score reflecting depth explicitness, quantities found, mitigation found and
  OCR quality.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CLUSTER_WINDOW = 4  # sentences after a trigger that can still belong to the same event
DEPTH_MIN, DEPTH_MAX = 20.0, 9500.0


def _p(pattern: str, flags: int = re.I) -> re.Pattern:
    # OCR often drops spaces: allow zero whitespace where the pattern asks for at least one
    return re.compile(pattern.replace(r"\s+", r"\s*"), flags)


TRIGGERS: dict[str, re.Pattern] = {
    "mud_loss": _p(
        r"(?:seepage|partial|severe|total)\s+(?:mud\s+)?loss(?:es)?\b"
        r"|lost\s+circulation"
        r"|loss\s+of\s+returns"
        r"|observed\s+(?:mud\s+)?losses"
        r"|mud\s+losses?\s+(?:encountered|noted|observed)"
    ),
    "kick": _p(
        r"kick\s+(?:taken|detected|observed|noted)"
        r"|gas\s+kick"
        r"|well\s+(?:was\s+)?flowing"
        r"|positive\s+flow\s*check"
    ),
    "stuck_pipe": _p(
        r"(?:string|pipe|drillstring|bha)\s+(?:became\s+|was\s+|got\s+)?stuck"
        r"|stuck\s+(?:pipe|string)"
        r"|pack-?off"
    ),
    "overpressure": _p(
        r"overpress\w*"
        r"|drilling\s+break"
        r"|abnormal(?:ly)?\s+(?:high\s+)?pressure"
    ),
    "torque_spike": _p(
        r"torque\s+spikes?"
        r"|(?:high|erratic)\s+(?:and\s+erratic\s+)?torque"
        r"|torque\s+peak"
    ),
    "cementing_issue": _p(
        r"poor\s+cement\s+bond"
        r"|cement\s+channel\w*"
        r"|cement\s+top\s+(?:found\s+)?lower"
        r"|remedial\s+squeeze"
        r"|top-?up\s+cement"
    ),
    "fishing": _p(
        r"fishing\s+operation"
        r"|fish\s+(?:was\s+)?(?:not\s+)?recovered"
        r"|lost\s+[\w\- ]{2,40}?\s+in\s+hole"
    ),
}

NEGATION = _p(r"\b(?:no|nil|not|without|negative|nor|zero|never)\b")
POST_NEGATION = _p(r"(?:loss(?:es)?|kick|torque|gas|pack-?off)\s*[:\-]?\s*(?:nil|none|negative)|flow\s*check\s+negative")
CONTINGENCY = _p(r"\b(?:precaution|contingency|in\s+case|if\s+needed|should|ready\s+for|anticipat\w+|prepared?\s+to|to\s+avoid|prevent\w*|against)\b")
RECOMMEND = _p(r"^\s*(?:recommend\w*|lesson\w*|it\s+is\s+recommended|suggest\w*)")

DEPTH_RE = re.compile(
    r"(?<![\d.])(\d{1,2},\d{3}|\d{2,5})(?:\.\d+)?\s*"
    r"(?:(?:mMD|mts|meters|metres)(?![\d/])"  # unambiguous units may be glued to the next word by OCR
    r"|m(?![\w/])"  # plain metres: not m3, m/hr or the start of a word
    r"|(?<=\d)m(?=(?:in|at|to|and|of|with|the|while|from|during)[A-Za-z]))",  # OCR: '2371mintheBarail'
    re.I,
)
NPT_RE = _p(r"NPT\s*(\d+(?:\.\d+)?)\s*h")
AFTER_HRS_RE = _p(r"after\s+(?:soak\s+of\s+)?(\d+(?:\.\d+)?)\s*h")

RATE_RE = _p(r"(\d+(?:\.\d+)?)\s*m3\s*/\s*h")
RESIDUAL_RE = _p(r"(?:reduced\s+to|residual\s+loss(?:es)?(?:\s+of)?)\s*(\d+(?:\.\d+)?)\s*m3\s*/\s*h")
LCM_VOL_RE = _p(r"(\d+)\s*m3\s+(?:LCM|of\s+LCM)")
LCM_VOL_ALT_RE = _p(r"LCM\s+sweep,?\s*(\d+)\s*m3")
PPB_RE = _p(r"(\d+)\s*ppb")
LCM_TYPE_RE = _p(r"(fine\s+nut\s+plug|medium\s+mica/?\s*CaCO3|coarse\s+fib(?:re|er)|sized\s+CaCO3|graphite\s+blend)")
GAIN_RE = _p(r"(?:pit\s+gain\s+(?:of\s+)?|gain\s+of\s+)(\d+(?:\.\d+)?)\s*m3")
SIDPP_RE = _p(r"SIDPP\s*(\d+)\s*bar")
SICP_RE = _p(r"SICP\s*(\d+)\s*bar")
MW_STEP_RE = _p(r"(\d\.\d\d)\s*(?:to|->|-\s*>|→)\s*(\d\.\d\d)\s*SG")
MW_TO_RE = _p(r"(?:increased|raised)\s+(?:to\s+)?(\d\.\d\d)\s*SG")
OVERPULL_RE = _p(r"overpull\s*(?:of\s*)?(\d+)\s*t\b")
MECH_RE = _p(r"(pack-?off|differential\s+sticking|mechanical\s*\(?key-?seat\)?|hole\s+collapse)")
GAS_RE = _p(r"(?:gas\s+(?:increased\s+to\s+)?|gas\s+)(\d+)\s*units")
PP_RE = _p(r"(?:pore\s+pressure|formation\s+pressure)\s*(?:approx\.?\s*)?(\d\.\d\d)\s*SG")
PEAK_RE = _p(r"(?:up\s+to|peak)\s*(\d+(?:\.\d+)?)\s*kNm")
BASE_RE = _p(r"(?:normal|baseline|versus)\s*(\d+(?:\.\d+)?)\s*kNm|(\d+(?:\.\d+)?)\s*kNm\s*baseline")
SQUEEZE_VOL_RE = _p(r"(\d+)\s*m3\s*(?:slurry|cement)")
CASING_RE = _p(r'(\d+(?:-\d/\d)?")\s*(?:[A-Z]-?\d+\s*)?casing')
TOOL_RE = _p(r"lost\s+([\w\- ]{2,40}?)\s+in\s+hole")
SEVERITY_RE = _p(r"\b(seepage|partial|severe|total)\b")

MITIGATIONS: list[tuple[str, re.Pattern]] = [
    ("lcm_pill", _p(r"LCM\s+(?:pill|sweep)|LCM\s+in\s+the\s+active|fine\s+LCM|cured\s+with\s+LCM")),
    ("reduce_rate", _p(r"reduced\s+(?:pump|flow)\s+rate|lowered\s+flow\s+rate|reduced\s+flow\s+rate")),
    ("cement_plug", _p(r"cement\s+plug")),
    ("weight_up", _p(r"weighted\s+up|(?:MW|mud\s+weight)\s+(?:was\s+)?(?:raised|increased)|increased\s+MW|raised\s+MW|mud\s+weight\s+raised")),
    ("shut_in", _p(r"shut\s+in|driller'?s\s+method|wait\s+and\s+weight")),
    ("jarring", _p(r"\bjars?\b|jarring")),
    ("freeing_pill", _p(r"freeing\s+pill")),
    ("backoff", _p(r"backed\s*off|back-?off")),
    ("reduce_rpm", _p(r"reduced\s+RPM|RPM\s+reduced")),
    ("wiper_trip", _p(r"wiper\s+trip|hole\s+clean")),
    ("squeeze", _p(r"squeez\w+")),
    ("fishing_run", _p(r"overshot|fishing\s+run")),
]

OUTCOMES: list[tuple[str, re.Pattern]] = [
    ("cured", _p(r"losses\s+cured|full\s+returns\s+regained|returns\s+restored")),
    ("reduced", _p(r"losses\s+reduced|residual\s+loss|partial\s+returns\s+regained")),
    ("blind", _p(r"blind|without\s+returns")),
    ("freed", _p(r"pipe\s+freed|freed\s+(?:by|after)|freed\s+after")),
    ("fish_left", _p(r"backed\s*off|leaving\s+bha|bha\s+in\s+hole")),
    ("controlled", _p(r"well\s+(?:dead|stable\s+after)|flow\s*check\s+negative|mud\s+weight\s+(?:was\s+)?increased|weighted\s+up|MW\s+raised|increased\s+MW")),
    ("remediated", _p(r"remedial\s+squeeze|squeezed|top-?up")),
    ("recovered", _p(r"fish\s+(?:was\s+)?recovered|recovered\s+after")),
    ("abandoned_fish", _p(r"not\s+recovered|abandon")),
    ("normalised", _p(r"reduced\s+RPM|RPM\s+reduced|hole\s+clean")),
]


@dataclass
class RawEvent:
    type: str
    md: float | None
    depth_source: str  # 'explicit' | 'day' | 'none'
    sentences: list[str]
    details: dict = field(default_factory=dict)
    mitigations: list[str] = field(default_factory=list)
    outcome: str | None = None
    npt_h: float | None = None
    confidence: float = 0.0
    page: int | None = None
    severity: str | None = None
    formation: str | None = None


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[A-Za-z0-9\)\"]\.)\s*(?=[A-Z])|(?<=[!?])\s*(?=[A-Z])", text)
    return [p.strip() for p in parts if p and p.strip()]


def parse_depth(sentence: str) -> float | None:
    for m in DEPTH_RE.finditer(sentence):
        v = float(m.group(1).replace(",", ""))
        if DEPTH_MIN <= v <= DEPTH_MAX:
            return v
    return None


def parse_depths(sentence: str) -> list[float]:
    out = []
    for m in DEPTH_RE.finditer(sentence):
        v = float(m.group(1).replace(",", ""))
        if DEPTH_MIN <= v <= DEPTH_MAX:
            out.append(v)
    return out


def _negated(sentence: str, match: re.Match) -> bool:
    before = sentence[max(0, match.start() - 32): match.start()]
    if NEGATION.search(before):
        return True
    if POST_NEGATION.search(sentence):
        return True
    return False


def _first_num(rx: re.Pattern, text: str) -> float | None:
    m = rx.search(text)
    if not m:
        return None
    for g in m.groups():
        if g is not None:
            return float(g)
    return None


def _find_trigger(sentence: str) -> str | None:
    """Return the event type triggered by this sentence, or None (also None if negated / contingency)."""
    if RECOMMEND.search(sentence):
        return None
    if CONTINGENCY.search(sentence) and not re.search(r"\b(?:observed|encountered|experienced|taken|noted)\b", sentence, re.I):
        return None
    hits: list[tuple[int, str, re.Match]] = []
    for et, rx in TRIGGERS.items():
        m = rx.search(sentence)
        if m and not _negated(sentence, m):
            hits.append((m.start(), et, m))
    if not hits:
        return None
    # prefer the more specific consequence types when several fire in one sentence
    priority = {"cementing_issue": 0, "fishing": 1, "kick": 2, "stuck_pipe": 3, "overpressure": 4, "mud_loss": 5, "torque_spike": 6}
    hits.sort(key=lambda h: (priority[h[1]], h[0]))
    return hits[0][1]


def _fill_details(ev: RawEvent, text: str) -> None:
    d: dict = {}
    t = ev.type
    if t == "mud_loss":
        rates = [float(x.group(1)) for x in RATE_RE.finditer(text)]
        res = _first_num(RESIDUAL_RE, text)
        main = [r for r in rates if res is None or abs(r - res) > 1e-9]
        if main:
            d["rate_m3h"] = main[0]
        elif rates:
            d["rate_m3h"] = rates[0]
        if res is not None:
            d["residual_m3h"] = res
        v = _first_num(LCM_VOL_RE, text) or _first_num(LCM_VOL_ALT_RE, text)
        if v:
            d["lcm_vol_m3"] = v
        p = _first_num(PPB_RE, text)
        if p:
            d["lcm_ppb"] = p
        m = LCM_TYPE_RE.search(text)
        if m:
            d["lcm_type"] = re.sub(r"\s+", " ", m.group(1)).lower()
        s = SEVERITY_RE.search(text)
        if s:
            d["severity"] = s.group(1).lower()
        elif "rate_m3h" in d:
            r = d["rate_m3h"]
            d["severity"] = "seepage" if r < 3 else "partial" if r < 20 else "severe" if r < 45 else "total"
        if re.search(r"loss\s+of\s+returns|total\s+loss", text, re.I):
            d["severity"] = "total" if d.get("severity") != "severe" else d["severity"]
    elif t == "kick":
        for key, rx in (("gain_m3", GAIN_RE), ("sidpp_bar", SIDPP_RE), ("sicp_bar", SICP_RE)):
            v = _first_num(rx, text)
            if v is not None:
                d[key] = v
        m = MW_STEP_RE.search(text)
        if m:
            d["mw0"], d["mw1"] = float(m.group(1)), float(m.group(2))
        else:
            v = _first_num(MW_TO_RE, text)
            if v:
                d["mw1"] = v
        mm = re.search(r"(driller'?s\s+method|wait\s+and\s+weight(?:\s+method)?)", text, re.I)
        if mm:
            d["method"] = re.sub(r"\s+", " ", mm.group(1)).title()
    elif t == "stuck_pipe":
        v = _first_num(OVERPULL_RE, text)
        if v is not None:
            d["overpull_t"] = v
        m = MECH_RE.search(text)
        if m:
            d["mechanism"] = re.sub(r"\s+", " ", m.group(1)).lower()
    elif t == "overpressure":
        v = _first_num(GAS_RE, text)
        if v is not None:
            d["gas_units"] = v
        v = _first_num(PP_RE, text)
        if v is not None:
            d["pp_sg"] = v
        m = MW_STEP_RE.search(text)
        if m:
            d["mw0"], d["mw1"] = float(m.group(1)), float(m.group(2))
        else:
            v = _first_num(MW_TO_RE, text)
            if v:
                d["mw1"] = v
    elif t == "torque_spike":
        v = _first_num(PEAK_RE, text)
        if v is not None:
            d["peak_knm"] = v
        v = _first_num(BASE_RE, text)
        if v is not None:
            d["baseline_knm"] = v
    elif t == "cementing_issue":
        v = _first_num(SQUEEZE_VOL_RE, text)
        if v is not None:
            d["squeeze_vol_m3"] = v
        m = CASING_RE.search(text)
        if m:
            d["casing"] = m.group(1)
        if re.search(r"poor\s*cement\s*bond|poor\s*bond", text, re.I):
            d["kind"] = "poor bond"
        elif re.search(r"channel", text, re.I):
            d["kind"] = "channeling"
        elif re.search(r"lower\s+than\s+planned|top\s*of\s*cement|top-?up", text, re.I):
            d["kind"] = "low top of cement"
    elif t == "fishing":
        m = TOOL_RE.search(text)
        if m:
            d["tool"] = m.group(1).strip()
        else:
            m2 = re.search(r"operation\s+at\s+[\d,]+\s*\w*:\s*([\w\- ]{2,40}?)\s+left\s+in\s+hole", text, re.I)
            if m2:
                d["tool"] = m2.group(1).strip()
        d["recovered"] = not re.search(r"not\s+recovered|abandon", text, re.I)
    ev.details = d


def _classify_tags(ev: RawEvent, text: str) -> None:
    ev.mitigations = [name for name, rx in MITIGATIONS if rx.search(text)]
    # drop tags that don't make sense for the type
    allowed = {
        "mud_loss": {"lcm_pill", "reduce_rate", "cement_plug"},
        "kick": {"shut_in", "weight_up"},
        "stuck_pipe": {"jarring", "freeing_pill", "backoff"},
        "overpressure": {"weight_up"},
        "torque_spike": {"reduce_rpm", "wiper_trip"},
        "cementing_issue": {"squeeze"},
        "fishing": {"fishing_run"},
    }[ev.type]
    ev.mitigations = [m for m in ev.mitigations if m in allowed]
    allowed_out = {
        "mud_loss": {"cured", "reduced", "blind"},
        "kick": {"controlled"},
        "stuck_pipe": {"freed", "fish_left"},
        "overpressure": {"controlled"},
        "torque_spike": {"normalised"},
        "cementing_issue": {"remediated"},
        "fishing": {"recovered", "abandoned_fish"},
    }[ev.type]
    outs = [name for name, rx in OUTCOMES if name in allowed_out and rx.search(text)]
    # backing off means the pipe was NOT freed
    if ev.type == "stuck_pipe" and "backoff" in ev.mitigations:
        outs = ["fish_left"]
    elif ev.type == "stuck_pipe" and "freed" in outs:
        outs = ["freed"]
    ev.outcome = outs[0] if outs else None
    if ev.type == "overpressure" and ev.outcome is None and "weight_up" in ev.mitigations:
        ev.outcome = "controlled"
    if ev.type == "kick" and ev.outcome is None and "weight_up" in ev.mitigations:
        ev.outcome = "controlled"


def _npt(text: str) -> float | None:
    v = _first_num(NPT_RE, text)
    if v is None:
        v = _first_num(AFTER_HRS_RE, text)
    return v


def _severity_from(ev: RawEvent) -> str:
    """Coarse severity bucket from NPT (and type-specific details)."""
    npt = ev.npt_h or 0.0
    if ev.type == "kick":
        npt = max(npt, 12.0 if (ev.details.get("gain_m3") or 0) > 3 else 0)
    if ev.type == "mud_loss" and ev.details.get("severity") in ("severe", "total"):
        npt = max(npt, 24.0)
    if npt >= 48:
        return "critical"
    if npt >= 18:
        return "high"
    if npt >= 6:
        return "medium"
    return "low"


def extract_events(
    sentences: list[str],
    day_depth: float | None = None,
    ocr_conf: float | None = None,
    page: int | None = None,
    allow_day_depth: bool = True,
) -> list[RawEvent]:
    """Extract events from an ordered list of sentences belonging to one report section/day."""
    events: list[RawEvent] = []
    open_ev: RawEvent | None = None
    open_idx = -10
    for i, s in enumerate(sentences):
        et = _find_trigger(s)
        depth_here = parse_depth(s)
        merge = (
            et is not None
            and open_ev is not None
            and et == open_ev.type
            and i - open_idx <= CLUSTER_WINDOW
            and (depth_here is None or open_ev.md is None or abs(depth_here - open_ev.md) <= 30)
            and open_ev.type not in ("cementing_issue",)
        )
        if et is not None and not merge:
            open_ev = RawEvent(type=et, md=depth_here, depth_source="explicit" if depth_here is not None else "none",
                               sentences=[s], page=page)
            events.append(open_ev)
            open_idx = i
        elif open_ev is not None and i - open_idx <= CLUSTER_WINDOW:
            # continuation sentence: attach unless it starts a routine drilling narrative
            if re.match(r"^\s*(?:drilled|performed wiper|circulated bottoms|changed out|rig maintenance|conducted|mw\s|background|took survey|reached casing|ran\s|cemented|nipple)", s, re.I) and et is None:
                open_ev = None
            else:
                open_ev.sentences.append(s)
                if open_ev.md is None and depth_here is not None:
                    open_ev.md = depth_here
                    open_ev.depth_source = "explicit"
        else:
            open_ev = None

    out: list[RawEvent] = []
    for ev in events:
        text = " ".join(ev.sentences)
        if ev.md is None:
            if allow_day_depth and day_depth is not None:
                ev.md, ev.depth_source = day_depth, "day"
            else:
                continue
        _fill_details(ev, text)
        _classify_tags(ev, text)
        ev.npt_h = _npt(text)
        ev.severity = _severity_from(ev)
        score = 0.50
        score += 0.20 if ev.depth_source == "explicit" else 0.0
        score += 0.10 if ev.details else 0.0
        score += 0.10 if ev.mitigations else 0.0
        score += 0.05 if ev.npt_h is not None else 0.0
        score += 0.05 if ev.outcome else 0.0
        if ocr_conf is not None:
            score *= 0.75 + 0.25 * max(0.0, min(1.0, ocr_conf))
        ev.confidence = round(min(score, 0.99), 2)
        out.append(ev)
    return out


def split_recommendations(sentences: list[str]) -> list[str]:
    return [s for s in sentences if RECOMMEND.search(s)]
