"""Verify ATS apply URLs are live (not 404 / removed)."""
import re
from urllib.parse import urlparse

from jobright_site.apply_urls import is_blocked_apply_host, is_valid_apply_url

DEAD_PAGE_MARKERS = (
    "page not found",
    "404 error",
    "404",
    "job no longer",
    "position filled",
    "position has been filled",
    "expired",
    "couldn't find anything",
    "could not find anything",
    "has been removed",
    "might have closed",
    "might have been closed",
    "no longer available",
    "posting is no longer",
    "this job is no longer",
    "sorry, we couldn't",
    "sorry, we could not",
    "role has been filled",
    "requisition is no longer",
    "job posting you're looking for",
    "job posting you are looking for",
    "not accepting applications",
    "no open positions",
    "error 404",
)


def page_body_is_dead(body_low):
    if not body_low:
        return True
    return any(m in body_low for m in DEAD_PAGE_MARKERS)


def parse_lever_url(url):
    parsed = urlparse(url)
    if "lever.co" not in parsed.netloc.lower():
        return None, None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and re.match(r"^[0-9a-f-]{8,}$", parts[1], re.I):
        return parts[0], parts[1]
    return None, None


def lever_posting_live(request_ctx, url):
    site, posting_id = parse_lever_url(url)
    if not site or not posting_id:
        return False
    try:
        direct = request_ctx.get(
            f"https://api.lever.co/v0/postings/{site}/{posting_id}",
            timeout=15000,
        )
        if direct.status == 200:
            return True
        listings = request_ctx.get(
            f"https://api.lever.co/v0/postings/{site}?mode=json",
            timeout=15000,
        )
        if listings.status != 200:
            return False
        posts = listings.json()
        if not isinstance(posts, list):
            return False
        return any((p.get("id") or "") == posting_id for p in posts)
    except Exception:
        return False


def parse_greenhouse_parts(url):
    low = url.lower()
    job_id = None
    m = re.search(r"gh_jid=(\d+)", url, re.I)
    if m:
        job_id = m.group(1)
    if not job_id:
        m = re.search(r"/jobs/(\d+)", url, re.I)
        if m:
            job_id = m.group(1)
    board = None
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/", url, re.I)
    if m:
        board = m.group(1)
    return board, job_id


def greenhouse_job_live(request_ctx, url):
    board, job_id = parse_greenhouse_parts(url)
    if board and job_id:
        try:
            resp = request_ctx.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}",
                timeout=15000,
            )
            if resp.status == 200:
                data = resp.json()
                return bool(data.get("id") or data.get("absolute_url"))
        except Exception:
            pass
    return False


def is_apply_url_live(request_ctx, url, ats_domains, company_url=""):
    if not url or not str(url).startswith("http"):
        return False
    if is_blocked_apply_host(url) or not is_valid_apply_url(url, ats_domains, company_url=company_url):
        return False

    low = url.lower()
    if "lever.co" in low:
        if not lever_posting_live(request_ctx, url):
            return False
    elif "greenhouse.io" in low:
        if not greenhouse_job_live(request_ctx, url):
            return False

    try:
        resp = request_ctx.get(url, max_redirects=12, timeout=25000)
        final = resp.url
        if resp.status >= 400:
            return False
        if is_blocked_apply_host(final):
            return False
        if not is_valid_apply_url(final, ats_domains, company_url=company_url):
            return False
        body = (resp.text() or "").lower()[:25000]
        if page_body_is_dead(body):
            return False
        return True
    except Exception:
        return False
