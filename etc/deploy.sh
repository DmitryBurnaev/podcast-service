#!/bin/sh

if [ "${DEPLOY_MODE}" != "CI" ]
  then
    echo "=== reading $(pwd)/.env file ==="
    export $(cat .env | grep -v ^# | grep -v ^EMAIL | xargs)
fi

echo "=== pulling image ${REGISTRY_PREFIX}/${IMAGE_NAME}:${IMAGE_TAG} ==="
docker pull ${REGISTRY_PREFIX}/${IMAGE_NAME}:${IMAGE_TAG}

echo "=== restarting service ==="
supervisorctl stop podcast-service:
docker-compose down
supervisorctl start podcast-service:

echo "=== clearing ==="
echo y | docker image prune -a

echo "=== check status ==="
supervisorctl status podcast-service:
