#!/bin/sh

if [ "${DEPLOY_MODE}" != "CI" ]
  then
    echo "=== reading $(pwd)/.env file ==="
    export $(cat .env | grep -v ^# | grep -v ^EMAIL | xargs)
fi

echo "=== reading $(pwd)/.version file ==="
export $(cat .version | grep -v ^# | xargs)

echo "=== pulling image '${DOCKER_IMAGE}' ==="
docker pull ${DOCKER_IMAGE}

echo "=== restarting service ==="
supervisorctl stop podcast-service:
docker-compose down
supervisorctl start podcast-service:

echo "=== clearing ==="
echo y | docker image prune -a

echo "=== check status ==="
supervisorctl status podcast-service:

echo "=== show containers ==="
sleep 15
docker ps --format "table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}\t|" | grep podcast
echo "==="
