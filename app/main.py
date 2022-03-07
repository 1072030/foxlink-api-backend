import logging
from fastapi import FastAPI
from app.env import MQTT_BROKER, MQTT_PORT
from app.routes import (
    health,
    migration,
    mock,
    user,
    auth,
    mission,
    statistics,
    log,
    device,
    factorymap,
)
from app.core.database import database
from app.daemon.daemon import FoxlinkDbPool
from app.services.mission import dispatch_routine
from app.utils.timer import Ticker
from app.mqtt.main import connect_mqtt, disconnect_mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(migration.router)
app.include_router(statistics.router)
app.include_router(log.router)
app.include_router(device.router)
app.include_router(factorymap.router)
app.include_router(mock.router)


foxlink_db = FoxlinkDbPool()
dispatcher = Ticker(dispatch_routine, 10)


@app.on_event("startup")
async def startup():
    connect_mqtt(MQTT_BROKER, MQTT_PORT, "foxlink-api-server")
    await database.connect()
    await foxlink_db.connect()
    await dispatcher.start()
    # mock, test usage
    await mock._db.connect()


@app.on_event("shutdown")
async def shutdown():

    # mock, test usage
    await mock._db.disconnect()

    await dispatcher.stop()
    await foxlink_db.close()
    await database.disconnect()
    disconnect_mqtt()
