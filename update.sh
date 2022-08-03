# /bin/bash
git pull origin
docker-compose kill foxlink-backend && docker-compose up -d --build foxlink-backend
docker-compose kill foxlink-daemon && docker-compose up -d --build foxlink-daemon
