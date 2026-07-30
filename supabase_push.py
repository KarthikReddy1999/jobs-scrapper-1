"""Read all JobrightJob records from Django SQLite and upsert into Supabase."""
import logging
import os
import re
from datetime import datetime, timezone

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
    no_sponsorship = any(p in lower for p in [
        "no sponsorship", "not sponsor", "unable to sponsor",
        "cannot sponsor", "will not sponsor", "does not sponsor",
        "sponsorship not available", "no visa sponsor",
        "not provide sponsorship", "not able to sponsor",
        "must be authorized to work in the u", "must be legally authorized",
        "must have authorization to work", "must be eligible to work",
        "citizen or permanent resident", "us citizen or green card",
        "not support visa", "not offer sponsorship",
        "opt/cpt not", "opt candidates will not", "opt candidates are not",
        "no f-1", "f-1 candidates will not", "f1 candidates will not",
        "no cpt", "cpt not accepted", "f-1 visa not", "no opt candidates",
        "not accepting opt", "not accept opt",
    ])
    opt_positive = not no_sponsorship and any(p in lower for p in [
        "opt accepted", "opt students", "opt eligible", "f-1 opt", "f1 opt",
        "accepts opt", "welcome opt", "open to opt", "opt welcome",
        "optional practical training", "opt candidates", "cpt/opt",
        "opt/cpt", "f1 students welcome", "f-1 students",
    ])
    stem_opt = not no_sponsorship and any(p in lower for p in [
        "stem opt", "stem-opt", "stem extension", "24-month opt", "24 month opt",
    ])
    h1b_sponsoring = not no_sponsorship and any(p in lower for p in [
        "h-1b sponsor", "h1b sponsor", "will sponsor h-1b", "will sponsor h1b",
        "sponsorship available", "visa sponsorship provided", "we will sponsor",
        "we sponsor visa", "sponsors h-1b", "h-1b transfer", "h1b transfer",
        "provide visa sponsorship", "offer visa sponsorship",
    ])
    return {
        "opt_accepting": opt_positive,
        "stem_opt_eligible": stem_opt,
        "no_sponsorship": no_sponsorship,
        "h1b_sponsoring": h1b_sponsoring,
        "visa_confidence": "high" if (no_sponsorship or opt_positive or stem_opt or h1b_sponsoring) else "low",
    }


def _parse_experience_level(description: str):
    if not description:
        return None
    lower = description.lower()
    if any(p in lower for p in ["7+ years", "8+ years", "10+ years"]):
        return "senior"
    if any(p in lower for p in ["2-4 years", "3-5 years", "4-6 years", "2+ years", "3+ years", "4+ years", "5+ years", "6+ years", "5 or more years", "mid-level", "mid level"]):
        return "mid"
    if any(p in lower for p in ["entry level", "entry-level", "0-2 years", "1-2 years", "new grad", "recent graduate", "recent grad"]):
        return "entry"
    return None


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

    from internship_detector import classify as classify_internship, passes_quality_gate

    now_iso = datetime.now(timezone.utc).isoformat()

    def _build_row(job):
        desc = job.description or ""
        title = job.title or ""
        is_intern, intern_meta = classify_internship(title, desc)
        row = {
            "title": title,
            "company": job.company,
            "location": job.location,
            "external_apply_link": job.apply_url,
            "is_published": True,
            "is_reviewing": False,
            "is_archived": False,
            "ingested_via": "jobright",
            "is_direct_apply": True,
            "description": desc or None,
            "description_enriched": False,
            "description_source": "original",
            "company_logo": _logo_dev_url(job.company),
            **_parse_visa_signals(desc),
            "experience_level": _parse_experience_level(desc),
            "last_seen_at": now_iso,
        }
        if is_intern:
            row["employment_type"] = "Internship"
            row["internship_metadata"] = intern_meta
            if not passes_quality_gate(title, job.apply_url or "", intern_meta):
                row["is_published"] = False
                row["is_reviewing"] = True
        return row

    rows = [
        _build_row(job)
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

    # Bump last_seen_at on already-existing rows — ignore_duplicates=True above
    # means the full-row upsert skips them entirely on conflict, so without this
    # a job jobright still shows every day would look stale to the 7-day expiry
    # sweep in sociax-scraper-cron/ats_scraper.py. Every row here came from a
    # fresh (non-resume) scrape pass, so "in `rows`" already means "confirmed
    # live right now" — see JobrightScraper.start_scraper(), which clears the
    # local table before a fresh run. Also un-archives, so a job that comes back
    # after being archived isn't stuck hidden forever.
    # Plain UPDATE, not upsert — an upsert with a minimal payload can get treated
    # as an INSERT under read-after-write visibility lag right after the insert
    # above, and fail NOT NULL on title (confirmed in production 2026-07-15,
    # taking a whole batch down with it). UPDATE can never attempt an insert.
    # Batched — .in_() puts every link in the URL query string, and this list
    # can run to thousands of rows; too many blows past typical URL length
    # limits (also confirmed in production, same day, in the id-list version
    # of this pattern in ats_scraper.py).
    links = [r["external_apply_link"] for r in rows if r.get("external_apply_link")]
    touch_batch_size = 150
    for i in range(0, len(links), touch_batch_size):
        batch = links[i : i + touch_batch_size]
        try:
            client.table("jobs").update(
                {"last_seen_at": now_iso, "is_archived": False}
            ).in_("external_apply_link", batch).execute()
        except Exception as exc:
            logger.error("last_seen_at touch failed: %s", exc)

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
