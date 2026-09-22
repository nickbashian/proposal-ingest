"""Fail-closed application configuration; no provider connections at startup."""

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml
from django.core.exceptions import ImproperlyConfigured

ROOT = Path(__file__).resolve().parents[2]
with (ROOT / "config/default_config.yaml").open(encoding="utf-8") as stream:
    APP = yaml.safe_load(stream)["web_application"]

MODE = os.environ.get("PROPOSAL_APP_ENV", "local")
LOCAL_AUTH = os.environ.get("PROPOSAL_LOCAL_AUTH_ENABLED", "false").lower() == "true"
if MODE not in {"local", "production"} or (MODE == "production" and LOCAL_AUTH):
    raise ImproperlyConfigured("Invalid deployment mode or local authentication in production")

SECRET_KEY = os.environ.get("PROPOSAL_SECRET_KEY", "")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
OIDC_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.environ.get("ENTRA_REDIRECT_URI", "")
if MODE == "production":
    if not os.environ.get("DATABASE_URL"):
        raise ImproperlyConfigured("Production requires explicit DATABASE_URL")
    if not all((SECRET_KEY, OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_REDIRECT_URI)):
        raise ImproperlyConfigured("Production requires secret key and complete OIDC settings")
    if len(SECRET_KEY) < 50 or not all(
        urlparse(value).scheme == "https" for value in (OIDC_ISSUER, OIDC_REDIRECT_URI)
    ):
        raise ImproperlyConfigured("Production requires a strong secret and HTTPS OIDC URLs")
else:
    SECRET_KEY = SECRET_KEY or "local-development-only-never-deploy-this-key"

DEBUG = False
ALLOWED_HOSTS = (
    os.environ.get("PROPOSAL_ALLOWED_HOSTS", "").split(",")
    if MODE == "production"
    else ["localhost", "127.0.0.1", "[::1]", "testserver"]
)
if MODE == "production" and (not all(ALLOWED_HOSTS) or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Production requires explicit PROPOSAL_ALLOWED_HOSTS")
database = urlparse(os.environ.get("DATABASE_URL", APP["development_database_url"]))
if database.scheme not in {"postgres", "postgresql"}:
    raise ImproperlyConfigured("DATABASE_URL must identify PostgreSQL")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database.path.lstrip("/"),
        "USER": unquote(database.username or ""),
        "PASSWORD": unquote(database.password or ""),
        "HOST": database.hostname,
        "PORT": database.port or 5432,
        "OPTIONS": {"connect_timeout": 5},
    }
}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "proposal_app",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "proposal_app.auth.AccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "proposal_app.urls"
STATIC_URL = "/static/"
WSGI_APPLICATION = "proposal_app.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
            ]
        },
    }
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = APP["session_seconds"]
SESSION_COOKIE_SECURE = MODE == "production"
CSRF_COOKIE_SECURE = MODE == "production"
SECURE_SSL_REDIRECT = MODE == "production"
SECURE_HSTS_SECONDS = 31536000 if MODE == "production" else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = MODE == "production"
SECURE_HSTS_PRELOAD = MODE == "production"
# Do not trust proxy/forwarded headers without an explicit deployment decision.
DATA_UPLOAD_MAX_MEMORY_SIZE = APP["request_max_bytes"]

for key in ("lease_seconds", "max_attempts", "backoff_seconds", "poll_seconds"):
    APP[key] = int(os.environ.get("JOB_" + key.upper(), APP[key]))
    if APP[key] <= 0:
        raise ImproperlyConfigured(f"JOB_{key.upper()} must be positive")

for key, environment in (
    ("setup_limit_usd", "SETUP_COST_LIMIT_USD"),
    ("monthly_limit_usd", "MONTHLY_VARIABLE_COST_LIMIT_USD"),
    ("job_limit_usd", "SINGLE_JOB_COST_LIMIT_USD"),
):
    APP[key] = os.environ.get(environment, APP[key])
    try:
        value = Decimal(APP[key])
        if not value.is_finite() or value <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ImproperlyConfigured(f"{environment} must be finite and positive") from None
if Decimal(APP["setup_limit_usd"]) > 500 or Decimal(APP["monthly_limit_usd"]) > 100:
    raise ImproperlyConfigured("Configured cost exceeds the approved envelope")
