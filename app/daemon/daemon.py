from typing import List, Any, Dict
import os
from app.utils.timer import Ticker
from app.daemon.dto import Event
from app.core.database import Device, Mission
from app.models.schema import MissionCreate
from app.services.mission import create_mission
from databases import Database
from app.env import (
    FOXLINK_DB_USER,
    FOXLINK_DB_PWD,
    FOXLINK_DB_HOST,
    FOXLINK_DB_PORT,
)

unfinished_event_ids: Dict[int, bool] = {}


class FoxlinkDbPool:
    _db: Database
    _ticker: Ticker

    def __init__(self):
        self._db = Database(
            f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{FOXLINK_DB_HOST}:{FOXLINK_DB_PORT}"
        )

    async def connect(self):
        await self._db.connect()
        self._ticker = Ticker(self.fetch_events_from_foxlink, 10)

    async def close(self):
        await self._db.disconnect()
        self._ticker.stop()

    async def run_sql_statement(self, query: str, values) -> Any:
        return self._db.fetch_all(query=query, values=values)

    async def get_db_table_list(self, db_name: str) -> List[str]:
        r = await self.run_sql_statement(
            "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = %s",
            (db_name),
        )

        return [x[0] for x in r]

    async def get_recent_events(self, db_name: str) -> List[Event]:
        stmt = f"SELECT * FROM `{db_name}` WHERE ((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND End_Time is NULL;"
        rows = await self._db.fetch_all(query=stmt)

        return [
            Event(
                id=x[0],
                project=db_name,
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
        tables = await self.get_db_table_list("aoi")
        tables = [x for x in tables if x != "measure_info"]

        for t in tables:
            events = await self.get_recent_events(t)

            for e in events:
                unfinished_event_ids[e.id] = True

                try:
                    await Device.objects.get_or_create(
                        id=_generate_device_id(e),
                        project=e.project,
                        line=e.line,
                        device_name=e.device_name,
                        x_axis=0,
                        y_axis=0,
                    )

                    is_event_id_existed = await Mission.objects.filter(
                        related_event_id=e.id
                    ).exists()

                    if not is_event_id_existed:
                        await create_mission(
                            MissionCreate(
                                name="New Mission",
                                device=_generate_device_id(e),
                                description=e.message,
                                related_event_id=e.id,
                                required_expertises=[],
                            )
                        )
                except Exception as e:
                    raise Exception("cannot create device", e)


def _generate_device_id(event: Event) -> str:
    return f"{event.project}-{event.line}-{event.device_name}"

