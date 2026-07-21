# Website Audit Tool

A local web app that crawls a site (same domain, breadth-first) and reports on:

- **SEO** — titles, meta descriptions, heading structure, alt text, canonical tags, Open Graph tags, robots.txt, sitemap.xml
- **Performance** — response time, HTML payload size, compression, caching headers, render-blocking scripts, image dimensions, script count
- **Design & Polish** — responsive viewport, favicon, custom typography, color palette signals, motion/interactivity, visual density

These are heuristic, request-level checks (no headless browser), so treat scores as *directional* — a prompt for where to look closer, not a lab-grade Lighthouse report.

## Setup (local)

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** and enter a URL.

## How it works

- `audit/crawler.py` — breadth-first crawl, same-domain only, configurable page limit and depth
- `audit/seo_checks.py`, `performance_checks.py`, `design_checks.py` — one function per category, each returns pass/warn/fail issues
- `audit/scoring.py` — turns issue lists into 0–100 scores and letter grades
- `app.py` — Flask routes: `/` (form), `/audit` (runs the crawl + checks, renders the report)
- `templates/`, `static/style.css` — the report UI

## Deploying it (public URL)

The app is ready to deploy as-is — it reads `PORT` from the environment, runs via `gunicorn`, and defaults `debug` to off.

### Render (free tier, easiest)

1. Push this folder to a GitHub repo.
2. In Render: **New → Blueprint**, point it at the repo. It'll read `render.yaml` and configure everything automatically.
   *(No `render.yaml`? New → Web Service → build command `pip install -r requirements.txt`, start command `gunicorn app:app --timeout 60 --workers 2`.)*
3. Deploy. You'll get a `https://your-app.onrender.com` URL.

### Railway / Fly.io / Heroku-style platforms

Same idea — they all read the included `Procfile` (`web: gunicorn app:app --timeout 60 --workers 2`). Point the platform at the repo and deploy.

### Before you make it public — security notes

Once this has a public URL, it's effectively an open URL-fetcher anyone can point at any address, so a few protections are already built in:

- **SSRF guard** (`audit/safety.py`) — resolves every target hostname and rejects private, loopback, link-local, and reserved IP ranges (so it can't be used to probe your own internal network or cloud metadata endpoints). Known gap: this doesn't fully defend against DNS rebinding — a hostname that resolves safely at check-time but is repointed to an internal IP by connection time. For most use this is a reasonable bar; for stricter protection, block private IP ranges at the network/firewall level too.
- **Rate limiting** — `/audit` is capped at 6 requests/minute per IP via `flask-limiter`. It uses in-memory storage by default, which is fine for a single instance but resets on restart and doesn't share state across multiple instances — swap in a Redis backend (`flask-limiter` supports this via a `storage_uri`) if you scale beyond one dyno/instance.
- **Bounded crawl** — page count (≤30), depth (≤4), link checks (≤60), and a 25-second wall-clock crawl budget all cap how much work a single request can trigger, so a request can't run indefinitely.
- **Not included**: authentication. Anyone with the URL can run audits. Add a login wall (e.g. `flask-login`, or your host's built-in access control) if that matters for your use case.



Each check module returns a flat list of `{id, label, status, detail, page}` dicts, so adding a new check is just adding another function call in `app.py` and appending its issues to the right list. Ideas:

- Swap in a headless browser (Playwright) for real Lighthouse-style performance metrics
- Add a broken-link checker (HEAD request on every internal/external link)
- Export the report as PDF or JSON via a new route
- Add auth/rate-limiting if you deploy this beyond localhost
