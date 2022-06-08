import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy.engine.url import URL
from starlette.config import Config
from starlette.datastructures import Secret

SETTINGS_PATH = Path(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = Path(os.path.dirname(SETTINGS_PATH))
PROJECT_ROOT_DIR = Path(os.path.dirname(BASE_DIR))

config = Config(PROJECT_ROOT_DIR / ".env")

APP_HOST = config("APP_HOST", default="0.0.0.0")
APP_PORT = config("APP_PORT", default="8000")
APP_DEBUG = config("APP_DEBUG", cast=bool, default=False)

SECRET_KEY = config("SECRET_KEY", default="podcast-project-secret")

TEST_MODE = "test" in sys.argv[0]

DB_NAME = config("DB_NAME", default="podcast")
if TEST_MODE:
    DB_NAME = config("DB_NAME_TEST", default="podcast_test")

DATABASE = {
    "driver": "postgresql+asyncpg",
    "host": config("DB_HOST", default=None),
    "port": config("DB_PORT", cast=int, default=None),
    "username": config("DB_USERNAME", default=None),
    "password": config("DB_PASSWORD", cast=Secret, default=None),
    "database": DB_NAME,
    "pool_min_size": config("DB_POOL_MIN_SIZE", cast=int, default=1),
    "pool_max_size": config("DB_POOL_MAX_SIZE", cast=int, default=16),
    "ssl": config("DB_SSL", default=None),
    "use_connection_for_request": config("DB_USE_CONNECTION_FOR_REQUEST", cast=bool, default=True),
    "retry_limit": config("DB_RETRY_LIMIT", cast=int, default=1),
    "retry_interval": config("DB_RETRY_INTERVAL", cast=int, default=1),
}
DATABASE_DSN = config(
    "DB_DSN",
    cast=str,
    default=URL.create(
        drivername=DATABASE["driver"],
        username=DATABASE["username"],
        password=DATABASE["password"],
        host=DATABASE["host"],
        port=DATABASE["port"],
        database=DATABASE["database"],
    ),
)
DB_ECHO = config("DB_ECHO", cast=bool, default=False)

REDIS_HOST = config("REDIS_HOST", default="localhost")
REDIS_PORT = config("REDIS_PORT", default=6379)
REDIS_DB = config("REDIS_DB", default=0)
REDIS_CON = (REDIS_HOST, REDIS_PORT, REDIS_DB)
RQ_QUEUE_NAME = config("RQ_QUEUE_NAME", default="podcast")


TMP_PATH = Path(tempfile.mkdtemp(prefix="podcast__"))
TMP_AUDIO_PATH = Path(tempfile.mkdtemp(prefix="podcast_audio__"))
TMP_RSS_PATH = Path(tempfile.mkdtemp(prefix="podcast_rss__"))
TMP_IMAGE_PATH = Path(tempfile.mkdtemp(prefix="podcast_images__"))
TMP_COOKIES_PATH = Path(tempfile.mkdtemp(prefix="podcast_cookies__"))
TEMPLATE_PATH = BASE_DIR / "templates"

JWT_EXPIRES_IN = config("JWT_EXPIRES_IN", default=(5 * 60), cast=int)  # 5 min
JWT_REFRESH_EXPIRES_IN = 30 * 24 * 3600  # 30 days
JWT_ALGORITHM = "HS512"  # see https://pyjwt.readthedocs.io/en/latest/algorithms.html for details

S3_STORAGE_URL = config("S3_STORAGE_URL")
S3_AWS_ACCESS_KEY_ID = config("S3_AWS_ACCESS_KEY_ID")
S3_AWS_SECRET_ACCESS_KEY = config("S3_AWS_SECRET_ACCESS_KEY")
S3_REGION_NAME = config("S3_REGION_NAME")

S3_BUCKET_NAME = config("S3_BUCKET_NAME", default="podcast")
S3_BUCKET_AUDIO_PATH = config("S3_BUCKET_AUDIO_PATH", default="audio/")
S3_BUCKET_RSS_PATH = config("S3_BUCKET_RSS_PATH", default="rss/")
S3_BUCKET_IMAGES_PATH = config("S3_BUCKET_IMAGES_PATH", default="images/")
S3_BUCKET_EPISODE_IMAGES_PATH = Path(os.path.join(S3_BUCKET_IMAGES_PATH, "episodes"))
S3_BUCKET_PODCAST_IMAGES_PATH = Path(os.path.join(S3_BUCKET_IMAGES_PATH, "podcasts"))
S3_LINK_EXPIRES_IN = config("S3_LINK_EXPIRES_IN", default=600, cast=int)
S3_LINK_CACHE_EXPIRES_IN = config("S3_LINK_CACHE_EXPIRES_IN", default=120, cast=int)

# TODO: upload images with persistent public links
DEFAULT_EPISODE_COVER = config("DEFAULT_EPISODE_COVER", default="episode-default.jpg")
DEFAULT_PODCAST_COVER = config("DEFAULT_PODCAST_COVER", default="podcast-default.jpg")

SENDGRID_API_KEY = config("SENDGRID_API_KEY")
SENDGRID_API_VERSION = "v3"
EMAIL_FROM = config("EMAIL_FROM", default="").strip("'\"")
INVITE_LINK_EXPIRES_IN = 3 * 24 * 3600  # 3 day
RESET_PASSWORD_LINK_EXPIRES_IN = 3 * 3600  # 3 hours

SITE_URL = config("SITE_URL", default="") or "https://podcast.site.com"
SERVICE_URL = config("SERVICE_URL", default="") or "https://podcast-service.site.com/"

DOWNLOAD_EVENT_REDIS_TTL = 60 * 60  # 60 minutes
RQ_DEFAULT_TIMEOUT = 24 * 3600  # 24 hours
FFMPEG_TIMEOUT = 2 * 60 * 60  # 2 hours
DEFAULT_LIMIT_LIST_API = 20
MAX_UPLOAD_ATTEMPT = config("MAX_UPLOAD_ATTEMPT", default=5, cast=int)
RETRY_UPLOAD_TIMEOUT = 1  # 1 second
REQUEST_IP_HEADER = config("REQUEST_IP_HEADER", default="X-Real-IP", cast=str)

SENTRY_DSN = config("SENTRY_DSN", default=None)
LOG_LEVEL = config("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%d.%m.%Y %H:%M:%S",
        },
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "loggers": {
        "uvicorn": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "modules": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "common": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "app": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "youtube_dl": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "rq.worker": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
