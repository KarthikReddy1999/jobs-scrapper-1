import json
import logging
import os
import random
import re
import threading
import time
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.conf import settings
from django.db import IntegrityError, close_old_connections
from fake_useragent import UserAgent
from playwright.sync_api import sync_playwright

from jobright_site.apply_live import is_apply_url_live
from jobright_site.apply_urls import is_blocked_apply_host, is_valid_apply_url as _valid_apply
from jobright_site.scraper_process import (
    clear_stop_flag,
    is_stop_requested,
    pid_is_alive,
    request_stop,
    spawn_worker,
    terminate_pid,
)

from .models import JobrightJob, JobrightScraperState
from .time_utils import (
    format_posted_time,
    is_within_24h_from_publish,
    parse_publish_time,
    slugify_keyword,
)

logger = logging.getLogger("jobright_scraper")

_stop_event = threading.Event()
_active_browser = None
_active_lock = threading.Lock()
_ua = UserAgent()

JOBS_PER_PAGE = 20
MAX_SLUGS_PER_KEYWORD = getattr(settings, "JOBRIGHT_MAX_SLUGS_PER_KEYWORD", 3)
USE_SLUG_VARIANTS = getattr(settings, "JOBRIGHT_USE_SLUG_VARIANTS", True)
ATS_DOMAINS = tuple(settings.ALLOWED_ATS)
CAREER_PATH_SUFFIXES = ("", "/careers", "/jobs", "/career", "/join-us", "/work-with-us", "/open-positions")


def _title_match_score(want, found):
    if not want or not found:
        return 0.0
    return SequenceMatcher(None, want.lower(), found.lower()).ratio()


def _board_tokens(company_name, company_url=""):
    company = (company_name or "").strip()
    slug = slugify_keyword(company)
    tokens = []
    if slug:
        tokens.extend([slug, slug.replace("-", "")])
    if company_url and str(company_url).startswith("http"):
        host = urlparse(company_url).netloc.lower().replace("www.", "")
        base = host.split(".")[0] if host else ""
        if base and len(base) >= 2:
            tokens.extend([base, base.replace("-", "")])
    clean = re.sub(r"[^a-z0-9]", "", company.lower())
    if clean:
        tokens.append(clean)
    words = re.findall(r"[a-z0-9]{3,}", company.lower())
    if words:
        tokens.append(words[0])
    return list(dict.fromkeys(t for t in tokens if t and len(t) >= 2))


def _greenhouse_apply(request_ctx, job_title, company_name, company_url=""):
    tokens = _board_tokens(company_name, company_url)
    best_url = None
    best_score = 0.0
    for token in tokens[:8]:
        if _should_stop():
            break
        api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        try:
            resp = request_ctx.get(api, timeout=12000)
            if resp.status >= 400:
                continue
            jobs = resp.json().get("jobs") or []
        except Exception:
            continue
        for job in jobs:
            score = _title_match_score(job_title, job.get("title") or "")
            if score > best_score:
                best_score = score
                best_url = job.get("absolute_url") or ""
    if best_url and best_score >= 0.65 and is_valid_apply_url(best_url, company_url=company_url):
        if is_apply_url_live(request_ctx, best_url, ATS_DOMAINS, company_url=company_url):
            return best_url
    return None


def _lever_apply(request_ctx, job_title, company_name, company_url=""):
    tokens = _board_tokens(company_name, company_url)
    best_url = None
    best_score = 0.0
    for token in tokens[:8]:
        if _should_stop():
            break
        api = f"https://api.lever.co/v0/postings/{token}?mode=json"
        try:
            resp = request_ctx.get(api, timeout=12000)
            if resp.status >= 400:
                continue
            postings = resp.json()
            if not isinstance(postings, list):
                continue
        except Exception:
            continue
        for post in postings:
            score = _title_match_score(job_title, post.get("text") or post.get("title") or "")
            if score > best_score:
                best_score = score
                best_url = post.get("hostedUrl") or post.get("applyUrl") or ""
    if best_url and best_score >= 0.65 and is_valid_apply_url(best_url, company_url=company_url):
        if is_apply_url_live(request_ctx, best_url, ATS_DOMAINS, company_url=company_url):
            return best_url
    return None


