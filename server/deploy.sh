#!/bin/sh

if [ "${DEPLOY_MODE}" != "CI" ]
  then
    echo "=== reading $(pwd)/.env file ==="
    export $(cat .env | grep -v ^# | grep -v ^EMAIL | xargs)
fi

echo "=== pulling image ${REGISTRY_URL}/podcast-service:last ==="
docker-compose pull

echo "=== restarting service ==="
supervisorctl stop podcast_service:
docker-compose down
supervisorctl start podcast_service:

echo "=== clearing ==="
#echo y | docker image prune -a

echo "=== check status ==="
supervisorctl status podcast_service:
