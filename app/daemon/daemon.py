from typing import List, Any
import asyncio
import aiomysql
import os

from app.daemon.dto import Event
from app.core.database import Device, Mission
from app.models.schema import MissionCreate
from app.services.mission import create_mission


FOXLINK_DB_HOST = os.getenv("FOXLINK_DB_HOST")
FOXLINK_DB_PORT = os.getenv("FOXLINK_DB_PORT")
FOXLINK_DB_USER = os.getenv("FOXLINK_DB_USER")
FOXLINK_DB_PWD = os.getenv("FOXLINK_DB_PWD")


class FoxlinkDbPool:
    _pool: aiomysql.Pool

    def __init__(self, loop):
        task = asyncio.create_task(
            aiomysql.create_pool(
                host=FOXLINK_DB_HOST,
                port=(3306 if FOXLINK_DB_PORT is None else int(FOXLINK_DB_PORT)),
                user=FOXLINK_DB_USER,
                password=FOXLINK_DB_PWD,
                db="mysql",
                autocommit=True,
            )
        )

        loop.run_until_complete(task)
        self._pool = task.result()

    def close(self):
        self._pool.close()

    async def run_sql_statement(self, stat: str, args=None) -> Any:
        if self._pool is None:
            raise RuntimeError("pool is not initialized")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(stat, args)
                return await cur.fetchall()

    async def get_db_table_list(self, db_name: str) -> List[str]:
        r = await self.run_sql_statement(
            "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = %s",
            (db_name),
        )

        return [x[0] for x in r]

    async def get_recent_events(self, db_name: str) -> List[Event]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                stmt = f"SELECT * FROM `{db_name}` WHERE ((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND End_Time is NULL;"

                await cur.execute("USE aoi;")
                await cur.execute(stmt)

                r = await cur.fetchall()

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
                    for x in r
                ]


def _generate_device_id(event: Event) -> str:
    return f"{event.project}-{event.line}-{event.device_name}"


loop = asyncio.get_event_loop()

try:
    dbPool = FoxlinkDbPool(loop)
except:
    print("cannot initialize foxlink db pool")
    exit(1)


async def fetch_events_from_foxlink():
    events = await dbPool.get_recent_events("x61 e75_event_new")
    for e in events:
        try:
            await Device.objects.get_or_create(
                id=_generate_device_id(e),
                project=e.project,
                line=e.line,
                device_name=e.device_name,
                x_axis=0,
                y_axis=0,
            )

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

