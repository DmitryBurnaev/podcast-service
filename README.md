# Podcasts Service
Backend Service which can be used for creation a custom podcasts (sets of episodes) based on fetched public media resources.<br/>
This project provides a backend (API service) and is positioned as an updated version of [podcast application](https://github.com/DmitryBurnaev/podcast).

![GitHub Pipenv locked Python version](https://img.shields.io/github/pipenv/locked/python-version/DmitryBurnaev/podcast-service)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Content
+ [Project Description](#project-description)
+ [Install Project](#install-project)
+ [Run Project](#run-project)
+ [Useful Commands](#useful-commands)
+ [Env Variables](#environment-variables)
+ [License](#license)


### Project Description

#### Target 
This application can be used for creation your podcasts. <br/>
If you have any sounds (or YouTube videos as example) which you want to listen later, you can create podcast (via web interface) and attach your tracks to it <br/>
Created podcast (with prepared episodes) will have a direct link (to RSS feed), which can be used for adding your podcast to same podcast application (`Add by URL`) <br />
Adding and downloading each new episodes will refresh RSS-feed and your APP will be able to get them.

#### Tech Stack
+ python 3.11
+ [Starlette](https://www.starlette.io/) 
+ RQ (background tasks)
+ yt-dlp (download audio tracks from external media platforms)
+ redis (key-value storage + RQ)
+ ffmpeg (audio postprocessing)

#### Tech details
Technically project contains from 3 parts:

##### Starlette API service (run on `APP_PORT` from your env):
  + AUTH service (JWT-based)
  + PODCAST service (CRUD API for podcasts/episodes)
  + Some tools and engines for fetching episodes from external resources (YouTube as for now) 

##### Media storage (S3):  
  + episodes
  + generated RSS feeds 

##### Background application: RQ 
  + download sounds from requested resource
  + perform sound and prepare mp3 files with `ffmpeg`
  + generate RSS feed file (xml) with episodes (by specification https://cyber.harvard.edu/rss/rss.html)  



### Install Project

#### Prepare virtual environment
```shell script
cd "<PATH_TO_PROJECT>"
cp .env.template .env
# update variables to actual (redis, postgres, etc.)
```

#### Prepare extra resources (postgres | redis)
```shell script
export $(cat .env | grep -v ^# | xargs)
docker run --name postgres-etc -e POSTGRES_PASSWORD=${DATABASE_PASSWORD} -d postgres:10.11
docker run --name redis-etc -d redis
```

#### Create database
```shell script
export $(cat .env | grep -v ^# | xargs)
PGPASSWORD=${DATABASE_PASSWORD} psql -U${DATABASE_USER} -h${DATABASE_HOST} -p${DATABASE_PORT} -c "create database ${DATABASE_NAME};"
```

#### Apply migrations
```shell script
cd "<PATH_TO_PROJECT>" && make migrations_upgrade
```


### Run Project

+ Run via docker-containers (like in production mode)
```shell script
cd "<PATH_TO_PROJECT>" && docker-compose up --build
```

+ Run in develop-mode
```shell script
# install pipenv https://pypi.org/project/pipenv/
cd "<PATH_TO_PROJECT>"
pipenv install --dev
make run_web
# or 
make run_rq
```

### Useful commands

+ work with migrations 
```shell script
make migrations_create_auto   # auto-creation
make migrations_create_manual # manual-creation
make migrations_upgrade       # apply all migrations
make migrations_downgrade     # unapply with param `revision=1231`
make migrations_history       # show applied migrations

```

+ Run tests
```shell script
cd "<PATH_TO_PROJECT>"/src && pytest 
```

+ Apply formatting (`black`) and lint code (`pylint`)
```shell script
make lint
```

## Environment Variables

### REQUIRED Variables

| argument              |                    description                    |                          example |
|:----------------------|:-------------------------------------------------:|---------------------------------:|
| APP_HOST              | App default host running (used by docker compose) |                        127.0.0.1 |
| APP_PORT              | App default port running (used by docker compose) |                             9000 |
| APP_SERVICE           |  Run service (web/celery/test) via entrypoint.sh  |                              web |
| SECRET_KEY            |           Django secret key (security)            |             _abc3412j345j1f2d3f_ |
| SITE_URL              |   URL address to the UI-part of the podcast APP   |         https://podcast.site.com |
| SERVICE_URL           |   URL address to the BE-part of the podcast APP   | https://podcast-service.site.com |
| DB_HOST               |             PostgreSQL database host              |                        127.0.0.1 |
| DB_PORT               |             PostgreSQL database port              |                             5432 |
| DB_NAME               |             PostgreSQL database name              |                          podcast |
| DB_USERNAME           |           PostgreSQL database username            |                          podcast |
| DB_PASSWORD           |           PostgreSQL database password            |                  podcast_asf2342 |
| S3_STORAGE_URL        |            URL to S3-like file storage            |  https://s3.storage.endpoint.net |
| S3_ACCESS_KEY_ID      |             Public key to S3 storage              |                                  |
| S3_SECRET_ACCESS_KEY  |             Secret key to S3 storage              |                                  |
| S3_REGION_NAME        |                     S3 region                     |                                  |
| S3_BUCKET_NAME        |                     S3 bucket                     |                    podcast-media |
| S3_BUCKET_AUDIO_PATH  |                S3 dir for episodes                |                            audio |
| S3_BUCKET_IMAGES_PATH |    S3 dir for images (episode,podcast covers)     |                           images |
| S3_BUCKET_RSS_PATH    |          S3 dir for generated RSS feeds           |                              rss |

### OPTIONAL Variables

| argument                 |                    description                    |                         default |
|:-------------------------|:-------------------------------------------------:|--------------------------------:|
| JWT_EXPIRES_IN           |         Default time for token's lifespan         |                       300 (sec) |
| APP_DEBUG                |               Run app in debug mode               |                           False |
| LOG_LEVEL                |        Allows to set current logging level        |                           DEBUG |
| SENTRY_DSN               | Sentry dsn (if not set, error logs won't be sent) |                                 |
| REDIS_HOST               |                    Redis host                     |                       localhost |
| REDIS_PORT               |                    Redis port                     |                            6379 |
| REDIS_DB                 |                     Redis db                      |                               0 |
| REDIS_PROGRESS_PUBSUB_CH |    Subscribe channel name for progress events     |       channel:episodes-progress |
| DB_NAME_TEST             |         Custom name for DB name for tests         |             `DB_NAME` + `_test` |
| SENDGRID_API_KEY         | Is needed for sending Email (invite, passw., etc) |                                 |
| DB_ECHO                  |         Sending all db queries to stdout          |                           False |
| DB_ECHO                  |         Sending all db queries to stdout          |                           False |
| SMTP_HOST                |            SMTP host for sending email            |                                 |
| SMTP_PORT                |            SMTP port for sending email            |                             462 |
| SMTP_USERNAME            |         SMTP credential for sending email         |                                 |
| SMTP_PASSWORD            |         SMTP credential for sending email         |                                 |
| SMTP_STARTTLS            |               SMTP starttls config                |                                 |
| SMTP_USE_TLS             |                SMTP use tls config                |                            true |
| SMTP_FROM_EMAIL          |             Default email for sending             |                                 |
| SENS_DATA_ENCRYPT_KEY    |            Key for sensdata encryption            |      aa&nhn-k*a*7tq6i+22ks2ya5x |


* * *

### License

This product is released under the MIT license. See LICENSE for details.
