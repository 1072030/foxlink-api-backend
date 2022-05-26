import asyncio
from typing import Dict, List
from databases import Database
from app.env import (
    FOXLINK_DB_HOSTS,
    FOXLINK_DB_USER,
    FOXLINK_DB_PWD,
)


class FoxlinkDbPool:
    _dbs: List[Database] = []

    def __init__(self):
        for host in FOXLINK_DB_HOSTS:
            self._dbs += [
                Database(f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{host}")
            ]

    async def get_device_cname(self, workshop_name: str):
        main_db = self._dbs[0]

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

    async def get_database_names(self, db: Database):
        result = await db.fetch_all("SHOW DATABASES")
        return result

    async def connect(self):
        db_connect_routines = [db.connect() for db in self._dbs]
        await asyncio.gather(*db_connect_routines)

    async def close(self):
        db_disconnect_routines = [db.disconnect() for db in self._dbs]
        await asyncio.gather(*db_disconnect_routines)
