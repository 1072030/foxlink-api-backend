import datetime
from typing import List, Dict, Optional

from pydantic import BaseModel
from app.utils.timer import Ticker
from app.core.database import Device, Mission
from app.models.schema import MissionCreate
from app.services.mission import create_mission
from app.core.database import Mission
from databases import Database
from app.env import (
    FOXLINK_DB_USER,
    FOXLINK_DB_PWD,
    FOXLINK_DB_HOST,
    FOXLINK_DB_PORT,
)

unfinished_event_ids: Dict[int, bool] = {}

db_name = "aoi"


class Event(BaseModel):
    id: int
    project: str
    line: str
    device_name: str
    category: int
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime]
    message: Optional[str]
    start_file_name: Optional[str]
    end_file_name: Optional[str]


class FoxlinkDbPool:
    _db: Database
    _ticker: Ticker

    def __init__(self):
        self._db = Database(
            f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{FOXLINK_DB_HOST}:{FOXLINK_DB_PORT}"
        )
        self._ticker = Ticker(self.fetch_events_from_foxlink, 3)

    async def get_database_names(self):
        result = await self._db.fetch_all("SHOW DATABASES")
        return result

    async def connect(self):
        await self._db.connect()
        await self._ticker.start()

    async def close(self):
        await self._db.disconnect()
        await self._ticker.stop()

    async def get_db_table_list(self, db_name: str) -> List[str]:
        r = await self._db.fetch_all(
            "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = :table_name",
            {"table_name": db_name},
        )

        return [x[0] for x in r]

    async def get_recent_events(self, db_name: str, table_name: str) -> List[Event]:
        stmt = f"SELECT * FROM `{db_name}`.`{table_name}` WHERE ((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND End_Time is NULL ORDER BY Start_Time DESC;"
        rows = await self._db.fetch_all(query=stmt)

        return [
            Event(
                id=x[0],
                project=table_name,
                line=x[1],
                device_name=x[2],
                category=x[3],
                start_time=x[4],
                end_time=x[5],
                message=x[6],
                start_file_name=x[7],
                end_file_name=x[8],
            )
            for x in rows
        ]

    async def fetch_events_from_foxlink(self):
        tables = await self.get_db_table_list(db_name)
        tables = [x for x in tables if x != "measure_info"]

        for table_name in tables:
            events = await self.get_recent_events(db_name, table_name)

            for e in events:
                m = await Mission.objects.filter(related_event_id=e.id).get_or_none()

                if m is not None:
                    continue

                device = await Device.objects.filter(
                    id=self.generate_device_id(e)
                ).get()

                await Mission.objects.create(
                    device=device,
                    related_event_id=e.id,
                    category=e.category,
                    event_start_date=e.start_time,
                    name=f"{device.id} 故障",
                    required_expertises=[],
                    description=e.message,
                )

    def generate_device_id(self, event: Event) -> str:
        return f"{event.project}-{event.line}-{event.device_name}"

