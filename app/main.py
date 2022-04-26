import logging
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
from fastapi.middleware.cors import CORSMiddleware


dictConfig(LogConfig().dict())
logger = logging.getLogger(LOGGER_NAME)

app = FastAPI(title="Foxlink API Backend", version="0.0.1")

# Adding CORS middleware
origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://140.118.157.9:43114",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Adding routers
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(migration.router)
app.include_router(statistics.router)
app.include_router(log.router)
app.include_router(device.router)
app.include_router(workshop.router)


foxlink_db = FoxlinkDbPool()
dispatcher = Ticker(main_routine, 10)


@app.on_event("startup")
async def startup():
    connect_mqtt(MQTT_BROKER, MQTT_PORT, "foxlink-api-server")
    await database.connect()
    await foxlink_db.connect()
    await dispatcher.start()
    logger.info("Foxlink API Server startup complete.")


@app.on_event("shutdown")
async def shutdown():
    await dispatcher.stop()
    await foxlink_db.close()
    await database.disconnect()
    disconnect_mqtt()
