#!/bin/sh

echo "${REGISTRY_URL}" > ~/deploy.log
supervisorctl stop podcast_service:
docker-compose down
supervisorctl start podcast_service:
echo y | docker image prune -a
supervisorctl status podcast_service:
