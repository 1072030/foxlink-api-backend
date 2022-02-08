#! /usr/bin/env bash

echo "API Server will wait 20 secound for the database to be ready"
sleep 20;
alembic upgrade head;