import logging, importlib
from fastapi import FastAPI
from app.env import MQTT_BROKER, MQTT_PORT, PY_ENV
from logging.config import dictConfig
from app.routes import (
    health,
    migration,
    user,
    auth,
    mission,
    statistics,
    log,
    device,
    workshop,
)
from app.core.database import database
from app.daemon.daemon import FoxlinkDbPool
from app.background_service import main_routine
from app.utils.timer import Ticker
from app.mqtt.main import connect_mqtt, disconnect_mqtt
from app.my_log_conf import LOGGER_NAME, LogConfig

if PY_ENV == "dev":
    mock = importlib.import_module("app.routes.mock")

dictConfig(LogConfig().dict())
logger = logging.getLogger(LOGGER_NAME)

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(migration.router)
app.include_router(statistics.router)
app.include_router(log.router)
app.include_router(device.router)
app.include_router(workshop.router)

if PY_ENV == "dev":
    logger.info("Creating mock router for dev mode")
    app.include_router(mock.router)  # type: ignore


foxlink_db = FoxlinkDbPool()
dispatcher = Ticker(main_routine, 10)


@app.on_event("startup")
async def startup():
    connect_mqtt(MQTT_BROKER, MQTT_PORT, "foxlink-api-server")
    await database.connect()
    await foxlink_db.connect()
    await dispatcher.start()
    # mock, test usage
    if PY_ENV == "dev":
        await mock._db.connect()
    logger.info("Foxlink API Server startup complete.")


@app.on_event("shutdown")
async def shutdown():
    # mock, test usage
    if PY_ENV == "dev":
        await mock._db.disconnect()

    await dispatcher.stop()
    await foxlink_db.close()
    await database.disconnect()
    disconnect_mqtt()
