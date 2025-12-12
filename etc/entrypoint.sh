#!/bin/sh


if [ "${APP_SERVICE}" = "web" ]
  then
    cd /podcast && alembic upgrade head
    cd src && uvicorn asgi:app --host 0.0.0.0 --port 8000 --no-use-colors

elif [ "${APP_SERVICE}" = "rq" ]
  then
    cd /podcast && alembic upgrade head
    cd src && python -m worker podcast

elif [ "${APP_SERVICE}" = "test" ]
  then
    cd /podcast &&
    PYTHONPATH=$(pwd)/src pylint src/ && \
    PYTHONPATH=$(pwd)/src coverage run -m pytest && \
    coverage report

else
  echo "APP_SERVICE environment variable is unexpected or was not provided (APP_SERVICE='${APP_SERVICE}')" >&2
  kill -s SIGINT 1

fi
