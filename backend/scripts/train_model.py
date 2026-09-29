"""Train the drilling-risk models from the knowledge base (run after ingest_all.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.db import connect
from nwis.risk_model import train


def main() -> None:
    conn = connect()
    m = train(conn)
    print(f"\ntrained in {m['trained_seconds']}s on {m['n_samples']} samples / {m['n_wells']} wells\n")
    print(f"{'hazard':16s} {'base rate':>9s} | {'full AUC':>8s} {'AP':>5s} | {'offsets only':>12s} | {'live signals only':>17s} | thr")
    for et, r in m["results"]["full"].items():
        o = m["results"].get("offset_knowledge_only", {}).get(et, {})
        l = m["results"].get("live_signals_only", {}).get(et, {})
        print(f"{et:16s} {r['base_rate']:9.3f} | {r['auc']:8.3f} {r['ap']:5.2f} | {o.get('auc', float('nan')):12.3f} | {l.get('auc', float('nan')):17.3f} | {r['threshold']:.2f}")


if __name__ == "__main__":
    main()
