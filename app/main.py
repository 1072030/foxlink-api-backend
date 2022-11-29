import sys
import uuid
import logging
import asyncio
import multiprocessing as mp
from fastapi import FastAPI
from app.env import MQTT_BROKER, MQTT_PORT, PY_ENV
from logging.config import dictConfig
from app.routes import (
    health,
    migration,
    test,
    user,
    auth,
    mission,
    statistics,
    log,
    device,
    workshop,
    shift
)
from app.core.database import api_db, Shift, ShiftType, ShiftInterval
from app.mqtt import mqtt_client
from app.log import LOGGER_NAME
from fastapi.middleware.cors import CORSMiddleware
from app.foxlink.db import foxlink_dbs


# dictConfig(LogConfig().dict())
logger = logging.getLogger(LOGGER_NAME)

app = FastAPI(title="Foxlink API Backend", version="0.0.1")


# Adding CORS middleware
origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://140.118.157.9:43114",
    "http://192.168.65.210:8083",
    "http://140.118.157.9:8086",
    "http://ntust.foxlink.com.tw",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex="http(?:s)?://(?:.+\.)?foxlink\.com\.tw(?::\d+)?",
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
app.include_router(test.router)
app.include_router(shift.router)

if PY_ENV == 'dev':
    app.include_router(test.router)


@app.on_event("startup")
async def startup():
    # connect to databases
    await asyncio.gather(*[
        mqtt_client.connect(),
        api_db.connect(),
        foxlink_dbs.connect()
    ])

    logger.info("Foxlink API Server startup complete.")


@app.on_event("shutdown")
async def shutdown():
    # disconnect databases
    await asyncio.gather(*[
        mqtt_client.disconnect(),
        api_db.disconnect(),
        foxlink_dbs.disconnect()
    ])
    logger.info("Foxlink API Server shutdown complete.")
