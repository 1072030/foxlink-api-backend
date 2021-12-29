from app.core.database import database


async def get_top_most_crashed_devices(limit: int):
    result = await database.fetch_all(
        f"SELECT device, count(*) AS count FROM missions GROUP BY device ORDER BY count DESC LIMIT {limit}"
    )

    return result
