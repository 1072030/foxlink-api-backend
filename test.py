import asyncio
import datetime
from app.core.database import api_db, Shift


async def main():
    await api_db.connect()
    transaction = api_db.transaction()
    try:
        await transaction.start()
        await (await Shift.objects.first()).update(shift_beg_time=datetime.time(0, 30))
        # raise Exception()
    except:
        await transaction.rollback()
    else:
        await transaction.commit()

asyncio.run(main())
