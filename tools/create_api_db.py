import mysql.connector
from app.core.database import metadata,create_engine
from app.env import (
    DATABASE_HOST,
    DATABASE_PORT,
    DATABASE_USER,
    DATABASE_PASSWORD,
    DATABASE_NAME
)

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
print("Createing table...")
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
    engine = create_engine(f"mysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}")
    metadata.create_all(engine)
except Exception as e:
    print(e)


##### END #######
print("All done!")