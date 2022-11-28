#! /usr/bin/env bash
echo "The API server will wait for 10 secound to let the database ready."
sleep 10;
alembic upgrade head;