import logging
import os
from dotenv import load_dotenv
from app.my_log_conf import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

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
FOXLINK_DB_NAME = os.getenv("FOXLINK_DB_NAME")

JWT_SECRET = os.getenv("JWT_SECRET", "secret")

if PY_ENV == "production" and JWT_SECRET == "secret":
    logger.warn(
        "For security, JWT_SECRET is highly recommend to be set in production environment!!"
    )

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

if MQTT_BROKER == "":
    logger.error("MQTT_BROKER is not set")
    exit(1)

# Factory related configs
# Day shift: 07:40 ~ 19:40, Night shift: 19:40 ~ 07:40
DAY_SHIFT_BEGIN = os.getenv("DAY_SHIFT_BEGIN", "07:40")
DAY_SHIFT_END = os.getenv("DAY_SHIFT_END", "19:40")
NIGHT_SHIFT_BEGIN = os.getenv("NIGHT_SHIFT_BEGIN", "19:40")
NIGHT_SHIFT_END = os.getenv("NIGHT_SHIFT_END", "07:40")

