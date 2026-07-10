"""Read all JobrightJob records from Django SQLite and upsert into Supabase."""
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
_LOGO_DEV_KEY = os.getenv("LOGO_DEV_PUBLIC_KEY") or None


def _logo_dev_url(company: str) -> str | None:
    if not _LOGO_DEV_KEY:
        return None
    domain = re.sub(r"[^a-z0-9]", "", company.lower()) + ".com"
    return f"https://img.logo.dev/{domain}?token={_LOGO_DEV_KEY}"

_ENRICH_URL = f"{SUPABASE_URL}/functions/v1/enrich-job-description"
_ENRICH_BATCH = 25
_ENRICH_LIMIT = 500  # max jobs to enrich per push run

BLOCKED_DOMAINS = ("jobright.ai", "jobright.com", "simplify.jobs", "linkedin.com")

EXCLUDED_TITLE_WORDS = {
    "senior", "staff", "principal", "lead", "manager", "director",
    "clearance", "secret", "top secret", "ts/sci", "dod", "defense",
    "intelligence", "classified",
    "technician", "rope access", "instrument operator",
}


def _parse_visa_signals(description: str) -> dict:
    if not description:
        return {}
    lower = description.lower()
    opt_positive = any(p in lower for p in [
        "opt accepted", "opt students", "opt eligible", "f-1 opt", "f1 opt",
        "accepts opt", "welcome opt", "open to opt", "opt welcome",
        "optional practical training", "opt candidates", "cpt/opt",
        "opt/cpt", "f1 students welcome", "f-1 students",
    ])
    stem_opt = any(p in lower for p in [
        "stem opt", "stem extension", "24-month opt", "24 month opt",
        "stem designated", "stem degree",
    ])
    no_sponsorship = any(p in lower for p in [
        "no sponsorship", "not sponsor", "unable to sponsor",
        "cannot sponsor", "will not sponsor", "does not sponsor",
        "sponsorship not available", "no visa sponsor",
        "not provide sponsorship", "not able to sponsor",
        "must be authorized to work in the u", "must be legally authorized",
        "must have authorization to work", "must be eligible to work",
        "citizen or permanent resident", "us citizen or green card",
        "not support visa", "not offer sponsorship",
    ])
    if no_sponsorship:
        return {"opt_accepting": False, "stem_opt_eligible": False, "no_sponsorship": True, "visa_confidence": "high"}
    if opt_positive or stem_opt:
        return {"opt_accepting": opt_positive, "stem_opt_eligible": stem_opt, "no_sponsorship": False, "visa_confidence": "high"}
    return {"opt_accepting": False, "stem_opt_eligible": False, "no_sponsorship": False, "visa_confidence": "low"}


def _is_excluded_title(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in EXCLUDED_TITLE_WORDS)


def _get_client():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _enrich_jobs(job_ids: list) -> None:
    if not job_ids:
        return
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    batches = [job_ids[i:i + _ENRICH_BATCH] for i in range(0, len(job_ids), _ENRICH_BATCH)]
    for batch in batches:
        try:
            r = requests.post(_ENRICH_URL, headers=headers, json={"job_ids": batch}, timeout=60)
            logger.info("Enrichment batch %d jobs: HTTP %d", len(batch), r.status_code)
        except Exception as exc:
            logger.error("Enrichment batch failed: %s", exc)


def push_jobs_to_supabase() -> dict:
    from jobright.models import JobrightJob

    jobs = list(JobrightJob.objects.all())
    if not jobs:
        logger.info("No Jobright jobs to push")
        return {"inserted": 0, "failed": 0}

    client = _get_client()

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
            "company_logo": _logo_dev_url(job.company),
            **_parse_visa_signals(job.description or ""),
        }
        for job in jobs
        if not any(d in (job.apply_url or "") for d in BLOCKED_DOMAINS)
        and not _is_excluded_title(job.title or "")
    ]

    try:
        response = client.table("jobs").upsert(
            rows, on_conflict="external_apply_link", ignore_duplicates=True
        ).execute()
        inserted = len(response.data) if response.data else 0
        failed = 0
    except Exception as exc:
        logger.error("Bulk push failed: %s", exc)
        return {"inserted": 0, "failed": len(rows)}

    logger.info("Supabase push done: %d inserted, %d failed", inserted, failed)

    # Enrich unenriched jobright jobs (most recent first, capped to avoid timeout)
    result = (
        client.table("jobs")
        .select("id")
        .eq("ingested_via", "jobright")
        .eq("description_enriched", False)
        .or_("description.is.null,description.eq.")
        .order("created_at", desc=True)
        .limit(_ENRICH_LIMIT)
        .execute()
    )
    job_ids = [r["id"] for r in result.data or []]
    logger.info("Enriching %d jobright jobs...", len(job_ids))
    _enrich_jobs(job_ids)

    return {"inserted": inserted, "failed": failed}
