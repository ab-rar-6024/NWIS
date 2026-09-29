"""Evaluate document extraction against the generator's ground truth (synthetic data only).

Usage: python scripts/eval_extraction.py [--ocr] [--wells N]
Reports precision / recall / F1 per event type and depth error, for DDR-only, WCR-only and (DDR+WCR merged).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.config import EVENT_TYPES, RAW_DIR, TRUTH_DIR
from nwis.extraction.documents import parse_ddr, parse_wcr
from nwis.extraction.pdf_text import extract_pdf

EXPLICIT_TOL = 15.0
DAY_TOL = 260.0


def match(truth: list[dict], preds: list[dict]):
    """Greedy one-to-one match on type and depth. Returns (matched_pairs, unmatched_truth, unmatched_pred)."""
    used = set()
    pairs = []
    for t in sorted(truth, key=lambda x: x["md"]):
        best, best_d = None, 1e9
        for j, p in enumerate(preds):
            if j in used or p["type"] != t["type"]:
                continue
            tol = EXPLICIT_TOL if p["depth_source"] == "explicit" else DAY_TOL
            d = abs(p["md"] - t["md"]) if p["depth_source"] == "explicit" else (t["md"] - p["md"] + 130 if p["md"] >= t["md"] else 1e9)
            dd = abs(p["md"] - t["md"])
            if p["depth_source"] == "explicit" and dd <= tol and dd < best_d:
                best, best_d = j, dd
            elif p["depth_source"] != "explicit" and 0 <= p["md"] - t["md"] <= DAY_TOL and dd < best_d:
                best, best_d = j, dd
        if best is not None:
            used.add(best)
            pairs.append((t, preds[best]))
    matched_t = {id(t) for t, _ in pairs}
    return pairs, [t for t in truth if id(t) not in matched_t], [p for j, p in enumerate(preds) if j not in used]


def merge_sources(ddr: list[dict], wcr: list[dict]) -> list[dict]:
    out = list(ddr)
    for w in wcr:
        dup = [d for d in out if d["type"] == w["type"] and abs(d["md"] - w["md"]) <= 20]
        if not dup:
            out.append(w)
    return out


def to_dict(ev) -> dict:
    return {"type": ev.type, "md": ev.md, "depth_source": ev.depth_source, "npt_h": ev.npt_h, "details": ev.details,
            "outcome": ev.outcome, "mitigations": ev.mitigations}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr", action="store_true", help="run OCR on scanned pages (slow)")
    ap.add_argument("--wells", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    stats = {k: defaultdict(lambda: defaultdict(int)) for k in ("DDR", "WCR", "MERGED")}
    depth_err, npt_ok, npt_n = [], 0, 0
    wells = sorted(p for p in RAW_DIR.iterdir() if (p / "DDR.pdf").exists())
    if args.wells:
        wells = wells[: args.wells]
    for wd in wells:
        truth = json.loads((TRUTH_DIR / f"{wd.name}.json").read_text())["events"]
        ddr_doc = extract_pdf(wd / "DDR.pdf", allow_ocr=args.ocr)
        ddr_ev = [to_dict(e) for d in parse_ddr(ddr_doc) for e in d.events]
        wcr_doc = extract_pdf(wd / "WCR.pdf", allow_ocr=args.ocr)
        wcr_ev = [to_dict(e) for e in parse_wcr(wcr_doc).events]
        for label, preds in (("DDR", ddr_ev), ("WCR", wcr_ev), ("MERGED", merge_sources(ddr_ev, wcr_ev))):
            pairs, miss, extra = match(truth, preds)
            for t, p in pairs:
                stats[label][t["type"]]["tp"] += 1
                if label == "DDR" and p["depth_source"] == "explicit":
                    depth_err.append(abs(p["md"] - t["md"]))
                if label == "DDR" and t["npt_h"] and p["npt_h"] is not None:
                    npt_n += 1
                    npt_ok += abs(p["npt_h"] - t["npt_h"]) < 0.06
            for t in miss:
                stats[label][t["type"]]["fn"] += 1
                if args.verbose and label == "DDR":
                    print("MISS", wd.name, t["type"], t["md"])
            for p in extra:
                stats[label][p["type"]]["fp"] += 1
                if args.verbose and label == "DDR":
                    print("FP  ", wd.name, p["type"], p["md"], p["depth_source"])
    for label in ("DDR", "WCR", "MERGED"):
        print(f"\n== {label} ==")
        tot = defaultdict(int)
        for et in EVENT_TYPES:
            s = stats[label][et]
            tp, fp, fn = s["tp"], s["fp"], s["fn"]
            for k, v in (("tp", tp), ("fp", fp), ("fn", fn)):
                tot[k] += v
            pr = tp / (tp + fp) if tp + fp else 0
            rc = tp / (tp + fn) if tp + fn else 0
            f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0
            print(f"  {et:16s} P={pr:.2f} R={rc:.2f} F1={f1:.2f}  (tp={tp} fp={fp} fn={fn})")
        pr = tot["tp"] / (tot["tp"] + tot["fp"]) if tot["tp"] + tot["fp"] else 0
        rc = tot["tp"] / (tot["tp"] + tot["fn"]) if tot["tp"] + tot["fn"] else 0
        print(f"  {'OVERALL':16s} P={pr:.2f} R={rc:.2f} F1={2 * pr * rc / (pr + rc) if pr + rc else 0:.2f}")
    if depth_err:
        import statistics
        print(f"\nDDR explicit-depth error: median {statistics.median(depth_err):.1f} m, max {max(depth_err):.1f} m")
    if npt_n:
        print(f"DDR NPT exact-match rate: {npt_ok}/{npt_n}")


if __name__ == "__main__":
    main()
