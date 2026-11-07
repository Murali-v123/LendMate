"""
LendMate settings.

Secrets and environment-specific values come from environment variables.
In development they are loaded from a local .env file. Nothing sensitive is
hardcoded here.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name, "true" if default else "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -----------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "insecure-development-key-do-not-use-in-production"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "notifications.apps.NotificationsConfig",
    "lending.apps.LendingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database (MySQL, used in development and production alike) ----------

db_options = {"charset": "utf8mb4"}

# Optional SSL/TLS configuration for remote managed MySQL connections (e.g., AWS RDS, Azure, PlanetScale)
db_ssl_ca = os.environ.get("MYSQL_SSL_CA", "") or os.environ.get("DB_SSL_CA", "")
db_ssl_mode = os.environ.get("MYSQL_SSL_MODE", "") or os.environ.get("DB_SSL_MODE", "")

if db_ssl_ca:
    db_options["ssl"] = {"ca": db_ssl_ca}
if db_ssl_mode:
    db_options["ssl_mode"] = db_ssl_mode

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE") or os.environ.get("DB_NAME", "lendmate"),
        "USER": os.environ.get("MYSQL_USER") or os.environ.get("DB_USER", "lendmate"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD") or os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST") or os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT") or os.environ.get("DB_PORT", "3306"),
        "OPTIONS": db_options,
        "CONN_MAX_AGE": 60,
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication -------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# --- Internationalisation -------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Email (password reset) ----------------------------------------------

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "LendMate <no-reply@lendmate.local>")

# --- WhatsApp (Meta WhatsApp Business Platform Cloud API) -------------

WHATSAPP_BACKEND = os.environ.get("WHATSAPP_BACKEND", "notifications.whatsapp.MockWhatsAppBackend")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v20.0")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")

# Template names (configured and approved in Meta WhatsApp Business Manager)
WHATSAPP_TEMPLATE_LOAN_CREATED = os.environ.get("WHATSAPP_TEMPLATE_LOAN_CREATED", "lendmate_loan_created")
WHATSAPP_TEMPLATE_PAYMENT_RECEIVED = os.environ.get("WHATSAPP_TEMPLATE_PAYMENT_RECEIVED", "lendmate_payment_received")
WHATSAPP_TEMPLATE_MONTHLY_REMINDER = os.environ.get("WHATSAPP_TEMPLATE_MONTHLY_REMINDER", "lendmate_monthly_reminder")
WHATSAPP_TEMPLATE_OVERDUE_REMINDER = os.environ.get("WHATSAPP_TEMPLATE_OVERDUE_REMINDER", "lendmate_overdue_reminder")
WHATSAPP_TEMPLATE_LOAN_CLOSED = os.environ.get("WHATSAPP_TEMPLATE_LOAN_CLOSED", "lendmate_loan_closed")
WHATSAPP_TEMPLATE_LANGUAGE = os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "en")

# --- SMS (deprecated / preserved for future multi-channel expansion) ----

SMS_BACKEND = os.environ.get("SMS_BACKEND", "notifications.sms.MockSMSBackend")

# MSG91 provider configuration (inactive; preserved for backward compatibility)
MSG91_AUTH_KEY = os.environ.get("MSG91_AUTH_KEY", "")
MSG91_SENDER_ID = os.environ.get("MSG91_SENDER_ID", "LNDMAT")
MSG91_ROUTE = os.environ.get("MSG91_ROUTE", "4")

# --- Celery ---------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60  # seconds – hard limit per task
CELERY_TASK_SOFT_TIME_LIMIT = 45
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Fair dispatch: one task at a time per worker
CELERY_TASK_ACKS_LATE = True  # Acknowledge only after task completes (crash safety)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Celery Beat schedule (Asia/Kolkata timezone applied via CELERY_TIMEZONE)
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Send monthly payment reminders at 09:00 every day
    "monthly-reminders": {
        "task": "notifications.tasks.send_monthly_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    # Send overdue reminders at 10:00 every day
    "overdue-reminders": {
        "task": "notifications.tasks.send_overdue_reminders",
        "schedule": crontab(hour=10, minute=0),
    },
    # Recover stuck notifications every 15 minutes
    "recover-stuck": {
        "task": "notifications.tasks.recover_stuck_notifications",
        "schedule": crontab(minute="*/15"),
    },
}

# --- Logging --------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "notifications": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# --- Security hardening outside development -----------------------------

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=True)
