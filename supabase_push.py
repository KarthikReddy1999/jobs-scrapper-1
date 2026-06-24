"""Read all JobrightJob records from Django SQLite and upsert into Supabase."""
import logging
import os

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def _get_client():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def push_jobs_to_supabase() -> dict:
    from jobright.models import JobrightJob

    jobs = list(JobrightJob.objects.all())
    if not jobs:
        logger.info("No Jobright jobs to push")
        return {"inserted": 0, "failed": 0}

    client = _get_client()

    BLOCKED_DOMAINS = ("jobright.ai", "jobright.com", "simplify.jobs", "linkedin.com")

    rows = [
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "external_apply_link": job.apply_url,
            "is_published": True,
            "is_reviewing": False,
            "is_archived": False,
            "ingested_via": "jobright",
            "is_direct_apply": True,
            "description": job.description or None,
            "description_enriched": False,
            "description_source": "original",
        }
        for job in jobs
        if not any(d in (job.apply_url or "") for d in BLOCKED_DOMAINS)
    ]

    try:
        response = client.table("jobs").upsert(rows, on_conflict="external_apply_link", ignore_duplicates=True).execute()
        inserted = len(response.data) if response.data else 0
        failed = 0
    except Exception as exc:
        logger.error("Bulk push failed: %s", exc)
        inserted = 0
        failed = len(rows)

    logger.info("Supabase push done: %d inserted, %d failed", inserted, failed)
    return {"inserted": inserted, "failed": failed}
