"""Phrasing and layout handling learned from real (Equinor Volve) daily reports.

All text below is invented for the test; the licensed reports are not part of the repository.
"""
from __future__ import annotations

from nwis.extraction.documents import classify, parse_ddr, parse_summary_report
from nwis.extraction.events import extract_events, parse_depths, split_sentences
from nwis.extraction.pdf_text import ExtractedDoc, PageText


def types(text: str, day_depth: float | None = 2000.0) -> set[str]:
    return {e.type for e in extract_events(split_sentences(text), day_depth=day_depth)}


def test_abbreviated_and_wrapped_wording_is_recognised():
    assert "stuck_pipe" in types("Hole packed- off and string torqued-up while reaming at 2199 m.")
    assert "stuck_pipe" in types("Got stuck while pulling through the window at 2190 m.")
    assert "stuck_pipe" in types("Tight hole from 2207 - 2226 m.")
    assert "mud_loss" in types("Lost circ several times at 2188 m.")
    assert "torque_spike" in types("Started drilling, TDS stalled at 16300 Nm at 2213 m.")


def test_one_sentence_can_report_two_hazards():
    found = types("Hole packed-off; lost circulation several times at 2199 m.")
    assert {"stuck_pipe", "mud_loss"} <= found


def test_routine_wording_is_not_an_incident():
    assert "overpressure" not in types("Drilling break at 3670 m. Circulated for samples. Flow check OK.")
    assert "torque_spike" not in types("Started release procedure by first torqued up the pipe to 10k ftlbs.")
    assert "stuck_pipe" not in types("Tagged TD at 1083 m, no tight spots.")


def test_depth_with_space_thousands_separator():
    assert parse_depths("worked casing to pass obstruction at 2 519 m") == [2519.0]
    assert parse_depths("drilled from 3052-3057 M") == [3057.0]


def test_obstruction_wording_counts_as_hole_trouble():
    evs = extract_events(split_sentences("Made several attempts to pass obstruction at 2 519 m. Sat down 15 MT."), day_depth=2536.0)
    assert [(e.type, e.md) for e in evs] == [("stuck_pipe", 2519.0)]


VOLVE_LIKE = [
    "Summary report",
    "Wellbore: 99/9-1 X | Period: 2001-02-02 00:00 - 2001-02-03 00:00",
    "Status: normal | Dist Drilled (m): 15 | Depth at Kick Off mMD: 100",
    "Report number: 9 | Hole Dia (in): 8.5 | Depth mMd: 2783",
    "Summar y of activities (24 Hours)",
    "SOMETHING INVENTED.",
    "Summar y of planned activities (24 Hours)",
    "NOTHING.",
    "Operations",
    "Start End | End | Main - State | Remark",
    "time time Depth | Sub",
    "mMD Activity",
    "00:00 | 06:00 2768 | drilling -- | ok | DRILLED FROM 2768 - 2771 M / SLIDING.",
    "survey",
    "06:00 | 09:00 2199 | drilling -- | fail | HOLE PACKED-OFF & LOST CIRC-STRING STUCK 2 MIN AT 2199 M. WORKED STRING FRE",
    "drill | E BY GOING DOWN.",
    "Drilling Fluid",
    "Sample Time | 13:45",
    "Comment: STRING STUCK ALSO IN THE FLUID SECTION AT 1500 M.",
]


def _doc() -> ExtractedDoc:
    return ExtractedDoc(path="x.pdf", pages=[PageText(number=1, lines=VOLVE_LIKE)])


def test_summary_report_layout_is_classified_and_parsed():
    doc = _doc()
    assert classify(doc, "x.pdf") == "DDR"
    day = parse_summary_report(doc)
    assert day is not None and day.well == "99/9-1 X" and day.date == "2001-02-03" and day.depth_md == 2783
    got = {(e.type, e.md) for e in day.events}
    assert ("stuck_pipe", 2199.0) in got and any(t == "mud_loss" for t, _ in got)
    # the wrapped cell is glued back together, and the text after the table is not read as remarks
    assert "FREE BY GOING DOWN" in " ".join(day.sentences).upper()
    assert "FLUID SECTION" not in " ".join(day.sentences)
    assert parse_ddr(_doc())[0].well == "99/9-1 X"
