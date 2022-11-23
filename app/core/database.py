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

DATABASE_URI = f"mysql+aiomysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

api_db = databases.Database(DATABASE_URI, max_size=20)

metadata = MetaData()

MissionRef = ForwardRef("Mission")
AuditLogHeaderRef = ForwardRef("AuditLogHeader")
UserRef = ForwardRef("User")


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
    notice = 'Notice'
    moving = 'Moving'
    idle = "Idle"
    leave = "Leave"


class LogoutReasonEnum(Enum):
    meeting = "Meeting"
    leave = "Leave"
    rest = "Rest"
    offwork = "OffWork"


class AuditActionEnum(Enum):
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_REJECTED = "MISSION_REJECTED"
    MISSION_ACCEPTED = "MISSION_ACCEPTED"
    MISSION_ASSIGNED = "MISSION_ASSIGNED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_FINISHED = "MISSION_FINISHED"
    MISSION_DELETED = "MISSION_DELETED"
    MISSION_UPDATED = "MISSION_UPDATED"
    MISSION_OVERTIME = "MISSION_OVERTIME"
    MISSION_CANCELED = "MISSION_CANCELED"
    MISSION_USER_DUTY_SHIFT = "MISSION_USER_DUTY_SHIFT"
    MISSION_EMERGENCY = "MISSION_EMERGENCY"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    USER_MOVE_POSITION = "USER_MOVE_POSITION"
    DATA_IMPORT_FAILED = "DATA_IMPORT_FAILED"
    DATA_IMPORT_SUCCEEDED = "DATA_IMPORT_SUCCEEDED"

    NOTIFY_MISSION_NO_WORKER = "NOTIFY_MISSION_NO_WORKER"


class MainMeta(ormar.ModelMeta):
    metadata = metadata
    database = api_db


class FactoryMap(ormar.Model):
    class Meta(MainMeta):
        tablename = "factory_maps"

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, index=True, unique=True)
    map: Json = ormar.JSON()
    related_devices: Json = ormar.JSON()
    image: bytes = ormar.LargeBinary(max_length=5242880, nullable=True)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    username: str = ormar.String(primary_key=True, max_length=100, index=True)
    full_name: str = ormar.String(max_length=50,nullable=False)
    password_hash: str = ormar.String(max_length=100,nullable=True)
    workshop: FactoryMap = ormar.ForeignKey(FactoryMap, ondelete="SET NULL",nullable=True)
    superior: UserRef = ormar.ForeignKey(UserRef, on_delete="SET NULL",nullable=True)
    level: int = ormar.SmallInteger(choices=list(UserLevel),nullable=False)
    shift: int = ormar.SmallInteger(choices=list(ShiftType),nullable=True)
    change_pwd: bool = ormar.Boolean(server_default="0",nullable=True)  
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class Device(ormar.Model):
    class Meta(MainMeta):
        tablename = "devices"

    id: str = ormar.String(max_length=100, primary_key=True, index=True)
    project: str = ormar.String(max_length=50, nullable=False)
    process: str = ormar.String(max_length=50, nullable=True)
    line: int = ormar.Integer(nullable=True)
    device_name: str = ormar.String(max_length=20, nullable=False)
    device_cname: str = ormar.String(max_length=100, nullable=True)
    x_axis: float = ormar.Float(nullable=False)
    y_axis: float = ormar.Float(nullable=False)
    is_rescue: bool = ormar.Boolean(default=False)
    workshop: FactoryMap = ormar.ForeignKey(FactoryMap, index=True)
    sop_link: str = ormar.String(max_length=128, nullable=True)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class UserDeviceLevel(ormar.Model):
    class Meta(MainMeta):
        tablename = "user_device_levels"
        constraints = [ormar.UniqueColumns("device", "user")]

    id: int = ormar.Integer(primary_key=True, index=True)
    user: User = ormar.ForeignKey(User, index=True, ondelete="CASCADE")
    device: Device = ormar.ForeignKey(Device, index=True, ondelete="CASCADE")
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class MissionEvent(ormar.Model):
    class Meta(MainMeta):
        tablename = "mission_events"
        constraints = [ormar.UniqueColumns("event_id", "table_name", "mission")]

    id: int = ormar.Integer(primary_key=True)
    mission: MissionRef = ormar.ForeignKey(MissionRef, index=True, ondelete="CASCADE")  # type: ignore
    event_id: int = ormar.Integer()
    table_name: str = ormar.String(max_length=50)
    category: int = ormar.Integer(nullable=False)
    message: str = ormar.String(max_length=100, nullable=True)
    done_verified: bool = ormar.Boolean(default=False)
    event_start_date: datetime = ormar.DateTime(nullable=True)
    event_end_date: datetime = ormar.DateTime(nullable=True)
    host: str = ormar.String(max_length=50)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class Mission(ormar.Model):

    class Meta(MainMeta):
        tablename = "missions"

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device, ondelete="CASCADE")
    worker: User = ormar.ForeignKey(User, ondelete="CASCADE")
    name: str = ormar.String(max_length=100, nullable=False)
    description: str = ormar.String(max_length=256)
    repair_start_date: datetime = ormar.DateTime(nullable=True)
    repair_end_date: datetime = ormar.DateTime(nullable=True)
    is_cancel: bool = ormar.Boolean(default=False)
    is_emergency: bool = ormar.Boolean(default=False)
    is_autocanceled: bool = ormar.Boolean(default=False, nullable=False)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)

    @property_field
    def mission_duration(self) -> timedelta:
        if self.repair_end_date is not None:
            return self.repair_end_date - self.created_date
        else:
            return datetime.utcnow() - self.created_date

    @property_field
    def repair_duration(self) -> Optional[timedelta]:
        if self.repair_start_date is not None:
            if self.repair_end_date is not None:
                return self.repair_end_date - self.repair_start_date
            else:
                return datetime.utcnow() - self.repair_start_date
        else:
            return None

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


