import logging
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")
PY_ENV = os.getenv("PY_ENV", "production")

FOXLINK_DB_HOST = os.getenv("FOXLINK_DB_HOST")
FOXLINK_DB_PORT = os.getenv("FOXLINK_DB_PORT")
FOXLINK_DB_USER = os.getenv("FOXLINK_DB_USER")
FOXLINK_DB_PWD = os.getenv("FOXLINK_DB_PWD")

JWT_SECRET = os.getenv("JWT_SECRET", "secret")

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

if MQTT_BROKER == "":
    logging.error("MQTT_BROKER is not set")
    exit(1)
