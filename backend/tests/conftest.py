"""Test fixtures. The app is pointed at a temporary COPY of the built database so tests never touch real data."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

_tmp = Path(tempfile.mkdtemp(prefix="nwis_test_"))
_real_db = ROOT / "data" / "nwis.db"
if _real_db.exists():
    shutil.copy(_real_db, _tmp / "nwis.db")
os.environ["NWIS_DB"] = str(_tmp / "nwis.db")
os.environ["NWIS_UPLOAD_DIR"] = str(_tmp / "uploads")

import pytest  # noqa: E402

DATA = ROOT / "data"
needs_data = pytest.mark.skipif(not _real_db.exists() or not (DATA / "raw").exists(),
                                reason="run scripts/build_dataset.py, ingest_all.py and train_model.py first")


@pytest.fixture(scope="session")
def tmp_dir():
    return _tmp
