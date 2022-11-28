import sys
import asyncio
import signal
from app.env import *
from app.main import app
from app.server_uvicorn import startup_daemons

startup_daemons()
