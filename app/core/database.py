from datetime import date
import os
import databases
import ormar
from sqlalchemy import MetaData, create_engine, Table, Column, Integer, String, Boolean
from sqlalchemy.sql import func
from sqlalchemy.sql.schema import ForeignKey
from sqlalchemy.sql.sqltypes import Date, DateTime


DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")

DATABASE_URI = f"mysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

database = databases.Database(DATABASE_URI)
metadata = MetaData()


class MainMeta(ormar.ModelMeta):
    metadata = metadata
    database = database


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    email: str = ormar.String(max_length=100, unique=True, index=True)
    password_hash: str = ormar.String(max_length=100)
    full_name: str = ormar.String(max_length=50)
    phone: str = ormar.String(max_length=20)
    is_active: bool = ormar.Boolean(server_default="1")


class Machine(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, nullable=False)
    manual: str = ormar.String(max_length=512)


class Mission(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    machine: Machine = ormar.ForeignKey(Machine)
    name: str = ormar.String(max_length=100, nullable=False)
    description: str = ormar.String(max_length=256)
    created_date: date = ormar.DateTime(server_default=func.now())
    updated_date: date = ormar.DateTime(server_default=func.now(), onupdate=func.now())
    closed_date: date = ormar.DateTime()


engine = create_engine(DATABASE_URI)

metadata.create_all(engine)
