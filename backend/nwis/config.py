from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
TRUTH_DIR = DATA_DIR / "truth"
MODEL_DIR = DATA_DIR / "models"
UPLOAD_DIR = Path(os.environ.get("NWIS_UPLOAD_DIR", DATA_DIR / "uploads"))
DB_PATH = Path(os.environ.get("NWIS_DB", DATA_DIR / "nwis.db"))

# Reference point of the (synthetic) operating area, Upper Assam basin.
AREA_LAT0 = 27.30
AREA_LON0 = 95.35

# Event taxonomy shared by extractor, knowledge base, risk model and UI.
EVENT_TYPES = [
    "mud_loss",
    "kick",
    "stuck_pipe",
    "overpressure",
    "torque_spike",
    "cementing_issue",
    "fishing",
]

# Types the predictive model scores (fishing is a consequence, cementing is tied to casing points).
RISK_TYPES = ["mud_loss", "kick", "stuck_pipe", "overpressure", "torque_spike"]

EVENT_LABELS = {
    "mud_loss": "Mud loss",
    "kick": "Kick",
    "stuck_pipe": "Stuck pipe",
    "overpressure": "Overpressure zone",
    "torque_spike": "Torque spike",
    "cementing_issue": "Cementing issue",
    "fishing": "Fishing operation",
}

# Look-ahead window (m) used by alerts and by the model's label horizon.
LOOKAHEAD_M = 50.0
ALERT_LOOKAHEAD_M = 250.0
DEFAULT_RADIUS_KM = 6.0

# Stratigraphic lexicon used to canonicalise formation names (OCR drops spaces / mangles letters).
# Extend this list when onboarding a new basin; unknown names pass through unchanged.
FORMATION_LEXICON = [
    "Alluvium", "Namsang", "Girujan Clay", "Tipam Sandstone", "Barail Coal Shale", "Barail Sandstone",
    "Kopili Shale", "Sylhet Limestone", "Langpar-Lakadong", "Therria",
]
