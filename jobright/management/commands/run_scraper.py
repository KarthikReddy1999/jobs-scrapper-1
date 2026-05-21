import os

from django.core.management.base import BaseCommand

from jobright_site.scraper_process import clear_stop_flag

from jobright.models import JobrightScraperState
from jobright.scraper import JobrightScraper


class Command(BaseCommand):
    help = "Run Jobright scraper in this process (used by dashboard Start button)."

    def add_arguments(self, parser):
        parser.add_argument("--resume", action="store_true", help="Resume from saved keyword index")

    def handle(self, *args, **options):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        clear_stop_flag()
        state = JobrightScraperState.get_singleton()
        state.worker_pid = os.getpid()
        state.status = JobrightScraperState.STATUS_RUNNING
        state.save(update_fields=["worker_pid", "status"])

        self.stdout.write(self.style.SUCCESS(f"Jobright worker started PID={os.getpid()}"))

        try:
            JobrightScraper(resume=options["resume"]).run()
        finally:
            state = JobrightScraperState.get_singleton()
            if state.worker_pid == os.getpid():
                state.worker_pid = 0
                if state.status == JobrightScraperState.STATUS_RUNNING:
                    state.status = JobrightScraperState.STATUS_IDLE
                state.save(update_fields=["worker_pid", "status"])
            self.stdout.write("Jobright worker exited.")

