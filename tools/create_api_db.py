from os import system
import mysql.connector
import asyncio
from app.env import (
    DATABASE_HOST,
    DATABASE_PORT,
    DATABASE_USER,
    DATABASE_PASSWORD,
    DATABASE_NAME
)
from app.core.database import metadata, create_engine, Shift, ShiftInterval, api_db, User

print(f"Working at Foxlink DB")
connection = mysql.connector.connect(
    host=DATABASE_HOST,
    user=DATABASE_USER,
    password=DATABASE_PASSWORD,
    port=DATABASE_PORT
)
cursor = connection.cursor()
##### DROP  TABLE #####
print("Dropping table...")
try:
    cursor.execute(
        f"""DROP DATABASE {DATABASE_NAME};"""
    )
    connection.commit()
except Exception as e:
    print(e)
##### BUILD TABLE ######
print("Creating table...")
try:
    cursor.execute(
        f"""CREATE DATABASE {DATABASE_NAME};"""
    )
    connection.commit()
except Exception as e:
    print(e)
##### BUILD SCHEMA ######
print("Creating Schema...")
try:
    # engine = create_engine(
    #     f"mysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}")
    # metadata.create_all(engine)
    
    system("rm -rf /code/app/alembic/versions/* 2> /dev/null")
    system("alembic revision --autogenerate -m 'initialize'")
    system("alembic upgrade head")
except Exception as e:
    print(e)


##### BUILD DEFAULTS ######
async def create_default_entries():
    await api_db.connect()
    # check table exists
    if (await Shift.objects.count() == 0):
        await Shift.objects.bulk_create(
            [
                Shift(
                    id=shift_type.value,
                    shift_beg_time=interval[0],
                    shift_end_time=interval[1]
                )
                for shift_type, interval in ShiftInterval.items()
            ]
        )

    if (await User.objects.count() == 0):
        await User.objects.create(
            badge='admin',
            username='admin',
            password_hash='$5$rounds=535000$fbZ4FKqPVjA70Bv2$Ox9gFhfGxOqAydiRGU6LTMmqzmsjGSVivX1RQGdHTcB',
            workshop=None,
            superior=None,
            current_UUID=0,
            change_pwd=0,
            status=None,
            shift=None,
            level=5
        )
    await api_db.disconnect()
print("Creating Default Entries...")
try:
    asyncio.run(create_default_entries())
except Exception as e:
    print(e)


##### END #######
print("All done!")
