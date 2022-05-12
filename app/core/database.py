from datetime import date, timedelta, datetime
from typing import Optional, List, ForwardRef
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

database = databases.Database(DATABASE_URI, echo=True)
metadata = MetaData()

MissionRef = ForwardRef("Mission")
AuditLogHeaderRef = ForwardRef("AuditLogHeader")


def generate_uuidv4():
    return str(uuid.uuid4())


class UserLevel(Enum):
    maintainer = 1  # 維修人員
    manager = 2  # 線長
    supervisor = 3  # 組長
    chief = 4  # 課級
    admin = 5  # 管理員


class ShiftType(Enum):
    day = 0
    night = 1


class WorkerStatusEnum(Enum):
    working = "Working"
    idle = "Idle"
    leave = "Leave"


class LogoutReasonEnum(Enum):
    meeting = "Meeting"
    leave = "Leave"
    rest = "Rest"
    offwork = "OffWork"


class MainMeta(ormar.ModelMeta):
    metadata = metadata
    database = database


class FactoryMap(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, index=True, unique=True)
    map: Json = ormar.JSON()
    related_devices: Json = ormar.JSON()
    image: bytes = ormar.LargeBinary(max_length=5242880, nullable=True)
    created_date: datetime = ormar.DateTime(server_default=func.now())
    updated_date: datetime = ormar.DateTime(server_default=func.now())


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    username: str = ormar.String(primary_key=True, max_length=100, index=True)
    password_hash: str = ormar.String(max_length=100)
    full_name: str = ormar.String(max_length=50)
    expertises: sqlalchemy.JSON = ormar.JSON()
    location: Optional[FactoryMap] = ormar.ForeignKey(FactoryMap, ondelete="SET NULL")
    is_active: bool = ormar.Boolean(server_default="1")
    is_admin: bool = ormar.Boolean(server_default="0")
    is_changepwd: bool = ormar.Boolean(server_default="0")
    level: int = ormar.SmallInteger(nullable=False, choices=list(UserLevel))


class Device(ormar.Model):
    class Meta(MainMeta):
        pass

    id: str = ormar.String(max_length=100, primary_key=True, index=True)
    project: str = ormar.String(max_length=50, nullable=False)
    process: Optional[str] = ormar.String(max_length=50, nullable=True)
    line: int = ormar.Integer(nullable=True)
    device_name: str = ormar.String(max_length=20, nullable=False)
    x_axis: float = ormar.Float(nullable=False)
    y_axis: float = ormar.Float(nullable=False)
    is_rescue: bool = ormar.Boolean(default=False)
    workshop: FactoryMap = ormar.ForeignKey(FactoryMap, index=True)
    sop_link: Optional[str] = ormar.String(max_length=128, nullable=True)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class UserDeviceLevel(ormar.Model):
    class Meta(MainMeta):
        constraints = [ormar.UniqueColumns("device", "user", "shift")]

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device, index=True, ondelete="CASCADE")
    user: User = ormar.ForeignKey(User, index=True, ondelete="CASCADE")
    superior: Optional[User] = ormar.ForeignKey(
        User, nullable=True, ondelete="SET NULL", related_name="superior",
    )
    shift: bool = ormar.Boolean(nullable=False, choices=list(ShiftType))
    level: int = ormar.SmallInteger(minimum=0)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class MissionEvent(ormar.Model):
    class Meta(MainMeta):
        constraints = [ormar.UniqueColumns("event_id", "table_name")]

    id: int = ormar.Integer(primary_key=True)
    mission: MissionRef = ormar.ForeignKey(MissionRef, index=True, ondelete="CASCADE")  # type: ignore
    event_id: int = ormar.Integer()
    table_name: str = ormar.String(max_length=50)
    category: int = ormar.Integer(nullable=False)
    message: Optional[str] = ormar.String(max_length=100, nullable=True)
    done_verified: bool = ormar.Boolean(default=False)
    event_start_date: Optional[datetime] = ormar.DateTime(nullable=True)
    event_end_date: Optional[datetime] = ormar.DateTime(nullable=True)


