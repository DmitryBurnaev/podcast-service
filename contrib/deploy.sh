#!/bin/sh

echo "${REGISTRY_URL}_111" > ~/deploy.log
echo "${PROD_SSH_HOST}_222" >> ~/deploy.log
supervisorctl stop podcast_service:
docker-compose down
supervisorctl start podcast_service:
echo y | docker image prune -a
supervisorctl status podcast_service:
exit 0
