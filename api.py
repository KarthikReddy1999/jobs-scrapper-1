"""FastAPI wrapper for Jobright scraper — deployed on Railway (port 7860)."""
import asyncio
import logging
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobright_site.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
import django
django.setup()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Header, HTTPException

from jobright.models import JobrightJob, JobrightScraperState
from jobright.scraper import is_scraper_running, start_scraper, stop_scraper
from supabase_push import push_jobs_to_supabase

app = FastAPI(title="Jobright Scraper", version="1.0.0")
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)

API_SECRET = os.environ["WEBHOOK_SECRET"]


async def _push_when_done() -> None:
    """Poll until the scraper subprocess finishes, then push all jobs to Supabase."""
    while is_scraper_running():
        await asyncio.sleep(30)
    state = JobrightScraperState.get_singleton()
    logger.info("Scraper finished — %d jobs saved — pushing to Supabase", state.jobs_saved)
    try:
        push_jobs_to_supabase()
    except Exception as exc:
        logger.error("Supabase push failed: %s", exc)


@app.on_event("startup")
async def start_scheduler() -> None:
    scheduler.add_job(
        _scheduled_scrape,
        CronTrigger(hour="1,7,13,19", minute="0"),
        id="jobright_scrape",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduler started — Jobright scrape at 01,07,13,19 UTC daily")


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)


async def _scheduled_scrape() -> None:
    if is_scraper_running():
        logger.info("Scheduled scrape skipped — already running")
        return
    ok, msg = start_scraper(resume=False)
    if ok:
        asyncio.create_task(_push_when_done())
    logger.info("Scheduled scrape: %s", msg)


@app.get("/")
def health():
    state = JobrightScraperState.get_singleton()
    return {
        "status": "running",
        "service": "jobright-scraper",
        "scraper_status": state.status,
        "jobs_saved": state.jobs_saved,
    }


@app.post("/scrape/all")
async def trigger_scrape(x_api_key: str = Header(None)):
    """Start a fresh scrape run (GitHub Actions cron calls this every hour)."""
    _check_auth(x_api_key)
    if is_scraper_running():
        return {"status": "already_running"}
    ok, msg = start_scraper(resume=False)
    if ok:
        asyncio.create_task(_push_when_done())
    return {"status": "started" if ok else "error", "message": msg}


@app.post("/scrape/stop")
async def stop(x_api_key: str = Header(None)):
    _check_auth(x_api_key)
    ok, msg = stop_scraper()
    return {"status": "stopped" if ok else "error", "message": msg}


@app.get("/status")
def status(x_api_key: str = Header(None)):
    _check_auth(x_api_key)
    state = JobrightScraperState.get_singleton()
    return {
        "scraper_status": state.status,
        "current_keyword": state.current_keyword,
        "keyword_index": state.keyword_index,
        "jobs_saved": state.jobs_saved,
        "jobs_skipped": state.jobs_skipped,
        "running": is_scraper_running(),
    }


def _check_auth(key: str | None) -> None:
    if key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
