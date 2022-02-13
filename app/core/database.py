from datetime import date, timedelta, datetime
from typing import Optional, List
from enum import Enum
from ormar import property_field, pre_update
from pydantic import Json
from sqlalchemy import MetaData, create_engine
from sqlalchemy.sql import func
import databases
import ormar
import sqlalchemy
import uuid
from app.env import (
    DATABASE_HOST,
    DATABASE_PORT,
    DATABASE_USER,
    DATABASE_PASSWORD,
    DATABASE_NAME,
    PY_ENV,
)

DATABASE_URI = f"mysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

database = databases.Database(DATABASE_URI)
metadata = MetaData()


def generate_uuidv4():
    return str(uuid.uuid4())


class UserLevel(Enum):
    maintainer = 0  # 維修人員
    manager = 1  # 線長
    supervisor = 2  # 組長
    chief = 3  # 課級
    # admin = 4 # 管理員


class ShiftClassType(Enum):
    day = "Day"
    night = "Night"


class MainMeta(ormar.ModelMeta):
    metadata = metadata
    database = database


class FactoryMap(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, index=True, unique=True)
    map: Json = ormar.JSON()
    created_date: datetime = ormar.DateTime(server_default=func.now())
    updated_date: datetime = ormar.DateTime(server_default=func.now())


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    id: str = ormar.String(
        primary_key=True, index=True, max_length=36, default=generate_uuidv4
    )
    username: str = ormar.String(max_length=100, unique=True, index=True)
    password_hash: str = ormar.String(max_length=100)
    full_name: str = ormar.String(max_length=50)
    expertises: sqlalchemy.JSON = ormar.JSON()
    location: Optional[FactoryMap] = ormar.ForeignKey(FactoryMap)
    is_active: bool = ormar.Boolean(server_default="1")
    is_admin: bool = ormar.Boolean(server_default="0")
    level: int = ormar.SmallInteger(nullable=False, choices=list(UserLevel))


class Device(ormar.Model):
    class Meta(MainMeta):
        pass

    id: str = ormar.String(max_length=100, primary_key=True, index=True)
    project: str = ormar.String(max_length=50, nullable=False)
    process: Optional[int] = ormar.Integer(nullable=True)
    line: int = ormar.Integer(nullable=True)
    device_name: str = ormar.String(max_length=20, nullable=False)
    x_axis: float = ormar.Float(nullable=False)
    y_axis: float = ormar.Float(nullable=False)
    is_rescue: bool = ormar.Boolean(default=False)
    workshop: FactoryMap = ormar.ForeignKey(FactoryMap, index=True)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class UserDeviceLevel(ormar.Model):
    class Meta(MainMeta):
        constraints = [ormar.UniqueColumns("device", "user")]

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device, index=True)
    user: User = ormar.ForeignKey(User, index=True)
    shift: bool = ormar.Boolean(nullable=False)
    level: int = ormar.SmallInteger(minimum=0)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class UserShiftInfo(ormar.Model):
    class Meta(MainMeta):
        constraints = [ormar.UniqueColumns("user", "shift_date")]

    id: int = ormar.Integer(primary_key=True, index=True)
    user: User = ormar.ForeignKey(User, index=True)
    devices: List[Device] = ormar.ManyToMany(Device)
    shift_date: date = ormar.Date()
    attend: bool = ormar.Boolean(default=True)
    day_or_night: str = ormar.String(max_length=5, choices=list(ShiftClassType))


class DeviceManageInfoManager(ormar.Model):
    class Meta(MainMeta):
        tablename = "deviceinfo_managers"

    id: int = ormar.Integer(primary_key=True)


class DeviceManageInfoSupervisor(ormar.Model):
    class Meta(MainMeta):
        tablename = "deviceinfo_supervisors"

    id: int = ormar.Integer(primary_key=True)


class DeviceManageInfoChief(ormar.Model):
    class Meta(MainMeta):
        tablename = "deviceinfo_chiefs"

    id: int = ormar.Integer(primary_key=True)


