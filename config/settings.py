"""
Django settings for config project.
"""

import os
from pathlib import Path

import dj_database_url
from dj_database_url import ParseError, UnknownSchemeError
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-only-change-me")

DEBUG = os.environ.get("DEBUG", "true").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
if DATABASE_URL:
    try:
        DATABASES = {
            "default": dj_database_url.config(
                default=DATABASE_URL,
                conn_max_age=600,
            )
        }
    except (ParseError, UnknownSchemeError):
        # Bad or truncated DATABASE_URL (e.g. value starting with "://" after a bad copy/paste).
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- App-specific ---
REPOS_DIR = Path(os.environ.get("REPOS_DIR", str(BASE_DIR / "repos"))).resolve()


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Free tier often has little or no quota on gemini-2.0-flash; 2.5 Flash-Lite usually has higher RPD.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
# When true, skip the Gemini API and return a quick grep-based summary (reliable for demos without quota).
GEMINI_DEMO_MODE = os.environ.get("GEMINI_DEMO_MODE", "").lower() in ("1", "true", "yes")
GEMINI_MAX_RETRIES = _env_int("GEMINI_MAX_RETRIES", 6)
GEMINI_RETRY_BACKOFF_CAP_S = _env_int("GEMINI_RETRY_BACKOFF_CAP_S", 90)
GEMINI_MAX_OUTPUT_TOKENS = _env_int("GEMINI_MAX_OUTPUT_TOKENS", 8192)
GEMINI_MAX_AGENT_ITERATIONS = _env_int("GEMINI_MAX_AGENT_ITERATIONS", 20)
GEMINI_MAX_TOOL_CALLS = _env_int("GEMINI_MAX_TOOL_CALLS", 10)
GEMINI_MAX_TOOL_RESULT_CHARS = _env_int("GEMINI_MAX_TOOL_RESULT_CHARS", 12000)

CORS_ALLOW_ALL_ORIGINS = DEBUG

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}
