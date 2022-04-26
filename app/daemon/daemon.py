import asyncio
import datetime
from typing import List, Optional, Tuple
from pydantic import BaseModel
from app.utils.timer import Ticker
from app.core.database import Device, Mission, CategoryPRI, MissionEvent
from databases import Database
from app.env import (
    FOXLINK_DB_HOSTS,
    FOXLINK_DB_USER,
    FOXLINK_DB_PWD,
)


class FoxlinkEvent(BaseModel):
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
    _dbs: List[Database] = []
    _ticker: Ticker
    # table_name_blacklist: List[str] = ["measure_info"]
    table_suffix = "_event_new"
    db_name = "aoi"

    def __init__(self):
        for host in FOXLINK_DB_HOSTS:
            self._dbs += [
                Database(f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{host}")
            ]
        self._ticker = Ticker(self.fetch_events_from_foxlink, 3)
        self._2ndticker = Ticker(self.check_events_is_complete, 10)

    async def get_database_names(self, db: Database):
        result = await db.fetch_all("SHOW DATABASES")
        return result

    async def connect(self):
        db_connect_routines = [db.connect() for db in self._dbs]
        await asyncio.gather(*db_connect_routines)
        await self._ticker.start()
        await self._2ndticker.start()

    async def close(self):
        await self._2ndticker.stop()
        await self._ticker.stop()
        db_disconnect_routines = [db.disconnect() for db in self._dbs]
        await asyncio.gather(*db_disconnect_routines)

    async def get_db_table_list(self) -> List[List[str]]:
        async def get_db_tables(db: Database) -> List[str]:
            r = await db.fetch_all(
                "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = :table_name",
                {"table_name": self.db_name},
            )

            table_names = [x[0] for x in r if x[0].endswith(self.table_suffix)]
            return table_names
            # return [x for x in table_names if x not in self.table_name_blacklist]

        get_table_names_routines = [get_db_tables(db) for db in self._dbs]
        table_names = await asyncio.gather(*get_table_names_routines)
        return [n for n in table_names]

    async def get_a_event_from_table(
        self, db: Database, table_name: str, id: int
    ) -> Optional[FoxlinkEvent]:
        stmt = f"SELECT * FROM `{self.db_name}`.`{table_name}` WHERE ID = :id;"

        try:
            row: list = await db.fetch_one(query=stmt, values={"id": id})  # type: ignore

            return FoxlinkEvent(
                id=row[0],
                project=table_name,
                line=row[1],
                device_name=row[2],
                category=row[3],
                start_time=row[4],
                end_time=row[5],
                message=row[6],
                start_file_name=row[7],
                end_file_name=row[8],
            )
        except:
            return None

    async def get_recent_events(
        self, db: Database, table_name: str
    ) -> List[FoxlinkEvent]:
        stmt = f"SELECT * FROM `{self.db_name}`.`{table_name}` WHERE ((Category >= 1 AND Category <= 199) OR (Category >= 300 AND Category <= 699)) AND End_Time is NULL AND Start_Time >= CURRENT_TIMESTAMP() - INTERVAL 1 DAY ORDER BY Start_Time DESC;"
        rows = await db.fetch_all(query=stmt)

        return [
            FoxlinkEvent(
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

    async def check_events_is_complete(self):
        incomplete_mission_events = await MissionEvent.objects.filter(
            event_end_date__isnull=True
        ).all()

        async def validate_event(db: Database, event: MissionEvent):
            e = await self.get_a_event_from_table(db, event.table_name, event.event_id)
            if e is None:
                return False
            if e.end_time is not None:
                await event.update(event_end_date=e.end_time, done_verified=True)
                return True
            return False

        for event in incomplete_mission_events:
            validate_routines = [validate_event(db, event) for db in self._dbs]
            await asyncio.gather(*validate_routines)

    async def fetch_events_from_foxlink(self):
        tables = await self.get_db_table_list()

        for db_idx in range(len(tables)):
            db = self._dbs[db_idx]
            for table_name in tables[db_idx]:
                events = await self.get_recent_events(db, table_name)

                for e in events:
                    mission_event = await MissionEvent.objects.filter(
                        event_id=e.id, table_name=table_name
                    ).get_or_none()

                    if mission_event is not None:
                        continue

                    device_id = self.generate_device_id(e)

                    # if this device's priority is not existed in `CategoryPRI` table, which means it's not an out-of-order event.
                    # Thus, we should skip it.
                    priority = await CategoryPRI.objects.filter(
                        devices__id__iexact=device_id, category=e.category
                    ).get_or_none()

                    if priority is None:
                        continue

                    device = await Device.objects.filter(id__iexact=device_id).get()

                    # find if this device is already in a mission
                    mission = await Mission.objects.filter(
                        device=device.id, repair_end_date__isnull=True, is_cancel=False
                    ).get_or_none()

                    if mission is not None:
                        await MissionEvent.objects.create(
                            mission=mission.id,
                            event_id=e.id,
                            table_name=table_name,
                            category=e.category,
                            message=e.message,
                            event_start_date=e.start_time,
                        )
                    else:
                        new_mission = Mission(
                            device=device,
                            name=f"{device.id} 故障",
                            required_expertises=[],
                            description="",
                        )
                        await new_mission.save()
                        await new_mission.missionevents.add(
                            MissionEvent(
                                mission=new_mission.id,
                                event_id=e.id,
                                table_name=table_name,
                                category=e.category,
                                message=e.message,
                                event_start_date=e.start_time,
                            )
                        )

    def generate_device_id(self, event: FoxlinkEvent) -> str:
        project = event.project.split(" ")[0]
        return f"{project}@{event.line}@{event.device_name}"

