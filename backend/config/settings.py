"""Django settings for Socra.

All configuration comes from the environment: the root .env file, which docker compose also
injects. Every value has a development default, so CI and tests run with no .env at all.
"""

import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import environ

from .databases import DatabaseConfig

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = "pytest" in sys.modules

env = environ.Env()
# Root .env when running on the host; inside docker it is absent and compose provides the variables.
# Never overrides variables that are already set.
environ.Env.read_env(BASE_DIR.parent / ".env")

# The default only exists so tests and CI run without a .env; `check --deploy` refuses it (core/checks.py).
DEV_SECRET_KEY = "dev-insecure-secret-key-change-me"
SECRET_KEY = env("DJANGO_SECRET_KEY", default=DEV_SECRET_KEY)
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "backend"])
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=[
        f"http://localhost:{env('FRONTEND_PORT', default='3000')}",
        f"http://localhost:{env('BACKEND_PORT', default='8000')}",
    ],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "rest_framework_simplejwt.token_blacklist",
    # local
    "core",
    "accounts",
    "llm_registry",
    "lessons",
    "onboarding",
]

AUTH_USER_MODEL = "accounts.User"

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

ASGI_APPLICATION = "config.asgi.application"

# --- Databases: Supabase when SUPABASE_DATABASE_URL is set, otherwise the docker Postgres ---
LOCAL_DATABASE_URL = DatabaseConfig.local_url(
    host=env("POSTGRES_HOST", default="localhost"),
    port=env.int("POSTGRES_PORT", default=5432),
    name=env("POSTGRES_DB", default="lessoncrafter"),
    user=env("POSTGRES_USER", default="lessoncrafter"),
    password=env("POSTGRES_PASSWORD", default="lessoncrafter"),
)
SUPABASE_DATABASE_URL = env("SUPABASE_DATABASE_URL", default="")
DATABASES = DatabaseConfig(env).build(local_url=LOCAL_DATABASE_URL, supabase_url=SUPABASE_DATABASE_URL, testing=TESTING)
USING_SUPABASE = "local" in DATABASES and not TESTING
# Copy local rows that Supabase doesn't have yet, every time the backend starts against Supabase.
SYNC_LOCAL_TO_SUPABASE = env.bool("SYNC_LOCAL_TO_SUPABASE", default=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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
# Local-only project: WhiteNoise serves admin/Swagger assets straight from the apps, no collectstatic step.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")

# --- Redis / Celery ---
_redis_password = env("REDIS_PASSWORD", default="")
_redis_auth = f":{quote(_redis_password, safe='')}@" if _redis_password else ""
_redis_base = f"redis://{_redis_auth}{env('REDIS_HOST', default='localhost')}:{env.int('REDIS_PORT', default=6379)}"
REDIS_URL = f"{_redis_base}/0"
CELERY_BROKER_URL = f"{_redis_base}/0"
CELERY_RESULT_BACKEND = f"{_redis_base}/1"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE

# Shared cache (Redis db 2): the resolved model registry and per-minute LLM rate-limit counters.
# Tests use an in-process cache so they don't depend on Redis.
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        if TESTING
        else {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": f"{_redis_base}/2"}
    )
}

# How long one worker may hold a run without a sign of life, and how long Redis waits before redelivering an
# unacknowledged task. After a hard kill, the run is picked up again once both have passed. Must exceed the
# longest single step of a graph (a model call with its retries and fallbacks).
FLOW_RUN_LOCK_TTL_S = env.int("FLOW_RUN_LOCK_TTL_S", default=600)
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": FLOW_RUN_LOCK_TTL_S}

# Where a started run is queued (the TaskQueue port, lessons/services.py). Tests swap it for an in-memory queue.
LESSON_TASK_QUEUE = "lessons.tasks.CeleryTaskQueue"
# Seconds between keep-alive comments on a run's event stream, so proxies don't close an idle connection.
SSE_HEARTBEAT_S = env.int("SSE_HEARTBEAT_S", default=15)

# --- LLM registry ---
# Thinking-token budgets for models whose reasoning is controlled by a budget (see llm_registry/profiles.py).
LLM_REASONING_BUDGETS = {
    "low": env.int("LLM_REASONING_BUDGET_LOW", default=2048),
    "medium": env.int("LLM_REASONING_BUDGET_MEDIUM", default=8192),
    "high": env.int("LLM_REASONING_BUDGET_HIGH", default=24576),
}

# --- Onboarding ---
# How long a suggested-topics page, a model's topic list and a translation stay in the cache (30 days).
ONBOARDING_SUGGESTION_TTL_S = env.int("ONBOARDING_SUGGESTION_TTL_S", default=30 * 24 * 3600)

