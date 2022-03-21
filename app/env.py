import logging
import os
from typing import TypeVar, Optional, Type
from dotenv import load_dotenv
from app.my_log_conf import LOGGER_NAME

T = TypeVar("T")


def get_env(
    key: str, type_: Type[T], default: Optional[T] = None, panic_on_none: bool = False
) -> Optional[T]:
    val = os.getenv(key)

    if val is None:
        if default is not None:
            if panic_on_none:
                raise KeyError(f"{key} is not set")
            return default
        else:
            return None
    else:
        return type_(val)  # type: ignore


logger = logging.getLogger(LOGGER_NAME)

load_dotenv()


DATABASE_HOST = get_env("DATABASE_HOST", str)
DATABASE_PORT = get_env("DATABASE_PORT", int)
DATABASE_USER = get_env("DATABASE_USER", str)
DATABASE_PASSWORD = get_env("DATABASE_PASSWORD", str)
DATABASE_NAME = get_env("DATABASE_NAME", str)
PY_ENV = get_env("PY_ENV", str, "production")

if PY_ENV not in ["production", "dev"]:
    logger.error("PY_ENV env should be either production or dev!")
    exit(1)

FOXLINK_DB_HOST = get_env("FOXLINK_DB_HOST", str)
FOXLINK_DB_PORT = get_env("FOXLINK_DB_PORT", int)
FOXLINK_DB_USER = get_env("FOXLINK_DB_USER", str)
FOXLINK_DB_PWD = get_env("FOXLINK_DB_PWD", str)
FOXLINK_DB_NAME = get_env("FOXLINK_DB_NAME", str)

JWT_SECRET = get_env("JWT_SECRET", str, "secret")

if PY_ENV == "production" and JWT_SECRET == "secret":
    logger.warn(
        "For security, JWT_SECRET is highly recommend to be set in production environment!!"
    )

# MQTT
MQTT_BROKER = get_env("MQTT_BROKER", str)
MQTT_PORT = get_env("MQTT_PORT", int, 1883)

if MQTT_BROKER is None:
    logger.error("MQTT_BROKER is not set")
    exit(1)

# Factory related configs
# Day shift: 07:40 ~ 19:40, Night shift: 19:40 ~ 07:40
WORKER_REJECT_AMOUNT_NOTIFY = get_env("WORKER_REJECT_AMOUNT_NOTIFY", int, 2)
MISSION_REJECT_AMOUT_NOTIFY = get_env("MISSION_REJECT_AMOUT_NOTIFY", int, 2)
DAY_SHIFT_BEGIN = get_env("DAY_SHIFT_BEGIN", str, "07:40")
DAY_SHIFT_END = get_env("DAY_SHIFT_END", str, "19:40")
NIGHT_SHIFT_BEGIN = get_env("NIGHT_SHIFT_BEGIN", str, "19:40")
NIGHT_SHIFT_END = get_env("NIGHT_SHIFT_END", str, "07:40")

