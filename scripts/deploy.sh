#!/bin/sh

docker pull podcast_service
supervisorctl stop podcast_service:
docker-compose down
supervisorctl start podcast_service:
echo y | docker image prune -a