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


@app.on_event("startup")
async def startup():
    await database.connect()
    await foxlink_db.connect()


@app.on_event("shutdown")
async def shutdown():
    # await fetch_ticker.stop()
    await database.disconnect()
    await foxlink_db.close()