class Mission(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device)
    assignees: List[User] = ormar.ManyToMany(User)
    name: str = ormar.String(max_length=100, nullable=False)
    description: Optional[str] = ormar.String(max_length=256)
    repair_start_date: Optional[datetime] = ormar.DateTime(nullable=True)
    repair_end_date: Optional[datetime] = ormar.DateTime(nullable=True)
    required_expertises: sqlalchemy.JSON = ormar.JSON()
    is_cancel: bool = ormar.Boolean(default=False)
    is_emergency: bool = ormar.Boolean(default=False)
    created_date: datetime = ormar.DateTime(server_default=func.now())
    updated_date: datetime = ormar.DateTime(server_default=func.now())

    @property_field
    def duration(self) -> timedelta:
        if self.repair_start_date is not None and self.repair_end_date is not None:
            return self.repair_end_date - self.created_date
        # elif self.repair_start_date is not None and self.repair_end_date is None:
        #     return datetime.utcnow() - self.repair_start_date
        else:
            return datetime.utcnow() - self.created_date

    @property_field
    def is_started(self) -> bool:
        return self.repair_start_date is not None

    @property_field
    def is_closed(self) -> bool:
        return self.repair_end_date is not None

    @property_field
    async def is_done_events(self) -> bool:
        events = await MissionEvent.objects.filter(mission=self.id).all()

        if len([x for x in events if x.done_verified]) == len(events):
            return True
        else:
            return False


MissionEvent.update_forward_refs()


class AuditActionEnum(Enum):
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_REJECTED = "MISSION_REJECTED"
    MISSION_ACCEPTED = "MISSION_ACCEPTED"
    MISSION_ASSIGNED = "MISSION_ASSIGNED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_FINISHED = "MISSION_FINISHED"
    MISSION_DELETED = "MISSION_DELETED"
    MISSION_OVERTIME = "MISSION_OVERTIME"
    MISSION_CANCELED = "MISSION_CANCELED"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    USER_MOVE_POSITION = "USER_MOVE_POSITION"
    DATA_IMPORT_FAILED = "DATA_IMPORT_FAILED"
    DATA_IMPORT_SUCCEEDED = "DATA_IMPORT_SUCCEEDED"


class LogValue(ormar.Model):
    class Meta(MainMeta):
        pass

    id: int = ormar.Integer(primary_key=True, index=True)
    log_header: AuditLogHeaderRef = ormar.ForeignKey(AuditLogHeaderRef, ondelete="CASCADE")  # type: ignore
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
    record_pk: Optional[str] = ormar.String(max_length=100, index=True, nullable=True)
    user: Optional[User] = ormar.ForeignKey(User, nullable=True, ondelete="SET NULL")
    created_date: datetime = ormar.DateTime(server_default=func.now())
    description: Optional[str] = ormar.String(max_length=256, nullable=True)


LogValue.update_forward_refs()

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
    worker: User = ormar.ForeignKey(User, unique=True, ondelete="CASCADE")
    at_device: Device = ormar.ForeignKey(Device)
    status: str = ormar.String(max_length=15, choices=list(WorkerStatusEnum))
    last_event_end_date: datetime = ormar.DateTime()
    dispatch_count: int = ormar.Integer(default=0)
    updated_date: datetime = ormar.DateTime(server_default=func.now())
    check_alive_time: datetime = ormar.DateTime(server_default=func.now())


@pre_update([Device, FactoryMap, Mission, UserDeviceLevel, WorkerStatus])
async def before_update(sender, instance, **kwargs):
    instance.updated_date = datetime.utcnow()


engine = create_engine(DATABASE_URI)

if PY_ENV == "dev":
    # metadata.drop_all(engine)
    metadata.create_all(engine)
