import logging
from fastapi import FastAPI
from app.routes import (
    health,
    migration,
    user,
    auth,
    mission,
    factory_map,
    statistics,
    log,
)
from app.core.database import database
from app.daemon.daemon import FoxlinkDbPool
from app.services.mission import dispatch_routine
from app.utils.timer import Ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(factory_map.router)
app.include_router(migration.router)
app.include_router(statistics.router)
app.include_router(log.router)


foxlink_db = FoxlinkDbPool()
dispatcher = Ticker(dispatch_routine, 1)


@app.on_event("startup")
async def startup():
    await database.connect()
    await foxlink_db.connect()
    await dispatcher.start()


@app.on_event("shutdown")
async def shutdown():
    # await fetch_ticker.stop()
    await dispatcher.stop()
    await database.disconnect()
    await foxlink_db.close()
