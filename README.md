# Jobright USA Job Scraper

Standalone Django app — **port 8001**, own `db.sqlite3`, no shared code with Simplify or MigrateMate.

| | Simplify | Jobright | MigrateMate |
|---|----------|----------|-------------|
| Folder | `../simplify/` | `Jobright_new/` | `../MigrateMate_new/` |
| Port | **8000** | **8001** | **8002** |

See `../PROJECTS.md` for running all three.

## What it does

- Scrapes [jobright.ai](https://jobright.ai) via Playwright (`/_next/data/.../jobs/{slug}.json` + detail pages).
- **~144 keywords** + up to **3 slug variants** per keyword (e.g. engineer / developer).
- Filters: **USA**, **last 24 hours**, **valid live ATS apply URL** (company career / Greenhouse / Lever / Workday — not Jobright portal, not LinkedIn).
- **Live link check** — dead Lever/Greenhouse 404 pages are not saved.
- Typical yield: **300+ saved jobs** per full run (many listings scanned; most skipped without a public ATS link).

Jobright’s public API exposes about **16 jobs per search slug**; variants and extra keywords increase unique listings scanned (~25–35 per keyword).

## Setup

```powershell
cd Jobright_new
pip install -r requirements.txt
playwright install chromium
python manage.py migrate
python manage.py runserver 8001 --noreload
```

Or double-click `start_server.bat`.

Dashboard: **http://127.0.0.1:8001/**

## Dashboard

| Button | Action |
|--------|--------|
| **Start** | Clear all jobs, reset state, scrape from keyword 1 |
| **Resume** | Continue from last keyword (no duplicates) |
| **Stop** | Save progress and stop background worker |
| **Clear All Jobs** | Delete jobs only (scraper must be stopped) |

Use **`--noreload`** while scraping so Django reload does not kill the browser worker.

## Management commands

```powershell
python manage.py run_scraper
python manage.py run_scraper --resume
python manage.py purge_invalid_apply_urls   # invalid ATS + dead/404 apply URLs
```

## Configuration (`jobright_site/settings.py`)

- `KEYWORDS` — search titles
- `JOBRIGHT_USE_SLUG_VARIANTS` / `JOBRIGHT_MAX_SLUGS_PER_KEYWORD` — more unique listings per keyword
- `ALLOWED_ATS` — accepted apply hosts

## Logs

- `logs/scraper.log`, `logs/worker.log` — not committed (see `.gitignore`)
