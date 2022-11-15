docker commit foxlink-api-backend-incubator-1 incubator:latest
docker compose rm -fs  incubator 
docker compose build incubator
docker compose create incubator
docker compose start incubator