# One-shot setup: venv, dependencies, synthetic data, ingestion (with OCR), model training, frontend build.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --quiet --upgrade pip
.\.venv\Scripts\python -m pip install --quiet -r backend\requirements.txt

Push-Location backend
..\.venv\Scripts\python scripts\build_dataset.py
..\.venv\Scripts\python scripts\ingest_all.py
..\.venv\Scripts\python scripts\train_model.py
Pop-Location

Push-Location frontend
npm install --no-audit --no-fund
npm run build
Pop-Location

Write-Host "`nSetup complete. Run ./start.ps1 and open http://127.0.0.1:8000"
