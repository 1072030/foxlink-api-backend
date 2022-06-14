import logging
import os
from typing import List, TypeVar, Optional, Type
from dotenv import load_dotenv
from app.my_log_conf import LOGGER_NAME
from ast import literal_eval

T = TypeVar("T")


def get_env(key: str, dtype: Type[T], default: Optional[T] = None) -> T:
    val = os.getenv(key)

    if val is None:
        if default is not None:
            return default
        else:
            if os.environ.get("USE_ALEMBIC") is None:
                raise KeyError(f"{key} is not set")
            else:
                return None #type: ignore
    else:
        if dtype is List[int] or dtype is List[str]:
            return literal_eval(val)
        else:
            return dtype(val)  # type: ignore


logger = logging.getLogger(LOGGER_NAME)

load_dotenv()

DATABASE_HOST = get_env("DATABASE_HOST", str)
DATABASE_PORT = get_env("DATABASE_PORT", int)
DATABASE_USER = get_env("DATABASE_USER", str)
DATABASE_PASSWORD = get_env("DATABASE_PASSWORD", str)
DATABASE_NAME = get_env("DATABASE_NAME", str)
PY_ENV = get_env("PY_ENV", str, "production")

FOXLINK_DB_HOSTS = get_env("FOXLINK_DB_HOSTS", List[str])
FOXLINK_DB_USER = get_env("FOXLINK_DB_USER", str)
FOXLINK_DB_PWD = get_env("FOXLINK_DB_PWD", str)
FOXLINK_DB_NAME = get_env("FOXLINK_DB_NAME", str, "aoi")

JWT_SECRET = get_env("JWT_SECRET", str, "secret")

# MQTT
MQTT_BROKER = get_env("MQTT_BROKER", str)
MQTT_PORT = get_env("MQTT_PORT", int, 1883)
# EMQX default admin account is (username: admin, password: public)
EMQX_USERNAME = get_env("EMQX_USERNAME", str, "admin")
EMQX_PASSWORD = get_env("EMQX_PASSWORD", str, "public")

# Factory related configs
# Day shift: 07:40 ~ 19:40, Night shift: 19:40 ~ 07:40
WORKER_REJECT_AMOUNT_NOTIFY = get_env("WORKER_REJECT_AMOUNT_NOTIFY", int, 2)
MISSION_REJECT_AMOUT_NOTIFY = get_env("MISSION_REJECT_AMOUT_NOTIFY", int, 2)
DAY_SHIFT_BEGIN = get_env("DAY_SHIFT_BEGIN", str, "07:40")
DAY_SHIFT_END = get_env("DAY_SHIFT_END", str, "19:40")
MAX_NOT_ALIVE_TIME = get_env("MAX_NOT_ALIVE_TIME", int, 5)  # unit: minutes


OVERTIME_MISSION_NOTIFY_PERIOD = get_env(
    "OVERTIME_MISSION_NOTIFY_PERIOD", List[int], [20, 10, 10]
)

# 當員工身處非 Rescue Station 時，若超過此時間，則自動派遣這名員工到 Rescue Station
MOVE_TO_RESCUE_STATION_TIME = get_env(
    "MOVE_TO_RESCUE_STATION_TIME", int, 5
)  # unit: minutes")


if os.environ.get("USE_ALEMBIC") is None:
    if PY_ENV not in ["production", "dev"]:
        logger.error("PY_ENV env should be either production or dev!")
        exit(1)

    if PY_ENV == "production" and JWT_SECRET == "secret":
        logger.warn(
            "For security, JWT_SECRET is highly recommend to be set in production environment!!"
        )

    if len(FOXLINK_DB_HOSTS) == 0:
        logger.error("FOXLINK_DB_HOSTS env should not be empty!")
        exit(1)

    if MQTT_BROKER is None:
        logger.error("MQTT_BROKER is not set")
        exit(1)