def _slugs_for_keyword(keyword):
    base = slugify_keyword(keyword)
    if not base:
        return []
    slugs = [base]
    if USE_SLUG_VARIANTS:
        if "engineer" in base and "developer" not in base:
            slugs.append(base.replace("engineer", "developer"))
        elif "developer" in base and "engineer" not in base:
            slugs.append(base.replace("developer", "engineer"))
        if "analyst" in base:
            slugs.append(base.replace("analyst", "analysis"))
    return slugs[:MAX_SLUGS_PER_KEYWORD]


def _close_active_browser():
    global _active_browser
    with _active_lock:
        browser = _active_browser
        _active_browser = None
    if browser:
        try:
            browser.close()
        except Exception:
            pass


def _should_stop():
    return _stop_event.is_set() or is_stop_requested()


def is_scraper_running():
    state = JobrightScraperState.get_singleton()
    return pid_is_alive(state.worker_pid)


def is_usa_job(job_result, company_result=None):
    loc = (job_result.get("jobLocation") or "").lower()
    if any(
        x in loc
        for x in (
            "usa",
            "united states",
            "remote in usa",
            ", us",
            "u.s.",
        )
    ):
        return True
    if company_result:
        cloc = (company_result.get("companyLocation") or "").lower()
        if "usa" in cloc or "united states" in cloc:
            return True
    return False


def is_valid_apply_url(url, company_url=""):
    return _valid_apply(url, ATS_DOMAINS, company_url=company_url)


def _find_ats_in_text(text, company_url=""):
    if not text:
        return []
    found = []
    for m in re.finditer(r"https?://[^\s\"'<>\\]+", text):
        u = m.group(0).rstrip(".,;)")
        if is_blocked_apply_host(u):
            continue
        if is_valid_apply_url(u, company_url=company_url):
            found.append(u)
    return found


def _is_job_page_ok(request_ctx, url, company_url=""):
    if is_blocked_apply_host(url) or not is_valid_apply_url(url, company_url=company_url):
        return False, url
    if not is_apply_url_live(request_ctx, url, ATS_DOMAINS, company_url=company_url):
        logger.info("Rejected dead/404 apply URL: %s", url[:90])
        return False, url
    if company_url:
        try:
            fu = urlparse(url)
            if _host_on_company(fu.netloc, company_url) and fu.path in ("", "/"):
                return False, url
        except Exception:
            pass
    return True, url


def _host_on_company(host, company_url):
    from jobright_site.apply_urls import _host_on_company_domain

    return _host_on_company_domain(host.lower(), company_url)


def job_exists(title, company, location, apply_url):
    close_old_connections()
    if JobrightJob.objects.filter(apply_url=apply_url).exists():
        return True
    return JobrightJob.objects.filter(title=title, company=company, location=location).exists()


