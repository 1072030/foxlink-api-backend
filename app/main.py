from fastapi import FastAPI
from dotenv import load_dotenv
from app.routes import health

load_dotenv()

app = FastAPI()
app.include_router(health.router)
