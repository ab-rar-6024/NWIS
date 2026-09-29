# Serves the API and the built dashboard on http://127.0.0.1:8000
Set-Location (Join-Path $PSScriptRoot 'backend')
..\.venv\Scripts\python -m uvicorn nwis.api:app --host 127.0.0.1 --port 8000