class JobrightScraper:
    BASE = "https://jobright.ai"

    def __init__(self, resume=False):
        self.resume = resume
        self.state = JobrightScraperState.get_singleton()
        raw = self.state.processed_ids or ""
        self.processed = set(x for x in raw.split(",") if x)
        self.build_id = None
        if resume:
            self._hydrate_processed_from_db()

    def _hydrate_processed_from_db(self):
        close_old_connections()
        before = len(self.processed)
        for jid in JobrightJob.objects.exclude(jobright_job_id="").values_list(
            "jobright_job_id", flat=True
        ).iterator(chunk_size=5000):
            if jid:
                self.processed.add(jid)
        logger.info(
            "Resume: %s IDs in state, +%s from DB (total %s)",
            before,
            len(self.processed) - before,
            len(self.processed),
        )

    def _save_state(self, **kwargs):
        close_old_connections()
        for k, v in kwargs.items():
            setattr(self.state, k, v)
        self.state.processed_ids = ",".join(sorted(self.processed)[-80000:])
        self.state.save()

    def _check_stop(self):
        if _should_stop():
            raise StopIteration

    def _human_delay(self, lo=0.25, hi=0.9):
        end = time.time() + random.uniform(lo, hi)
        while time.time() < end:
            if _should_stop():
                raise StopIteration
            time.sleep(0.12)

    def _scroll_page(self, page):
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(200, 500))
            end = time.time() + random.uniform(0.2, 0.6)
            while time.time() < end:
                if _should_stop():
                    raise StopIteration
                time.sleep(0.1)

    def _ensure_build_id(self, page):
        if self.build_id:
            return
        page.goto(f"{self.BASE}/jobs/software-engineer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)
        nd = page.locator("script#__NEXT_DATA__")
        if nd.count():
            data = json.loads(nd.inner_text())
            self.build_id = data.get("buildId")

    def _load_keyword_jobs_for_slug(self, page, slug):
        self._ensure_build_id(page)
        if self.build_id:
            json_url = f"{self.BASE}/_next/data/{self.build_id}/jobs/{slug}.json?slug={slug}"
            try:
                resp = page.request.get(json_url, timeout=45000)
                if resp.status == 200:
                    job_list = resp.json().get("pageProps", {}).get("jobList")
                    if job_list:
                        return job_list
            except Exception as exc:
                logger.debug("JSON list failed %s: %s", slug, exc)

        list_url = f"{self.BASE}/jobs/{slug}"
        page.goto(list_url, wait_until="domcontentloaded", timeout=90000)
        self._scroll_page(page)
        page.wait_for_timeout(2000)
        nd = page.locator("script#__NEXT_DATA__")
        if not nd.count():
            return []
        data = json.loads(nd.inner_text())
        self.build_id = data.get("buildId") or self.build_id
        return data.get("props", {}).get("pageProps", {}).get("jobList", [])

    def _load_keyword_jobs(self, page, keyword):
        merged = {}
        for slug in _slugs_for_keyword(keyword):
            if _should_stop():
                break
            for item in self._load_keyword_jobs_for_slug(page, slug):
                jr = item.get("jobResult") or {}
                job_id = jr.get("jobId")
                if job_id and job_id not in merged:
                    merged[job_id] = item
            self._human_delay(0.15, 0.35)
        return list(merged.values())

    def _load_job_detail(self, page, job_id):
        page.goto(f"{self.BASE}/jobs/info/{job_id}", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)
        nd = page.locator("script#__NEXT_DATA__")
        if not nd.count():
            return None, None
        data = json.loads(nd.inner_text())
        ds = data.get("props", {}).get("pageProps", {}).get("dataSource") or {}
        jr = ds.get("jobResult") or {}
        cr = ds.get("companyResult") or {}
        return jr, cr

    def _extract_apply_url(self, page, context, job_id, company_url, job_title, company_name=""):
        self._check_stop()
        company_url = company_url or ""

        gh = _greenhouse_apply(context.request, job_title, company_name, company_url)
        if gh:
            return gh
        lev = _lever_apply(context.request, job_title, company_name, company_url)
        if lev:
            return lev

        captured_pages = []

        def on_page(pg):
            try:
                pg.wait_for_load_state("domcontentloaded", timeout=20000)
                u = pg.url
                if u and "jobright" not in u.lower():
                    captured_pages.append(u)
            except Exception:
                pass

        context.on("page", on_page)

        jr, cr = self._load_job_detail(page, job_id)
        company_url = company_url or (cr or {}).get("companyURL", "")

        popup_urls = []
        page_urls = []
        career_urls = []

        for u in _find_ats_in_text(page.content(), company_url):
            page_urls.append(u)

        for label, selector in (
            ("APPLY NOW", 'button:has-text("APPLY NOW")'),
            ("Apply on Employer Site", 'text=Apply on Employer Site'),
        ):
            try:
                with context.expect_page(timeout=12000) as pinfo:
                    page.locator(selector).first.click(timeout=8000)
                popup = pinfo.value
                popup.wait_for_load_state("domcontentloaded", timeout=20000)
                if popup.url and "jobright" not in popup.url.lower():
                    popup_urls.append(popup.url)
                for u in _find_ats_in_text(popup.content(), company_url):
                    popup_urls.append(u)
                popup.close()
            except Exception:
                try:
                    page.locator(selector).first.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    for u in _find_ats_in_text(page.content(), company_url):
                        page_urls.append(u)
                except Exception as exc:
                    logger.debug("Apply UI %s: %s", label, exc)

        for u in captured_pages:
            if is_blocked_apply_host(u):
                continue
            if is_valid_apply_url(u, company_url=company_url):
                popup_urls.append(u)

        if company_url:
            career_urls.extend(self._scan_company_careers(context.request, company_url, job_title))

        candidates = popup_urls + page_urls + career_urls
        seen = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            ok, final = _is_job_page_ok(context.request, url, company_url)
            if ok:
                logger.info("ATS OK %s -> %s", job_id, final[:90])
                return final

        return None

    def _scan_company_careers(self, request_ctx, company_url, job_title):
        urls = []
        if not company_url or not company_url.startswith("http"):
            return urls
        base = company_url.rstrip("/")
        title_words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", job_title or "")][:4]

        for suffix in CAREER_PATH_SUFFIXES:
            if _should_stop():
                break
            try:
                target = base + suffix
                resp = request_ctx.get(target, timeout=20000)
                if resp.status >= 400:
                    continue
                soup = BeautifulSoup(resp.text(), "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = urljoin(target, href)
                    if is_blocked_apply_host(href) or not is_valid_apply_url(href, company_url=company_url):
                        continue
                    text = (a.get_text() or "").lower()
                    if any(d in href.lower() for d in ATS_DOMAINS):
                        urls.append(href)
                    elif title_words and any(w in text for w in title_words):
                        urls.append(href)
            except Exception:
                continue
        return urls

    def _process_keyword(self, page, context, keyword, ki, total):
        saved_before = self.state.jobs_saved
        items = self._load_keyword_jobs(page, keyword)
        if not items:
            logger.info("No jobs for keyword: %s", keyword)
            return 0

        self._save_state(
            current_page=1,
            last_message=f"[{ki + 1}/{total}] {keyword} — {len(items)} listings",
        )

        for item in items:
            if _should_stop():
                raise StopIteration

            jr = item.get("jobResult") or {}
            cr = item.get("companyResult") or {}
            job_id = jr.get("jobId")
            if not job_id or job_id in self.processed:
                continue
            if not is_usa_job(jr, cr):
                continue
            if not is_within_24h_from_publish(jr.get("publishTime"), jr.get("publishTimeDesc")):
                continue

            posted_ts = parse_publish_time(jr.get("publishTime"))
            posted_label = format_posted_time(posted_ts) if posted_ts else jr.get("publishTimeDesc", "Recently")
            if not posted_label:
                continue

            self.processed.add(job_id)
            self._human_delay(0.08, 0.25)

            apply_url = self._extract_apply_url(
                page,
                context,
                job_id,
                cr.get("companyURL", ""),
                jr.get("jobTitle", ""),
                cr.get("companyName", ""),
            )
            if not apply_url:
                self.state.jobs_skipped += 1
                logger.info("Skipped (no valid ATS): %s", jr.get("jobTitle"))
                self._save_state(jobs_skipped=self.state.jobs_skipped)
                continue

            title = (jr.get("jobTitle") or "").strip()
            company = (cr.get("companyName") or "").strip()
            location = (jr.get("jobLocation") or "United States").strip()

            if job_exists(title, company, location, apply_url):
                self.state.jobs_skipped += 1
                self._save_state(jobs_skipped=self.state.jobs_skipped)
                continue

            close_old_connections()
            try:
                JobrightJob.objects.create(
                    title=title,
                    company=company,
                    location=location,
                    apply_url=apply_url,
                    source="Jobright",
                    keyword=keyword,
                    posted_time=posted_label,
                    posted_at=posted_ts or int(time.time()),
                    jobright_job_id=job_id,
                )
            except IntegrityError:
                self.state.jobs_skipped += 1
                self._save_state(jobs_skipped=self.state.jobs_skipped)
                logger.info("Duplicate skipped (DB): %s", apply_url[:80])
                continue
            self.state.jobs_saved += 1
            self._save_state(jobs_saved=self.state.jobs_saved)
            logger.info("Saved: %s @ %s (%s)", title, company, posted_label)

        return self.state.jobs_saved - saved_before

    def run(self):
        global _active_browser
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        close_old_connections()
        keywords = list(settings.KEYWORDS)
        total = len(keywords)
        start_idx = self.state.keyword_index if self.resume else 0

        if not self.resume:
            self.processed.clear()
            self._save_state(
                status=JobrightScraperState.STATUS_RUNNING,
                keyword_index=0,
                current_page=1,
                jobs_saved=0,
                jobs_skipped=0,
                last_message=f"Jobright scraper started — {total} keywords",
            )
        else:
            kw = self.state.current_keyword or (keywords[start_idx] if start_idx < total else "")
            self._save_state(
                status=JobrightScraperState.STATUS_RUNNING,
                last_message=f"Resuming keyword {start_idx + 1}/{total}: '{kw}'",
            )

        logger.info("Jobright scraper started resume=%s idx=%s", self.resume, start_idx + 1)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                with _active_lock:
                    _active_browser = browser

                for ki in range(start_idx, total):
                    self._check_stop()
                    keyword = keywords[ki]
                    context = browser.new_context(user_agent=_ua.random, viewport={"width": 1400, "height": 900})
                    page = context.new_page()

                    try:
                        self._save_state(
                            current_keyword=keyword,
                            keyword_index=ki,
                            current_page=1,
                            last_message=f"[{ki + 1}/{total}] Searching: {keyword}",
                        )
                        n = self._process_keyword(page, context, keyword, ki, total)
                        self._save_state(
                            keyword_index=ki + 1,
                            current_page=1,
                            last_message=f"[{ki + 1}/{total}] Done '{keyword}' (+{n} jobs)",
                        )
                    except StopIteration:
                        raise
                    except Exception as exc:
                        logger.exception("Keyword error %s: %s", keyword, exc)
                        self._save_state(
                            keyword_index=ki + 1,
                            last_message=f"Error on '{keyword}': {str(exc)[:120]}",
                        )
                    finally:
                        try:
                            context.close()
                        except Exception:
                            pass
                        self.resume = False
                        if not _should_stop():
                            self._human_delay(0.5, 1.0)

                try:
                    browser.close()
                except Exception:
                    pass
                with _active_lock:
                    _active_browser = None

                if not _should_stop():
                    self._save_state(
                        status=JobrightScraperState.STATUS_IDLE,
                        keyword_index=total,
                        current_keyword="",
                        last_message=f"Completed all {total} Jobright keywords",
                    )

        except StopIteration:
            kw = self.state.current_keyword or "—"
            ki = self.state.keyword_index
            self._save_state(
                status=JobrightScraperState.STATUS_STOPPED,
                keyword_index=ki,
                last_message=(
                    f"Stopped — Resume continues keyword {ki + 1}: '{kw}' (no duplicates)"
                ),
            )
            logger.info("Jobright stopped at keyword %s", kw)
        except Exception as exc:
            if _should_stop():
                self._save_state(status=JobrightScraperState.STATUS_STOPPED, last_message="Stopped by user")
            else:
                self._save_state(status=JobrightScraperState.STATUS_STOPPED, last_message=str(exc)[:500])
                logger.exception("Jobright scraper error: %s", exc)
        finally:
            _close_active_browser()


def start_scraper(resume=False):
    if is_scraper_running():
        return False, "Jobright scraper already running (separate process)"

    clear_stop_flag()
    _stop_event.clear()
    state = JobrightScraperState.get_singleton()
    total = len(settings.KEYWORDS)
    if not resume:
        close_old_connections()
        deleted, _ = JobrightJob.objects.all().delete()
        state.status = JobrightScraperState.STATUS_RUNNING
        state.keyword_index = 0
        state.current_page = 1
        state.current_keyword = ""
        state.jobs_saved = 0
        state.jobs_skipped = 0
        state.processed_ids = ""
        state.last_message = f"Fresh start — deleted {deleted} jobs, keyword 1/{total}"
        start_msg = f"Started fresh: cleared {deleted} jobs, keyword 1/{total}"
    else:
        state.status = JobrightScraperState.STATUS_RUNNING
        kw = state.current_keyword or "—"
        idx = state.keyword_index
        state.last_message = (
            f"Resuming keyword {idx + 1}/{total}: '{kw}' (no duplicates)"
        )
        start_msg = None

    pid = spawn_worker(resume=resume)
    state.worker_pid = pid
    state.save()
    if start_msg:
        return True, start_msg
    return True, f"Resumed (PID {pid}) — continues from saved keyword"


def stop_scraper():
    state = JobrightScraperState.get_singleton()
    if not is_scraper_running() and state.status != JobrightScraperState.STATUS_RUNNING:
        return True, "Jobright scraper is not running"

    request_stop()
    _stop_event.set()
    terminate_pid(state.worker_pid)
    state.worker_pid = 0
    kw = state.current_keyword or "—"
    idx = state.keyword_index
    state.status = JobrightScraperState.STATUS_STOPPED
    state.worker_pid = 0
    state.last_message = (
        f"Stopped — click Resume for keyword {idx + 1}: '{kw}'"
    )
    state.save()
    return True, state.last_message
