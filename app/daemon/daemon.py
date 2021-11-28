from typing import List, Any
import asyncio
import aiomysql
import os

FOXLINK_DB_HOST = os.getenv("FOXLINK_DB_HOST")
FOXLINK_DB_PORT = os.getenv("FOXLINK_DB_PORT")
FOXLINK_DB_USER = os.getenv("FOXLINK_DB_USER")
FOXLINK_DB_PWD = os.getenv("FOXLINK_DB_PWD")
fetch_interval = 30  # sec


class FoxlinkDbPool:
    pool: aiomysql.Pool

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
        self.pool = task.result()

    async def run_sql_statement(self, stat: str, args=None) -> Any:
        if self.pool is None:
            raise RuntimeError("pool is not initialized")

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(stat, args)
                return await cur.fetchall()

    async def get_db_table_list(self, db_name: str) -> List[str]:
        r = await self.run_sql_statement(
            "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA = %s",
            (db_name),
        )

        return r
