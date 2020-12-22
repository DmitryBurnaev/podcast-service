#!/bin/sh

export $(cat .env | grep -v ^# | grep -v ^EMAIL | xargs)

echo "Pulling image ${REGISTRY_URL}/podcast-service:last..." >> ./deploy.log
docker pull ${REGISTRY_URL}/podcast-service:last

echo "Restarting service..." >> ./deploy.log
supervisorctl stop podcast_service:
docker-compose down
supervisorctl start podcast_service:

echo "Clearing..." >> ./deploy.log
#echo y | docker image prune -a
supervisorctl status podcast_service:
exit 0
