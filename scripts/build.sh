bash scripts/servers.sh rebuild
sleep 5
docker compose exec foxlink-backend bash scripts/rebuild_database.sh