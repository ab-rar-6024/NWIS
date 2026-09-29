"""Reset the database and ingest every well folder under data/raw."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.config import RAW_DIR
from nwis.db import reset_db
from nwis.ingest import ingest_well_dir, load_active_well


def main() -> None:
    t0 = time.time()
    conn = reset_db()
    dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir())
    for wd in dirs:
        t = time.time()
        if (wd / "well_header.json").exists():
            load_active_well(conn, wd)
            # replay logs are not stored: they reach the app through the live stream, like eRTMAC data would
            print(f"{wd.name}: active well registered (plan survey loaded)")
            continue
        res = ingest_well_dir(conn, wd)
        ocr = res.get("wcr", {}).get("ocr_pages")
        print(f"{wd.name}: wcr_events={res.get('wcr', {}).get('events')} ddr_events={res.get('ddr', {}).get('events')} "
              f"consolidated={res.get('ddr', {}).get('consolidated')} logs={res.get('log_rows')}"
              + (f" OCR pages={ocr} conf={res['wcr']['ocr_confidence']:.2f}" if ocr else "") + f" [{time.time() - t:.1f}s]")
    n_e = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    n_w = conn.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
    print(f"\n{n_w} wells, {n_e} consolidated events in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
