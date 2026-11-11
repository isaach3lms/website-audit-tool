# Website Audit Tool

A local web app that crawls a site (same domain, breadth-first) and reports on:

- **SEO** — titles, meta descriptions, heading structure, alt text, canonical tags, Open Graph tags, robots.txt, sitemap.xml
- **Performance** — response time, HTML payload size, compression, caching headers, render-blocking scripts, image dimensions, script count
- **Design & Polish** — responsive viewport, favicon, custom typography, color palette signals, motion/interactivity, visual density
- **Links** — every internal/external link found across crawled pages, checked for broken (4xx/5xx) or unreachable targets
- **Ministry Essentials** — church/ministry-specific signals a generic tool wouldn't check: giving/donate link, service times, physical location, sermon archive, staff/leadership bios, analytics tracking present
- **Guest Experience Review** - what a nervous first-time visitor needs before walking in, in three groups of 11 checks:
  - *Core Practical Details*: service times on the homepage with arrival guidance, location with a map link and parking/entrance notes, service length
  - *What to Expect*: what to wear, worship vibe and music style (and how lyrics are shown), a promise guests will not be put on the spot, kids and youth (programs, check-in and safety, class vs. stay in service)
  - *Community and Culture*: real vs. stock photos, plain language (unexplained church jargon), a Plan Your Visit / I'm New page, statement of faith and pastor introduction
- **Top priorities** — an executive summary of the 5 highest-impact findings across every category, for a client-facing deliverable

These are heuristic, request-level checks (no headless browser), so treat scores as *directional* — a prompt for where to look closer, not a lab-grade Lighthouse report.

## Setup (local)

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** and enter a URL.

## Emailing a report to a prospect

The report page has an "Email to prospect" button that sends the PDF as an attachment via SMTP. Configure it with environment variables (set these on Render under Settings → Environment, or in your local shell for testing):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@yourdomain.com
SMTP_PASSWORD=your-app-password        # NOT your regular account password — generate an app password
SMTP_FROM=you@yourdomain.com            # optional, defaults to SMTP_USER
FROM_NAME=Between Sundays               # optional
EMAIL_ACCESS_CODE=pick-a-passphrase     # required — see note below
```

For Gmail specifically: enable 2-factor auth on the sending account, then generate an **App Password** (myaccount.google.com/apppasswords) — use that as `SMTP_PASSWORD`, not your normal login password.

**Why `EMAIL_ACCESS_CODE` exists:** this app has no login/auth (see Security notes below), and an open "email anyone a PDF" endpoint on a public URL is exactly the kind of thing spammers scan for. The email form won't send anything unless the person using it enters this code, which only you know. Without `EMAIL_ACCESS_CODE` set, the email feature returns a clear "not configured" message instead of silently failing.


## Guest Experience Review: how it scores

- Each check is built from components (for example the kids check needs programs, check-in/safety details, and how kids are placed). All found = pass, some = notice, none = notice with 0 points. It never hard-fails.
- Partial credit flows into the score through an optional `points` value on each issue (`audit/scoring.py`). Other categories are unchanged.
- The review reads text, links, and image names across **all crawled pages**, so a Plan Your Visit page counts. The crawler now moves guest-facing links (visit, kids, beliefs, staff, worship, contact...) to the front of the queue so a small crawl still reaches them. If a page is outside the crawl it will look missing.
- Photo authenticity cannot be judged from code. The check flags stock-library markers in image URLs and names, counts content photos, and looks for descriptive alt text. Confirm by eye.
- The score is included in the overall score, shown in the on-screen report and in the PDF (every check, passes included).
- Logic lives in `audit/guest_experience.py`; tune the regex lists at the top of each check there.

Run the tests (no network, no extra dependencies):

```bash
python -m unittest discover -s tests -v
```

## How it works

- `audit/crawler.py` — breadth-first crawl, same-domain only, configurable page limit and depth
- `audit/seo_checks.py`, `performance_checks.py`, `design_checks.py`, `ministry_checks.py`, `guest_experience.py` — one module per category, each returns pass/warn/fail issues
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
