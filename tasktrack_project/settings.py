import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 't', 'yes', 'y', 'on'}


def _env_list(name, default=''):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(',') if item.strip()]


def _database_config():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.getenv('SQLITE_NAME', str(BASE_DIR / 'db.sqlite3')),
        }

    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()
    if scheme in {'postgres', 'postgresql'}:
        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed.path.lstrip('/'),
            'USER': unquote(parsed.username or ''),
            'PASSWORD': unquote(parsed.password or ''),
            'HOST': parsed.hostname or '',
            'PORT': str(parsed.port or ''),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
            'CONN_HEALTH_CHECKS': True,
        }

    if scheme == 'sqlite':
        db_path = parsed.path
        if db_path.startswith('/'):
            db_path = db_path[1:]
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': db_path or str(BASE_DIR / 'db.sqlite3'),
        }

    raise ImproperlyConfigured(
        'Unsupported DATABASE_URL scheme. Use postgres://, postgresql://, or sqlite:///'
    )


def _env_proxy_ssl_header(name):
    raw = os.getenv(name, '').strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(',', 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ImproperlyConfigured(
            f'{name} must be in the format HEADER_NAME,expected_value (e.g. HTTP_X_FORWARDED_PROTO,https).'
        )
    return parts[0], parts[1]


DEBUG = _env_bool('DJANGO_DEBUG', default=True)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-key-change-me'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY is required when DJANGO_DEBUG is False.')

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', default='127.0.0.1,localhost')
CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS')


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    'core',
    'accounts',
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

ROOT_URLCONF = "tasktrack_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = "tasktrack_project.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {'default': _database_config()}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = os.getenv('DJANGO_LANGUAGE_CODE', 'en-us')

TIME_ZONE = os.getenv('DJANGO_TIME_ZONE', 'UTC')

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', default=not DEBUG)
SESSION_COOKIE_SECURE = _env_bool('DJANGO_SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = _env_bool('DJANGO_CSRF_COOKIE_SECURE', default=not DEBUG)
SECURE_PROXY_SSL_HEADER = _env_proxy_ssl_header('DJANGO_SECURE_PROXY_SSL_HEADER')
USE_X_FORWARDED_HOST = _env_bool('DJANGO_USE_X_FORWARDED_HOST', default=False)
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS',
    default=not DEBUG,
)
SECURE_HSTS_PRELOAD = _env_bool('DJANGO_SECURE_HSTS_PRELOAD', default=not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = _env_bool('DJANGO_SECURE_CONTENT_TYPE_NOSNIFF', default=True)
SECURE_REFERRER_POLICY = os.getenv('DJANGO_SECURE_REFERRER_POLICY', 'same-origin')

DJANGO_LOG_LEVEL = os.getenv('DJANGO_LOG_LEVEL', 'INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'structured': {
            'format': (
                'ts=%(asctime)s level=%(levelname)s logger=%(name)s '
                'module=%(module)s msg=%(message)s'
            ),
            'datefmt': '%Y-%m-%dT%H:%M:%S%z',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'structured',
        },
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': DJANGO_LOG_LEVEL, 'propagate': False},
        'core': {'handlers': ['console'], 'level': DJANGO_LOG_LEVEL, 'propagate': False},
    },
}

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
