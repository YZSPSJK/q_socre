import os
import tomllib
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
config_override = os.getenv("QSCORE_CONFIG")
config_path = Path(config_override) if config_override else BASE_DIR / "qscore.local.toml"
config = {}
if config_override or config_path.is_file():
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)

app_config = config.get("app", {})
database_config = config.get("database", {})
SECRET_KEY = app_config.get("secret_key") or os.getenv("QSCORE_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("请在配置文件 [app] 中设置 secret_key，或提供 QSCORE_SECRET_KEY。")
DEBUG = app_config.get("debug", os.getenv("QSCORE_DEBUG") == "1")
ALLOWED_HOSTS = os.getenv("QSCORE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("QSCORE_TRUSTED_ORIGINS", "").split(",") if os.getenv(
    "QSCORE_TRUSTED_ORIGINS"
) else []
SESSION_COOKIE_SECURE = os.getenv("QSCORE_COOKIE_SECURE", "0" if DEBUG else "1") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

INSTALLED_APPS = [
    "qscore.apps.AccountAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ratings",
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
if os.getenv("QSCORE_SERVE_STATIC") == "1":
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
ROOT_URLCONF = "qscore.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
    },
}]
WSGI_APPLICATION = "qscore.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "mysql.connector.django",
        "NAME": database_config.get("name", os.getenv("QSCORE_DB_NAME", "qscore")),
        "USER": database_config.get("user", os.getenv("QSCORE_DB_USER", "qscore")),
        "PASSWORD": database_config.get("password", os.getenv("QSCORE_DB_PASSWORD", "")),
        "HOST": database_config.get("host", os.getenv("QSCORE_DB_HOST", "127.0.0.1")),
        "PORT": database_config.get("port", os.getenv("QSCORE_DB_PORT", "3306")),
        "OPTIONS": {"isolation_level": "read committed"},
    },
}
AUTH_USER_MODEL = "ratings.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.getenv("QSCORE_TIME_ZONE", "Asia/Singapore")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
