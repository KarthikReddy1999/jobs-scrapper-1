"""Read all JobrightJob records from Django SQLite and upsert into Supabase."""
import logging
import os

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dyguncqqjzuyiwxhgwcw.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
EMAIL = os.environ.get("EMAIL", "")
PASSWORD = os.environ.get("PASSWORD", "")


def _get_client():
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.sign_in_with_password({"email": EMAIL, "password": PASSWORD})
    return client


def push_jobs_to_supabase() -> dict:
    from jobright.models import JobrightJob

    jobs = list(JobrightJob.objects.all())
    if not jobs:
        logger.info("No Jobright jobs to push")
        return {"inserted": 0, "failed": 0}

    client = _get_client()
    inserted = 0
    failed = 0

    for job in jobs:
        row = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "external_apply_link": job.apply_url,
            "source": job.source or "Jobright",
            "employment_type": "Full Time",
            "is_published": True,
            "is_reviewing": False,
            "is_archived": False,
        }
        try:
            client.table("jobs").upsert(row, on_conflict="external_apply_link").execute()
            inserted += 1
        except Exception as exc:
            logger.error("Failed to push '%s @ %s': %s", job.title, job.company, exc)
            failed += 1

    logger.info("Supabase push done: %d inserted, %d failed", inserted, failed)
    return {"inserted": inserted, "failed": failed}
