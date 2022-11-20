#!/bin/bash
docker compose kill mysql-test
docker compose rm -f mysql-test
docker compose build mysql-test
docker compose create mysql-test
docker compose start mysql-test