class DeviceManageInfo(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True)
    device: Device = ormar.ForeignKey(Device, index=True)
    managers: List[User] = ormar.ManyToMany(
        User, through=DeviceManageInfoManager, related_name="managers"
    )
    supervisors: List[User] = ormar.ManyToMany(
        User, through=DeviceManageInfoSupervisor, related_name="supervisors"
    )
    chiefs: List[User] = ormar.ManyToMany(
        User, through=DeviceManageInfoChief, related_name="chiefs"
    )
    date: date = ormar.Date()


class Mission(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device)
    assignees: List[User] = ormar.ManyToMany(User)
    name: str = ormar.String(max_length=100, nullable=False)
    description: Optional[str] = ormar.String(max_length=256)
    repair_start_date: Optional[date] = ormar.DateTime(nullable=True)
    repair_end_date: Optional[date] = ormar.DateTime(nullable=True)
    required_expertises: sqlalchemy.JSON = ormar.JSON()
    done_verified: bool = ormar.Boolean(default=False)
    related_event_id: int = ormar.Integer()
    machine_status: Optional[str] = ormar.String(max_length=256, nullable=True)
    cause_of_issue: Optional[str] = ormar.String(max_length=512, nullable=True)
    issue_solution: Optional[str] = ormar.String(max_length=512, nullable=True)
    canceled_reason: Optional[str] = ormar.String(max_length=512, nullable=True)
    image: Optional[bytes] = ormar.LargeBinary(
        max_length=1024 * 1024 * 5, default=bytes(0)
    )
    signature: Optional[bytes] = ormar.LargeBinary(
        max_length=1024 * 1024 * 5, default=bytes(0)
    )
    is_cancel: bool = ormar.Boolean(default=False)
    created_date: datetime = ormar.DateTime(server_default=func.now())
    updated_date: datetime = ormar.DateTime(server_default=func.now())
    event_start_date: Optional[datetime] = ormar.DateTime(nullable=True)
    event_end_date: Optional[datetime] = ormar.DateTime(nullable=True)

    @property_field
    def duration(self) -> Optional[timedelta]:
        if self.repair_start_date is not None and self.repair_end_date is not None:
            return self.repair_end_date - self.repair_start_date
        return None

    @property_field
    def is_started(self) -> bool:
        return self.repair_start_date is not None

    @property_field
    def is_closed(self) -> bool:
        return self.repair_end_date is not None


class AuditActionEnum(Enum):
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_REJECTED = "MISSION_REJECTED"
    USER_LOGIN = "USER_LOGIN"


class LogValue(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    field_name: str = ormar.String(max_length=100)
    previous_value: str = ormar.String(max_length=512)
    new_value: str = ormar.String(max_length=512)


class AuditLogHeader(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    action: str = ormar.String(
        max_length=50, nullable=False, index=True, choices=list(AuditActionEnum)
    )
    table_name: Optional[str] = ormar.String(max_length=50, index=True)
    record_pk: Optional[str] = ormar.String(max_length=100, index=True)
    user: User = ormar.ForeignKey(User)
    created_date: datetime = ormar.DateTime(server_default=func.now())
    values: List[LogValue] = ormar.ManyToMany(LogValue)


# Device's Category Priority
class CategoryPRI(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    category: int = ormar.Integer(nullable=False)
    priority: int = ormar.Integer(nullable=False)
    message: Optional[str] = ormar.String(max_length=100)
    devices: Optional[List[Device]] = ormar.ManyToMany(Device)


class WorkerStatus(ormar.Model):
    class Meta(MainMeta):
        tablename = "worker_status"

    id: int = ormar.Integer(primary_key=True)
    worker: User = ormar.ForeignKey(User)
    at_device: Device = ormar.ForeignKey(Device)
    last_event_end_date: Optional[datetime] = ormar.DateTime(nullable=True)
    dispatch_count: int = ormar.Integer(default=0)
    updated_date: datetime = ormar.DateTime(server_default=func.now())


@pre_update([Device, FactoryMap, Mission, UserDeviceLevel, WorkerStatus])
async def before_update(sender, instance, **kwargs):
    instance.updated_date = datetime.utcnow()


engine = create_engine(DATABASE_URI)

if PY_ENV == "dev":
    metadata.create_all(engine)