# --- Lesson flow ---
# The sandbox/ package (Node): check.mjs and render-check.mjs run in a subprocess (see graph/sandbox.py).
SANDBOX_DIR = env.path("SANDBOX_DIR", default=BASE_DIR.parent / "sandbox")
NODE_BINARY = env("NODE_BINARY", default="node")
SANDBOX_CHECK_TIMEOUT_S = env.int("SANDBOX_CHECK_TIMEOUT_S", default=30)
SANDBOX_RENDER_TIMEOUT_S = env.int("SANDBOX_RENDER_TIMEOUT_S", default=180)
SANDBOX_PAGE_TIMEOUT_MS = env.int("SANDBOX_PAGE_TIMEOUT_MS", default=8000)
# Where lesson media is searched. The defaults are the public services; they are settings so tests and the offline
# walk-through can point them at a fake.
WIKIMEDIA_API_URL = env("WIKIMEDIA_API_URL", default="https://commons.wikimedia.org/w/api.php")
OPENVERSE_API_URL = env("OPENVERSE_API_URL", default="https://api.openverse.org/v1/images/")
GIPHY_API_URL = env("GIPHY_API_URL", default="https://api.giphy.com/v1/gifs/search")
# Downloads are https-only and never to a private address. Set true only for the offline walk-through's fake media host.
MEDIA_ALLOW_PRIVATE_HOSTS = env.bool("MEDIA_ALLOW_PRIVATE_HOSTS", default=False)
# Optional GIF search for the media agent (also add "giphy" to FlowSettings.media_sources and licences).
GIPHY_API_KEY = env("GIPHY_API_KEY", default="")
# Signed media URLs (/api/media/{id}?exp=&sig=) stay valid this long.
MEDIA_URL_TTL_S = env.int("MEDIA_URL_TTL_S", default=6 * 3600)

# Tracing of the model calls (llm_registry/tracing.py): none, langsmith or langfuse. Off by default, because a trace
# holds the prompts and replies, which contain what the learner wrote. The services' own keys are read from the
# environment by their SDKs (LANGSMITH_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST).
LLM_TRACING = env("LLM_TRACING", default="none")

# --- DRF / OpenAPI ---
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("AUTH_THROTTLE_RATE", default="20/min"),  # register/login, per client address
        "auth_account": env("AUTH_ACCOUNT_THROTTLE_RATE", default="10/min"),  # login attempts per email
        "auth_refresh": env("AUTH_REFRESH_THROTTLE_RATE", default="60/min"),
        "lesson_create": env("LESSON_CREATE_THROTTLE_RATE", default="30/hour"),  # each lesson costs model calls
        "test_submit": env("TEST_SUBMIT_THROTTLE_RATE", default="30/hour"),  # open-ended answers cost model calls
        "topic_suggestions": env(
            "TOPIC_SUGGESTIONS_THROTTLE_RATE", default="30/min"
        ),  # per user; may cost a model call
    },
    # Requests arrive through the Next.js proxy; the client address is the X-Forwarded-For entry it appends.
    # Keep the API port bound to localhost (BIND_ADDRESS) so nobody can reach Django directly with a forged header.
    "NUM_PROXIES": env.int("TRUSTED_PROXY_COUNT", default=1),
}

# --- Auth: JWTs in httpOnly cookies (see accounts/cookies.py) ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": SECRET_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}
# Only sent over HTTPS when true; local development runs on plain http.
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=False)
# Same switch for Django's own cookies (admin session, CSRF): one setting to flip when moving to HTTPS.
SESSION_COOKIE_SECURE = AUTH_COOKIE_SECURE
CSRF_COOKIE_SECURE = AUTH_COOKIE_SECURE

SPECTACULAR_SETTINGS = {
    "TITLE": "Socra API",
    "DESCRIPTION": "Diagnose what a learner knows, then generate a lesson or study sheet for the rest.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api",
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True, "displayRequestDuration": True, "withCredentials": True},
    # Separate request/response components, so read-only fields don't appear in request bodies.
    "COMPONENT_SPLIT_REQUEST": True,
    # One name per choice set that appears in several components.
    "ENUM_NAME_OVERRIDES": {
        "RouteEnum": "lessons.stages.Route",
        "StageEnum": "lessons.stages.Stage",
        "MaterialKindEnum": "lessons.stages.MaterialKind",
        "QuizKindEnum": "lessons.models.Quiz.Kind",
        "RunStatusEnum": "lessons.models.GraphRun.Status",
        "TestSubmissionStatusEnum": "lessons.models.TestSubmission.Status",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
