from fastapi import FastAPI
from dotenv import load_dotenv
from app.routes import health, machine, user, auth, mission
from app.core.database import database

app = FastAPI(title="Foxlink API Backend", version="0.0.1")
app.include_router(health.router)
app.include_router(user.router)
app.include_router(auth.router)
app.include_router(mission.router)
app.include_router(machine.router)


@app.on_event("startup")
async def startup():
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

