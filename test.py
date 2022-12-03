import asyncio
from app.core.database import api_db, User


async def main():
    await api_db.connect()
    while True:
        await asyncio.sleep(1)
        await User.objects.get()
        print("succeed")


if __name__ == "__main__":
    asyncio.run(main())
