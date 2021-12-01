from fastapi import FastAPI
from app.routes import (
    health,
    machine,
    migration,
    repairhistory,
    user,
    auth,
    mission,
    factory_map,
)
from app.core.database import database
from app.daemon.daemon import fetch_events_from_foxlink
from app.utils.timer import Ticker

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(machine.router)
app.include_router(repairhistory.router)
app.include_router(factory_map.router)
app.include_router(migration.router)

# fetch events ticker
fetch_ticker = Ticker(fetch_events_from_foxlink, 10)  # per 5 secs


@app.on_event("startup")
async def startup():
    await database.connect()
    await fetch_ticker.start()


@app.on_event("shutdown")
async def shutdown():
    await fetch_ticker.stop()
    await database.disconnect()
