"""Fetch pending role requests from Supabase and notify when scraping is done."""
import logging
import os

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
_WEBHOOK_SECRET = os.environ.get("SCRAPER_WEBHOOK_SECRET", "")


def fetch_pending_role_requests() -> list[dict]:
    """Return [{normalized_role, search_terms}, ...] deduplicated by role."""
    if not _SUPABASE_URL or not _SERVICE_KEY:
        return []
    try:
        from supabase import create_client
        client = create_client(_SUPABASE_URL, _SERVICE_KEY)
        result = (
            client.table("role_requests")
            .select("normalized_role, search_terms")
            .filter("normalized_role", "not.is", "null")
            .filter("scraped_at", "is", "null")
            .filter("emailed_at", "is", "null")
            .execute()
        )
        seen: dict[str, list[str]] = {}
        for row in result.data or []:
            role = row.get("normalized_role")
            if role and role not in seen:
                seen[role] = row.get("search_terms") or []
        return [{"normalized_role": r, "search_terms": t} for r, t in seen.items()]
    except Exception as exc:
        logger.error("fetch_pending_role_requests failed: %s", exc)
        return []


def notify_role_complete(normalized_role: str, jobs_found_count: int) -> None:
    """POST to complete-role-request Edge Function after scraping a role."""
    if not _SUPABASE_URL or not _WEBHOOK_SECRET:
        logger.warning("notify_role_complete: missing env vars, skipping")
        return
    try:
        import httpx
        url = f"{_SUPABASE_URL}/functions/v1/complete-role-request"
        resp = httpx.post(
            url,
            json={
                "normalized_role": normalized_role,
                "jobs_found_count": jobs_found_count,
                "secret": _WEBHOOK_SECRET,
            },
            headers={
                "Authorization": f"Bearer {_SERVICE_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        logger.info("Role complete notified: %s → %s", normalized_role, resp.json())
    except Exception as exc:
        logger.error("notify_role_complete failed for '%s': %s", normalized_role, exc)