class LogValue(ormar.Model):

    class Meta(MainMeta):
        tablename = "log_values"

    id: int = ormar.Integer(primary_key=True, index=True)
    log_header: AuditLogHeaderRef = ormar.ForeignKey(AuditLogHeaderRef, ondelete="CASCADE")  # type: ignore
    field_name: str = ormar.String(max_length=100)
    previous_value: str = ormar.String(max_length=512)
    new_value: str = ormar.String(max_length=512)


class AuditLogHeader(ormar.Model):

    class Meta(MainMeta):
        tablename = "audit_log_headers"

    id: int = ormar.Integer(primary_key=True, index=True)
    action: str = ormar.String(
        max_length=50, nullable=False, index=True, choices=list(AuditActionEnum)
    )
    table_name: str = ormar.String(max_length=50, index=True)
    record_pk: str = ormar.String(max_length=100, index=True, nullable=True)
    user: User = ormar.ForeignKey(User, nullable=True, ondelete="SET NULL")
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    description: str = ormar.String(max_length=256, nullable=True)


class WorkerStatus(ormar.Model):

    class Meta(MainMeta):
        tablename = "worker_status"
        
    id: int = ormar.Integer(primary_key=True)
    worker: User = ormar.ForeignKey(User, unique=True, ondelete="CASCADE")
    at_device: Device = ormar.ForeignKey(Device, nullable=True, ondelete="SET NULL")
    status: str = ormar.String(max_length=15, choices=list(WorkerStatusEnum))
    last_event_end_date: datetime = ormar.DateTime(timezone=True)
    dispatch_count: int = ormar.Integer(default=0)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)    
    check_alive_time: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


class WhitelistDevice(ormar.Model):

    class Meta(MainMeta):
        tablename = "whitelist_devices"

    id: int = ormar.Integer(primary_key=True)
    device: Device = ormar.ForeignKey(Device, unique=True, ondelete='CASCADE', nullable=False)
    workers: List[User] = ormar.ManyToMany(User)
    created_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)
    updated_date: datetime = ormar.DateTime(server_default=func.now(), timezone=True)


MissionEvent.update_forward_refs()
LogValue.update_forward_refs()
User.update_forward_refs()


@pre_update([Device, FactoryMap, Mission, UserDeviceLevel, WorkerStatus, WhitelistDevice])
async def before_update(sender, instance, **kwargs):
    instance.updated_date = datetime.utcnow()