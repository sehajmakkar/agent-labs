# Deploying the lab for companies to see

**Recommended: the read-only demo** (D-057). Vercel or Netlify serve the UI plus every real run,
fork, diff, blame and eval as JSON files. There is no backend. Visitors click through everything,
and the fork dialog offers three forks run ahead of time with their real results. It costs $0,
never sleeps, keeps no API key on any server, and can't fail while a founder is looking.

```
 visitor ──► Vercel / Netlify: the UI + ui/static/data/*.json (exported by `lab export-static`)
```

The **live backend** (further down) is still there if you want visitors to start real forks.

---

## Read-only demo (recommended)

### 1. Export the data (on your machine)

```bash
uv run lab export-static        # every page's data, packed into ui/static-data.tar.gz (one file)
(cd ui && npm run build:static && cd dist && python3 -m http.server 4173)   # optional local check
git add ui/static-data.tar.gz deploy/presets.json && git commit -m "Demo data" && git push
```

Re-run `lab export-static` and push whenever you want the demo to show newer runs. It refuses to
write anything that looks like an API key. Git keeps only the archive; the unpacked folder
(`ui/static/`) is ignored, and the build unpacks the archive itself. The same data always packs to
the same bytes, so an export with nothing new shows no change.

**Preset forks:** `deploy/presets.json` lists forks the fork dialog offers. To add one, run it
(`uv run lab fork <run> --step 3 --append-prompt "…" -n 5`), add its ID with a title and a
one-line description of the change, and export again.

### 2. Deploy

- **Vercel:** New Project → import the repo → **Root Directory** `ui` → Deploy. `ui/vercel.json`
  already says `npm run build:static`.
- **Netlify:** Add new site → import the repo → **Base directory** `ui` → Deploy. `ui/netlify.toml`
  already says `npm run build:static`.

No environment variables are needed.

### 3. Check before you send the link

- [ ] The nav shows "read-only demo", and the Overview shows real numbers (95% · 5/5 vs 0/5 · 92% · $0).
- [ ] "Try a fork yourself →" opens the fork dialog with the three presets; each opens its fork page.
- [ ] A run page opens, the tree is clickable, and "↺ See its replay" appears where a replay exists.
- [ ] The Blame accuracy page and a blame page load.

Then put the URL into `README.md` (`DEMO_URL`) and your emails.

---

## Live backend (optional)

Use this only if visitors should start real forks and blames. It needs a container host and your
Gemini key on it.

```
 visitor ──► Vercel / Netlify (the UI) ──/api/*──► backend container (Fly, Render or Railway)
                                                   FastAPI + worker + SQLite on /data
```

**Vercel and Netlify** serve the UI and pass `/api` calls through to the backend. The backend can't
run on them: forks and blames take minutes, need a worker running all the time, and write to a
database, while serverless functions time out in seconds and lose their files.

The backend URL on its own also works: it serves the UI too.

For the UI in front of it, replace the static configs: in `ui/vercel.json` set `"buildCommand":
"npm run build"` and add `"rewrites": [{ "source": "/api/:path*", "destination":
"https://YOUR-BACKEND-URL/api/:path*" }]`; in `ui/netlify.toml` set `command = "npm run build"` and
add a `[[redirects]]` from `/api/*` to `https://YOUR-BACKEND-URL/api/:splat` with `status = 200`.

### 0. Prepare the demo data (on your machine)

```bash
uv run lab snapshot          # → deploy/seed.db.gz: your runs, evals, forks, blames (scanned for keys)
git add deploy/seed.db.gz && git commit -m "Demo data snapshot" && git push
```

On its first boot, the backend creates its database from this snapshot (`deploy/start.sh`).
Re-run `lab snapshot` whenever you want the hosted demo to show newer runs.

### 1. Deploy the backend: choose one

Environment variables (the same on every host):

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` | your key. **Set it as a secret, never in a file.** Without it the demo is read-only plus replay. |
| `AGENTLAB_DEMO_KEY` | a password you choose, for forks and blames |
| `AGENTLAB_JOBS_PER_HOUR` | e.g. `6`: the most forks and blames per hour, across all visitors |
| `AGENTLAB_RPM` | `15` on a free Gemini key; higher on a paid one |

The Dockerfile already sets `AGENTLAB_PUBLIC=1`, `AGENTLAB_DB=/data/lab.db` and `PORT=8000`.

#### Option A: Fly.io (a persistent disk for little money)

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

#### Option B: Render (all in the dashboard)

New → **Web Service** → connect the GitHub repo → Runtime **Docker**. Add the environment
variables above. Optionally add a **Disk** mounted at `/data`, so forks made by visitors survive
restarts (this needs a paid instance). On the free instance the service sleeps when idle, so the
first visit can take a while to wake it.

#### Option C: Railway

New project → **Deploy from GitHub repo** (it finds the Dockerfile). Add a **Volume** mounted at
`/data`, and the variables above.

> Without a persistent disk, every restart goes back to the snapshot. That's fine for a demo:
> visitors' forks just aren't kept.

Check it: open `https://YOUR-BACKEND/api/config`. It should say `"public": true`.

### 2. Put the UI on Vercel or Netlify (optional, for a nicer URL)

First switch `ui/vercel.json` (or `ui/netlify.toml`) to the live build with the `/api` rewrite, as
above, using the backend's host, for example `agent-lab-demo.fly.dev`. Commit and push.

- **Vercel:** New Project → import the repo → **Root Directory** `ui` → Deploy. The rewrite in
`vercel.json` sends `/api/*` to the backend.
- **Netlify:** Add new site → import the repo → **Base directory** `ui` → Deploy. `netlify.toml`
holds the build command and the `/api/*` proxy.

### 3. Check before you send the link

- [ ] The Overview page shows real numbers (95% · 5/5 vs 0/5 · 92% · $0).
- [ ] A run page opens; the tree is clickable; ↺ Replay works without a key.
- [ ] Blame and Fork are greyed out, with "enter a demo key" as the tooltip.
- [ ] Enter the demo key (🔑 in the top right); a fork with N=3 queues, runs and finishes.
- [ ] `https://YOUR-BACKEND/api/store/get_run` returns 403 (the store RPC is closed).

## Safety notes (live backend)

- The key lives only in the host's secrets. `deploy/seed.db.gz` is scanned for anything that
looks like a Google API key before it's written.
- Set a **budget alert** on your Google AI account. With `AGENTLAB_JOBS_PER_HOUR=6` and N ≤ 3, an
hour of demo use is roughly 6 jobs × about 30 calls, a few cents on Flash-Lite.
- Change `AGENTLAB_DEMO_KEY` after a round of interviews.
- Pricing for Fly, Render and Railway changes; check their pages. A small instance plus a 1 GB
disk is typically a few dollars a month.
