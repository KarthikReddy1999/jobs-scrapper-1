"""Django settings for standalone Jobright scraper project."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "jobright-standalone-dev-key-change-in-production",
)

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "jobright",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jobright_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "jobright_site.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 60},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

RUNSERVER_PORT = 8001

# Fetch more unique jobs: try engineer/developer slug variants per keyword (Jobright caps ~16/slug).
JOBRIGHT_USE_SLUG_VARIANTS = True
JOBRIGHT_MAX_SLUGS_PER_KEYWORD = 3

ALLOWED_ATS = [
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "icims.com",
    "jobvite.com",
    "taleo.net",
    "oraclecloud.com",
    "successfactors.com",
    "pinpointhq.com",
    "amazon.jobs",
    "careers.microsoft.com",
]

KEYWORDS = [
    "Software engineer",
    "Software developer",
    "Backend developer",
    "Full stack developer",
    "Frontend developer",
    "Platform engineer",
    "System engineer",
    "Java backend developer",
    "Java developer",
    "iOS developer",
    "Android developer",
    "React native developer",
    "Cloud engineer",
    "Devops engineer",
    "Cloud developer",
    "Site reliability engineer",
    "Data analyst",
    "Data engineer",
    "Data science",
    "Machine learning engineer",
    "AI engineer",
    "Gen AI",
    "Analytics engineer",
    "Business intelligence analyst",
    "Security engineer",
    "Cybersecurity analyst",
    "Security analyst",
    "Application security engineer",
    "Network security engineer",
    "QA engineer",
    "Test engineer",
    "Automation test engineer",
    "QA analyst",
    "SDET",
    "Product manager",
    "Engineering manager",
    "UI designer",
    "UX designer",
    "Product designer",
    "SQL developer",
    "ETL developer",
    "Network engineer",
    "Systems administrator",
    "IT support engineer",
    "Technical support engineer",
    "Blockchain developer",
    "Robotics engineer",
    "Graphics engineer",
    "SAP developer",
    "SAP",
    "Salesforce developer",
    "Salesforce administrator",
    "Business analyst",
    "Supply chain",
    "Marketing manager",
    "Marketing analyst",
    "Project manager",
    "Program manager",
    "Aerospace engineer",
    "Mechanical engineer",
    "Civil engineer",
    "Physical therapist",
    "Supply chain manager",
    "Finance analyst",
    "Risk analyst",
    "Finance manager",
    "Product analyst",
    "Product owner",
    "Information security analyst",
    "AWS Azure",
    "AWS Java developer",
    "Quality engineer",
    ".NET developer",
    "Clinical research scientist",
    "Embedded systems engineer",
    "Drug safety associate",
    "AWS DevOps engineer",
    "Quality control",
    "Construction engineer",
    "Power Platform developer",
    "UI UX designer",
    # Extra titles to maximize unique Jobright listings (16 jobs per slug, public API)
    "Python developer",
    "Python engineer",
    "React developer",
    "React engineer",
    "Node developer",
    "Node.js developer",
    "Golang developer",
    "Go developer",
    "Rust developer",
    "C++ developer",
    "C# developer",
    "Ruby developer",
    "PHP developer",
    "Scala developer",
    "Kotlin developer",
    "Swift developer",
    "Flutter developer",
    "Angular developer",
    "Vue developer",
    "Typescript developer",
    "Javascript developer",
    "Web developer",
    "Mobile developer",
    "DevSecOps engineer",
    "MLOps engineer",
    "LLM engineer",
    "NLP engineer",
    "Computer vision engineer",
    "Solutions architect",
    "Cloud architect",
    "Infrastructure engineer",
    "Database administrator",
    "PostgreSQL developer",
    "MongoDB developer",
    "Big data engineer",
    "ETL engineer",
    "BI developer",
    "Tableau developer",
    "Power BI developer",
    "Salesforce engineer",
    "ServiceNow developer",
    "Workday consultant",
    "SAP consultant",
    "Oracle developer",
    "Mainframe developer",
    "Firmware engineer",
    "Hardware engineer",
    "Electrical engineer",
    "Manufacturing engineer",
    "Process engineer",
    "Chemical engineer",
    "Biomedical engineer",
    "Research engineer",
    "Staff engineer",
    "Principal engineer",
    "Lead developer",
    "Senior developer",
    "Junior developer",
    "Entry level software engineer",
    "New grad software engineer",
    "Intern software engineer",
]

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": LOGS_DIR / "scraper.log",
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "jobright_scraper": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "scraper_process": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
