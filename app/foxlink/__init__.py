import asyncio
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from databases import Database
from pydantic import BaseModel
from app.env import (
    FOXLINK_DB_NAME,
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
    start_time: datetime
    end_time: Optional[datetime]
    message: Optional[str]
    start_file_name: Optional[str]
    end_file_name: Optional[str]

class FoxlinkDatabasePool:
    _dbs: Dict[str,Database] = {}

    def __init__(self):
        self._dbs = {
            host: Database(
                f"mysql+aiomysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{host}/{FOXLINK_DB_NAME}",
                min_size=5,
                max_size=20,
            )
            for host in FOXLINK_DB_HOSTS
        }      

    def __getitem__(self,key):
        return self._dbs[key]

    async def get_device_cname(self, workshop_name: str):
        main_db = self._dbs.values()[0]

        all_cnames = await main_db.fetch_all(
            "SELECT Device_CName, Device_EName FROM `sfc`.`dev_func`"
        )

        cnames_dict: Dict[str, str] = {v: k for k, v in all_cnames}

        query = f"""
            SELECT distinct Project 
            FROM `sfc`.`device_setting` ds 
            WHERE ds.IP like (
                select concat('%', IP_Address, '%')
                from `sfc`.`layout_mapping` lm
                where lm.Layout = :workshop_name
            ) and Project != ''
        """

        project_names = await main_db.fetch_all(query, {"workshop_name": workshop_name})

        async def worker(p: str):
            return await main_db.fetch_all(
                """
                select Project, Line, Device_Name, Dev_Func
                from `sfc`.`device_setting` ds
                where `Project` = :project and `Device_Name` not like '%Repeater%';
                """,
                {"project": p},
            )

        resp = await asyncio.gather(*(worker(p[0]) for p in project_names))

        device_infos = {}

        for item in resp:
            device_infos[item[0]["Project"]] = [dict(x) for x in item]

        for _, v in device_infos.items():
            for info in v:
                split_ename = info["Dev_Func"].split(",")
                info["Dev_Func"] = [cnames_dict[x] for x in split_ename]
                info["Line"] = int(info["Line"])

        if device_infos == {}:
            return None

        return device_infos

    async def get_db_tables(self,host:str) -> Tuple[List[str],str]:
        r = await self._dbs[host].fetch_all(
            "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = :schema_name",
            {
                "schema_name": FOXLINK_DB_NAME,
            },
        )
        return (
            host,
            [x[0] for x in r if "events" in x[0]]
        )

    async def get_all_db_tables(self) -> List[List[str]]:
        get_table_names_routines = [self.get_db_tables(host) for host in self._dbs.keys()]
        return await asyncio.gather(*get_table_names_routines)

    async def connect(self):
        db_connect_routines = [db.connect() for db in self._dbs.values()]
        await asyncio.gather(*db_connect_routines)

    async def disconnect(self):
        db_disconnect_routines = [db.disconnect() for db in self._dbs.values()]
        await asyncio.gather(*db_disconnect_routines)

def generate_device_id(event: FoxlinkEvent) -> str:
    project = event.project.split(" ")[0]
    return f"{project}@{event.line}@{event.device_name}"

foxlink_dbs = FoxlinkDatabasePool()