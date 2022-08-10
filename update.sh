# /bin/bash

if [ "$1" = "--git"] then
    git pull origin
fi

docker-compose kill foxlink-backend && docker-compose up -d --build foxlink-backend
docker-compose kill foxlink-daemon && docker-compose up -d --build foxlink-daemon
