# Deploying: frontend on Vercel, backend on Render

The backend is a stateful FastAPI process (SQLite file, in-memory live-monitor sessions, a long-lived SSE
stream) — it needs a real persistent process, not Vercel's serverless functions. So the split is:

- **Frontend** (`frontend/`) → **Vercel** — a static build, no issues.
- **Backend** (`backend/`) → **Render** — runs `uvicorn` exactly as it does locally, free tier included.

Both platforms deploy from a Git repository, so this repo needs to be on GitHub (or GitLab/Bitbucket) first.

## 0. Push this repo to GitHub

```powershell
git init
git add .
git commit -m "Initial commit"
```
Then create an empty repo on GitHub (via the website, or `gh repo create` if you have the GitHub CLI signed
in) and push:
```powershell
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```
`data/` is gitignored on purpose — the backend regenerates it during the Render build (see below), so nothing
large needs to be committed.

## 1. Backend on Render — done

Deployed at **https://nwis-backend-hz80.onrender.com** (Blueprint `nwis-sih26121`, connected via the public
repo URL rather than the GitHub App, so there's no OAuth grant on file — see the note on redeploys below).

1. `render.yaml` at the repo root drives the whole thing: build command, start command, Python version.
2. The build step runs `build_dataset.py`, `ingest_all.py`, and `train_model.py` in sequence — this
   regenerates the synthetic data, ingests it (including OCR on the scanned samples), and trains the risk
   model, all from scratch. First build took ~4 minutes. Every redeploy starts clean.
3. **Free-tier spin-down:** a free Render web service spins down after 15 minutes of inactivity and spins
   back up on the next request (~30–60s cold start). Because the demo data is baked in during the *build*
   step rather than written at runtime, spinning back up always returns to the same clean starting state —
   fine for a repeatable demo, but anything uploaded live through the dashboard (a new PDF, alert feedback)
   won't survive a spin-down. **`.github/workflows/keepalive.yml`** pings `/api/health` every 5 minutes using
   GitHub Actions' own free minutes (no third-party account or API key needed) specifically so it never has
   the chance to go idle long enough to sleep — this starts running automatically once you push this repo.
4. **Redeploying:** this Blueprint was connected via the *public repository URL*, not the GitHub App, so
   **auto-deploy on push is off** — the free-tier "no repos found" GitHub connection step was skipped
   deliberately to avoid an OAuth authorization click that wasn't yours to approve sight-unseen. To ship a
   backend change, push to GitHub as usual, then in the Render dashboard open `nwis-backend` → **Manual
   Deploy** → **Deploy latest commit**. (You can connect the GitHub App later, under the service's Settings,
   if you'd rather have it auto-deploy — that's the point where Render will ask to authorize repo access.)

## 2. Frontend on Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New** → **Project**, import the same GitHub repo.
2. Set **Root Directory** to `frontend` (this repo is a monorepo; `frontend/vercel.json` handles the build
   command and output directory once the root is set correctly).
3. Before the first build, add an environment variable: **`VITE_API_BASE`** = your Render URL from step 1
   (e.g. `https://nwis-backend.onrender.com`, no trailing slash). This gets baked into the build at compile
   time — Vite environment variables aren't read at runtime, so if you change the backend URL later you need
   to redeploy the frontend, not just restart it.
4. Deploy. Vercel will give you a URL like `https://your-app.vercel.app`.

## 3. Point the backend's CORS at the frontend

Back in the Render dashboard, open the `nwis-backend` service → **Environment**, and set:
```
NWIS_CORS_ORIGINS = https://your-app.vercel.app
```
(comma-separate multiple origins if you also want to allow a Vercel preview URL or localhost). Save — Render
redeploys automatically. Until you set this, the API defaults to allowing any origin (there's no
authentication or cookie-based session on this API, so that's low-risk for a demo, but locking it to your
actual frontend is the tidier choice once you know the URL).

## Verifying it worked

- `https://nwis-backend-hz80.onrender.com/api/health` should return `{"ok": true, ...}` — confirmed working.
- Open the Vercel URL, go to **Live monitor**, and start the replay — if alerts and charts update live, the
  SSE connection to Render is working end to end.
- If the Live monitor looks stuck: open the browser console and check for CORS errors (means step 3 needs
  fixing) or a failed `EventSource` connection (means `VITE_API_BASE` wasn't set before the Vercel build, or
  the Render service is still cold-starting — wait ~60s and retry).

## Updating either side later

- Backend changes: push to GitHub, then trigger **Manual Deploy** on `nwis-backend` in the Render dashboard
  (see the redeploy note in step 1 — auto-deploy isn't wired up for this connection method).
- Frontend changes: push to GitHub; Vercel redeploys automatically. If you only changed `VITE_API_BASE`,
  trigger a redeploy manually from the Vercel dashboard (env var changes don't trigger one on their own).
