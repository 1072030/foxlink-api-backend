from datetime import date, timedelta
from typing import List, Optional
from ormar import property_field
from pydantic import Json
from sqlalchemy import MetaData, create_engine
from sqlalchemy.sql import func
import os
import databases
import ormar
import sqlalchemy


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


class FactoryMap(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, index=True, unique=True)
    map: Json = ormar.JSON()
    created_date: date = ormar.DateTime(server_default=func.now())
    updated_date: date = ormar.DateTime(server_default=func.now(), onupdate=func.now())


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    email: str = ormar.String(max_length=100, unique=True, index=True)
    password_hash: str = ormar.String(max_length=100)
    full_name: str = ormar.String(max_length=50)
    expertises: sqlalchemy.JSON = ormar.JSON()
    location: Optional[FactoryMap] = ormar.ForeignKey(FactoryMap)
    is_active: bool = ormar.Boolean(server_default="1")
    is_admin: bool = ormar.Boolean(server_default="0")


class Machine(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, nullable=False)
    manual: Optional[str] = ormar.String(max_length=512)


class Device(ormar.Model):
    class Meta(MainMeta):
        pass

    id: str = ormar.String(max_length=100, primary_key=True, index=True)
    process: str = ormar.String(max_length=100, nullable=False)
    machine: str = ormar.String(max_length=100, nullable=False)
    line: int = ormar.Integer(nullable=False)
    device: int = ormar.Integer(nullable=False)
    x_axis: float = ormar.Float(nullable=False)
    y_axis: float = ormar.Float(nullable=False)
    created_date: date = ormar.DateTime(server_default=func.now())
    updated_date: date = ormar.DateTime(server_default=func.now(), onupdate=func.now())


class UserDeviceLevel(ormar.Model):
    class Meta(MainMeta):
        constraints = [ormar.UniqueColumns("device", "user")]

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device, index=True)
    user: User = ormar.ForeignKey(User, index=True)
    level: int = ormar.SmallInteger(minimum=0)


class Mission(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    machine: Machine = ormar.ForeignKey(Machine)
    assignee: Optional[User] = ormar.ForeignKey(User)
    name: str = ormar.String(max_length=100, nullable=False, unique=True)
    description: Optional[str] = ormar.String(max_length=256)
    created_date: date = ormar.DateTime(server_default=func.now())
    updated_date: date = ormar.DateTime(server_default=func.now(), onupdate=func.now())
    start_date: Optional[date] = ormar.DateTime(nullable=True)
    end_date: Optional[date] = ormar.DateTime(nullable=True)
    required_expertises: sqlalchemy.JSON = ormar.JSON()

    @property_field
    def duration(self) -> Optional[timedelta]:
        if self.start_date is not None and self.end_date is not None:
            return self.end_date - self.start_date
        return None


class RepairHistory(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    mission: Mission = ormar.ForeignKey(Mission)
    machine_status: Optional[str] = ormar.String(max_length=256, nullable=True)
    cause_of_issue: Optional[str] = ormar.String(max_length=512, nullable=True)
    issue_solution: Optional[str] = ormar.String(max_length=512, nullable=True)
    canceled_reason: Optional[str] = ormar.String(max_length=512, nullable=True)
    is_cancel: bool = ormar.Boolean()


engine = create_engine(DATABASE_URI)

metadata.create_all(engine)
