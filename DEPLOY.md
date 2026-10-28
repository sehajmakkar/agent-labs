# Deploying the lab for companies to see

The hosted lab is **live**: visitors browse real runs, evals, forks, diffs and blames, and can
press **↺ Replay** (free, offline). **Fork** and **Blame** call Gemini with your key, so they
need a **demo key** that you give out (or type in yourself on a call), and they are capped per
hour.

```
 visitor ──► Vercel / Netlify (the UI, your nice URL) ──/api/*──► backend container (Fly, Render or Railway)
                                                                 FastAPI + worker + SQLite on /data
```

**Vercel and Netlify** serve the UI and pass `/api` calls through to the backend. The backend can't
run on them: forks and blames take minutes, need a worker running all the time, and write to a
database, while serverless functions time out in seconds and lose their files.

The backend URL on its own also works: it serves the UI too. Vercel or Netlify only add a nicer
address and a CDN.

---

## 0. Prepare the demo data (on your machine)

```bash
uv run lab snapshot          # → deploy/seed.db.gz: your runs, evals, forks, blames (scanned for keys)
git add deploy/seed.db.gz && git commit -m "Demo data snapshot" && git push
```

On its first boot, the backend creates its database from this snapshot (`deploy/start.sh`).
Re-run `lab snapshot` whenever you want the hosted demo to show newer runs.

## 1. Deploy the backend: choose one

Environment variables (the same on every host):

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your key. **Set it as a secret, never in a file.** Without it the demo is read-only plus replay. |
| `AGENTLAB_DEMO_KEY` | a password you choose, for forks and blames |
| `AGENTLAB_JOBS_PER_HOUR` | e.g. `6`: the most forks and blames per hour, across all visitors |
| `AGENTLAB_RPM` | `15` on a free Gemini key; higher on a paid one |

The Dockerfile already sets `AGENTLAB_PUBLIC=1`, `AGENTLAB_DB=/data/lab.db` and `PORT=8000`.

### Option A: Fly.io (a persistent disk for little money)

```bash
brew install flyctl && fly auth login
fly launch --no-deploy --copy-config=false --name agent-lab-demo   # uses the Dockerfile
fly volumes create data --size 1
```

Add this to the generated `fly.toml`:

```toml
[mounts]
  source = "data"
  destination = "/data"
```

Then:

```bash
fly secrets set GEMINI_API_KEY=... AGENTLAB_DEMO_KEY=... AGENTLAB_JOBS_PER_HOUR=6
fly deploy
```

The URL is `https://agent-lab-demo.fly.dev`.

### Option B: Render (all in the dashboard)

New → **Web Service** → connect the GitHub repo → Runtime **Docker**. Add the environment
variables above. Optionally add a **Disk** mounted at `/data`, so forks made by visitors survive
restarts (this needs a paid instance). On the free instance the service sleeps when idle, so the
first visit can take a while to wake it.

### Option C: Railway

New project → **Deploy from GitHub repo** (it finds the Dockerfile). Add a **Volume** mounted at
`/data`, and the variables above.

> Without a persistent disk, every restart goes back to the snapshot. That's fine for a demo:
> visitors' forks just aren't kept.

Check it: open `https://YOUR-BACKEND/api/config`. It should say `"public": true`.

## 2. Put the UI on Vercel or Netlify (optional, for a nicer URL)

First edit `ui/vercel.json` (or `ui/netlify.toml`) and replace `YOUR-BACKEND-URL` with the
backend's host, for example `agent-lab-demo.fly.dev`. Commit and push.

- **Vercel:** New Project → import the repo → **Root Directory** `ui` → Deploy. The rewrite in
`vercel.json` sends `/api/*` to the backend.
- **Netlify:** Add new site → import the repo → **Base directory** `ui` → Deploy. `netlify.toml`
holds the build command and the `/api/*` proxy.

## 3. Check before you send the link

- [ ] The Overview page shows real numbers (95% · 5/5 vs 0/5 · 92% · $0).
- [ ] A run page opens; the tree is clickable; ↺ Replay works without a key.
- [ ] Blame and Fork are greyed out, with "enter a demo key" as the tooltip.
- [ ] Enter the demo key (🔑 in the top right); a fork with N=3 queues, runs and finishes.
- [ ] `https://YOUR-BACKEND/api/store/get_run` returns 403 (the store RPC is closed).

## Safety notes

- The key lives only in the host's secrets. `deploy/seed.db.gz` is scanned for anything that
looks like a Google API key before it's written.
- Set a **budget alert** on your Google AI account. With `AGENTLAB_JOBS_PER_HOUR=6` and N ≤ 3, an
hour of demo use is roughly 6 jobs × about 30 calls, a few cents on Flash-Lite.
- Change `AGENTLAB_DEMO_KEY` after a round of interviews.
- Pricing for Fly, Render and Railway changes; check their pages. A small instance plus a 1 GB
disk is typically a few dollars a month.
