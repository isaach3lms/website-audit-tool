# Website Audit Tool

A web app that crawls a church site (same domain, breadth-first) and scores it in four areas. Each area has sub-sections, and every sub-section lists its findings.

1. **First-Time Visitor and Clarity**: the 5-second test (name, city, denomination, service times, next step), practical logistics (address, map link, parking, entrances, accessibility), family and kids info (ages, check-in, safety), and plain language (church jargon).
2. **Essential Content and Messaging**: service details (Sunday, midweek, special), What to Expect and Plan a Visit, beliefs, mission and leadership, and sermon media (links load, under 3 seconds, recent).
3. **User Experience and Design**: mobile-first navigation and giving, visual and brand consistency across pages (logo, favicon, stylesheets, real photos), and links, forms and embeds (broken links, dead-end forms, broken embeds, outdated event dates).
4. **Technical Health and Local SEO**: Google Business Profile signals, search optimization (unique titles, local keywords, URL structure), site speed and accessibility.

**Top priorities** is an executive summary of the 5 highest-impact findings across all four areas.

These are request-level checks (no headless browser), so treat scores as directional. Speed, accessibility and mobile usability use real Google PageSpeed data when a key is set (see below).

## How scoring works

- Each check is built from components. All found = pass, some = notice with partial credit, none = notice with 0 points. Visitor-facing checks never hard-fail.
- Sub-section score = mean of its checks. Area score = mean of its sub-sections. Overall = mean of the four areas.
- Site-level checks are always listed, passes included. Per-page findings are merged ("appears on N pages"). Link findings are never merged.
- The review reads all crawled pages, and the crawler moves guest-facing links (visit, kids, beliefs, staff, contact) to the front of the queue. A page outside the crawl will look missing.
- Google Business Profile is judged from the site only (GBP link, Church or LocalBusiness schema, consistent phone). Claimed and verified status must be confirmed at business.google.com.

## Google PageSpeed (optional, free)

1. In Google Cloud Console, create or pick a project and enable the **PageSpeed Insights API**.
2. Create an API key (Credentials, Create credentials, API key).
3. Set `PAGESPEED_API_KEY` locally (`export PAGESPEED_API_KEY=...`) and as an environment variable on Render.

Without a key the report still runs and shows a note that speed data was not collected. The PageSpeed call runs in the background while the crawl runs, with a 45 second wait cap. Gunicorn timeout is 120 seconds in `Procfile` and `render.yaml`.

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


Run the tests (no network, no extra dependencies):

```bash
python -m unittest discover -s tests -v
```

## How it works

- `audit/crawler.py` — breadth-first crawl, same-domain only, configurable page limit and depth
- `audit/seo_checks.py`, `performance_checks.py`, `design_checks.py`, `accessibility_checks.py`: per-page checks
- `audit/guest_experience.py`, `sermon_media.py`, `ux_checks.py`, `local_seo.py`, `pagespeed.py`: site-level checks
- `audit/structure.py` (areas and sub-sections) and `audit/areas.py` (tagging, merging, scoring)
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
