# /bin/bash

if [ "$1" = "--git" ]
then
    git pull origin
elif [ -z "$1" ]
then
    echo "Update without git pull"
else
    echo "Usage: update.sh --git"
    exit 1
fi

docker-compose kill foxlink-backend && docker-compose up -d --build foxlink-backend
docker-compose kill foxlink-daemon && docker-compose up -d --build foxlink-daemon
