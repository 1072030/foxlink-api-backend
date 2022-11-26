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
)
from app.core.database import api_db, Shift, ShiftType, ShiftInterval
from app.mqtt import mqtt_client
from app.log import LOGGER_NAME
from fastapi.middleware.cors import CORSMiddleware
from app.foxlink.db import foxlink_dbs
from app.daemon.daemon import _daemons


# dictConfig(LogConfig().dict())
logger = logging.getLogger(LOGGER_NAME)

app = FastAPI(title="Foxlink API Backend", version="0.0.1")

daemons =  []

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

if PY_ENV == 'dev':
    app.include_router(test.router)

@app.on_event("startup")
async def startup():
    # connect to databases
    await asyncio.gather(*[
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, str(uuid.uuid4())),
        api_db.connect(),
        foxlink_dbs.connect()
    ])
    logger.info("Foxlink API Server startup complete.")

    # check table exists
    if(await Shift.objects.count()==0):
        await Shift.objects.bulk_create(
            [
                Shift(
                    id=shift_type.value,
                    shift_beg_time=interval[0],
                    shift_end_time=interval[1]
                )
                for shift_type, interval in ShiftInterval.items()
            ]
        )


    # start background daemons
    for args in _daemons:
        daemons.append(
            await asyncio.create_subprocess_exec(
                sys.executable,'-m', *args,
            )
        )
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

    
    # stop background daemons
    await asyncio.gather(*[
        asyncio.wait_for(d.wait(), timeout=10)
        for d in daemons 
        if d.terminate() or True
    ])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080,reload=True,workers=1)