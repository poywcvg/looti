"""تنظیمات پروژه لوطی — بازار امن خرید و فروش اکانت بازی."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.accounts",
    "apps.listings",
    "apps.escrow",
    "apps.chat",
    "apps.notifications",
    "apps.reviews",
    "apps.panel",
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
    "apps.accounts.middleware.LastSeenMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
            "builtins": ["apps.core.templatetags.ui"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "gamanat"),
        "USER": os.getenv("DB_USER", "gamanat"),
        "PASSWORD": os.getenv("DB_PASSWORD", "gamanat"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5433"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.IdentifierBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("username", "email", "phone", "display_name")}},
    {"NAME": "apps.accounts.validators.PersianMinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if not DEBUG:
    # نام فایل‌های استاتیک هش‌دار می‌شود تا مرورگر نسخه قدیمی را نگه ندارد
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_TAGS = {10: "info", 20: "info", 25: "success", 30: "warning", 40: "error"}

# ---------------------------------------------------------------- برند
# «لوطی» (Looti): در فرهنگ ما لوطی کسی است که قولش قول است و امانت را تا آخر نگه می‌دارد (مثل داش‌آکل)؛
# در زبان گیمرها هم Loot یعنی غنیمت بازی. لاتین «Looti» نوشته می‌شود تا با برندهای خارجی Lootyo/Lootzy قاطی نشود.
SITE_NAME = "لوطی"
SITE_NAME_EN = "Looti"
SITE_TAGLINE = "بازار امن اکانت‌های بازی"

# ---------------------------------------------------------------- معامله
CREDENTIALS_KEY = os.getenv("CREDENTIALS_KEY", "")
OTP_DEBUG = env_bool("OTP_DEBUG", DEBUG)
OTP_TTL_SECONDS = 120
OTP_MAX_ATTEMPTS = 5
# ورود با رمز: بعد از این تعداد تلاش ناموفق، آن شناسه/IP برای چند دقیقه قفل می‌شود
PASSWORD_LOGIN_MAX_FAILS = 5
PASSWORD_LOGIN_LOCK_MINUTES = 15
# تا این مدت بعد از ورود پیامکی، تعیین رمز تازه بدون رمز فعلی مجاز است (فراموشی رمز)
PASSWORD_RESET_WINDOW_MINUTES = 15
LISTING_AUTO_APPROVE = env_bool("LISTING_AUTO_APPROVE", DEBUG)

# کارمزد واسطه‌گری (درصد) با سقف و کف به تومان
ESCROW_FEE_PERCENT = 5
ESCROW_FEE_MIN = 30_000
ESCROW_FEE_MAX = 2_000_000
# مهلت بررسی اکانت توسط خریدار بعد از تحویل (ساعت)
INSPECTION_HOURS = 72
# مهلت فروشنده برای تحویل اطلاعات بعد از پرداخت (ساعت)
SELLER_DELIVERY_HOURS = 24
# هزینه نردبان آگهی (تومان)
BOOST_PRICE = 25_000
