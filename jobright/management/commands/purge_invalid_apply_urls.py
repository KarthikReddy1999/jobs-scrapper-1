from django.conf import settings
from django.core.management.base import BaseCommand
from playwright.sync_api import sync_playwright

from jobright.models import JobrightJob
from jobright_site.apply_live import is_apply_url_live
from jobright_site.apply_urls import is_blocked_apply_host, is_valid_apply_url


class Command(BaseCommand):
    help = "Delete jobs with invalid, dead (404), or non-ATS apply URLs."

    def handle(self, *args, **options):
        removed = 0
        ats = tuple(settings.ALLOWED_ATS)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            request_ctx = browser.new_context().request
            for job in JobrightJob.objects.iterator():
                url = job.apply_url or ""
                reason = None
                if is_blocked_apply_host(url) or not is_valid_apply_url(url, ats):
                    reason = "invalid ATS"
                elif not is_apply_url_live(request_ctx, url, ats):
                    reason = "dead/404"
                if reason:
                    self.stdout.write(f"Removed ({reason}): {job.title} -> {url[:90]}")
                    job.delete()
                    removed += 1
            browser.close()
        self.stdout.write(self.style.SUCCESS(f"Deleted {removed} invalid or dead apply URLs"))
