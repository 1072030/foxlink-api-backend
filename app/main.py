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
import asyncio
from app.core.database import database
from app.daemon.daemon import fetch_events_from_foxlink

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(machine.router)
app.include_router(repairhistory.router)
app.include_router(factory_map.router)
app.include_router(migration.router)


@app.on_event("startup")
async def startup():
    await database.connect()
    await fetch_events_from_foxlink()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
