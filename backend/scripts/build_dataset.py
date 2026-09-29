"""Build the SYNTHETIC demo dataset under data/raw (and data/samples, data/truth).

Ground-truth event lists are written to data/truth and are only used by evaluation scripts and tests;
the application itself never reads them.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.config import DATA_DIR, RAW_DIR, TRUTH_DIR
from nwis.synth.docs_text import build_ddr, build_wcr
from nwis.synth.pdfgen import rasterise_to_scan, write_ddr_pdf, write_wcr_pdf
from nwis.synth.wellgen import generate_field

SAMPLES_DIR = DATA_DIR / "samples"
HOLDOUT = {"DGR-15", "BRS-15"}  # documents kept out of the initial load; used to demo live PDF upload
SCANNED_EVERY = 11  # every Nth well gets a rasterised (OCR-needed) completion report


def main(seed: int = 26121) -> None:
    t0 = time.time()
    for d in (RAW_DIR, TRUTH_DIR, SAMPLES_DIR):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    wells, active = generate_field(seed)
    print(f"generated {len(wells)} historical wells + active {active.name} in {time.time() - t0:.1f}s")

    rng = np.random.default_rng(seed + 1)
    scanned = []
    for k, w in enumerate(wells):
        truth = [
            {"id": e.id, "type": e.type, "md": round(e.md, 1), "tvd": round(e.tvd, 1), "formation": e.formation,
             "npt_h": e.npt_h, "details": e.details}
            for e in w.events
        ]
        (TRUTH_DIR / f"{w.name}.json").write_text(json.dumps({"well": w.name, "events": truth}, indent=1), encoding="utf-8")

        target = SAMPLES_DIR if w.name in HOLDOUT else RAW_DIR / w.name
        target.mkdir(parents=True, exist_ok=True)
        prefix = f"{w.name}_" if w.name in HOLDOUT else ""
        days = build_ddr(w, rng)
        write_ddr_pdf(target / f"{prefix}DDR.pdf", w, days, rng)
        wcr_path = target / f"{prefix}WCR.pdf"
        write_wcr_pdf(wcr_path, w, build_wcr(w, rng))
        if k % SCANNED_EVERY == SCANNED_EVERY - 1 and w.name not in HOLDOUT:
            tmp = wcr_path.with_suffix(".tmp.pdf")
            wcr_path.replace(tmp)
            rasterise_to_scan(tmp, wcr_path, rng)
            tmp.unlink()
            scanned.append(w.name)
        if w.name not in HOLDOUT:
            w.survey.to_csv(target / "survey.csv", index=False, float_format="%.2f")
            w.logs.drop(columns=["formation"]).to_csv(target / "logs.csv", index=False, float_format="%.3f")
        print(f"  {w.name}: {len(days)} DDR pages, {len(w.events)} events" + (" [scanned WCR]" if w.name in scanned else "")
              + (" [held-out sample]" if w.name in HOLDOUT else ""))

    # live demo well
    adir = RAW_DIR / active.name
    adir.mkdir(parents=True, exist_ok=True)
    active.survey.to_csv(adir / "plan_survey.csv", index=False, float_format="%.2f")
    pd.DataFrame(active.casing)[["size", "hole", "shoe_md", "grade", "toc_md"]].to_csv(adir / "plan_casing.csv", index=False)
    logs = active.logs.drop(columns=["formation"]).copy()
    hours = np.cumsum(5.0 / np.clip(logs["rop"].values, 1.0, None))
    logs.insert(0, "elapsed_h", np.round(hours, 3))
    logs.to_csv(adir / "replay_logs.csv", index=False, float_format="%.3f")
    (adir / "well_header.json").write_text(json.dumps({
        "name": active.name, "field": active.field, "lat": active.lat, "lon": active.lon, "rig": active.rig,
        "kb_m": active.kb_m, "spud_date": active.spud_date.isoformat(), "planned_td_md": active.td_md,
        "status": "ACTIVE", "directional": active.directional,
    }, indent=1), encoding="utf-8")
    (TRUTH_DIR / f"{active.name}.json").write_text(json.dumps({"well": active.name, "tops_md": {k: round(v, 1) for k, v in active.tops_md.items()}, "events": [
        {"id": e.id, "type": e.type, "md": round(e.md, 1), "formation": e.formation, "npt_h": e.npt_h}
        for e in active.events]}, indent=1), encoding="utf-8")
    total = sum(f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file())
    print(f"done in {time.time() - t0:.1f}s, {total / 1e6:.1f} MB written; scanned WCRs: {scanned}")


if __name__ == "__main__":
    main()
