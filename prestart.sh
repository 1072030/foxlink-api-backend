#! /usr/bin/env bash

echo "API Server will wait 10 secound for the database to be ready"
sleep 10;
alembic upgrade head;