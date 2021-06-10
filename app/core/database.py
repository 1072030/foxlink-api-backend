import os
from sqlalchemy import MetaData, create_engine, Table, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
import databases

DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")

DATABASE_URI = f"mysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

database = databases.Database(DATABASE_URI)
metadata = MetaData()
Base = declarative_base()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("email", String(100), unique=True, index=True),
    Column("password_hash", String(100)),
    Column("full_name", String(50)),
    Column("phone", String(20)),
    Column("is_active", Boolean, server_default="1"),
)


engine = create_engine(DATABASE_URI)

metadata.create_all(engine)
