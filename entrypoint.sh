#!/bin/sh


if [ "${APP_SERVICE}" = "web" ]
  then
    cd /podcast && alembic upgrade head
    cd src && uvicorn asgi:app --host 0.0.0.0 --port 8000 --no-use-colors

elif [ "${APP_SERVICE}" = "rq" ]
  then
    cd /podcast && alembic upgrade head
    cd src && python -m worker youtube_downloads

elif [ "${APP_SERVICE}" = "test" ]
  then
    cd /podcast &&
    flake8 --count && \
    PYTHONPATH=$(pwd)/src coverage run -m pytest && \
    coverage report

elif [ "${APP_SERVICE}" = "migrate_db" ]
  then
    cd /podcast && alembic upgrade head

else
  echo "ENV environment variable is unexpected or was not provided (ENV='${ENV}')" >&2
  kill -s SIGINT 1

fi
