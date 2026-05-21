from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="jobright_dashboard"),
    path("api/jobs/", views.jobs_api, name="jobright_jobs_api"),
    path("api/status/", views.status_api, name="jobright_status_api"),
    path("api/scraper/start/", views.scraper_start, name="jobright_scraper_start"),
    path("api/scraper/stop/", views.scraper_stop, name="jobright_scraper_stop"),
    path("api/scraper/resume/", views.scraper_resume, name="jobright_scraper_resume"),
    path("api/jobs/clear/", views.jobs_clear_all, name="jobright_jobs_clear"),
]
