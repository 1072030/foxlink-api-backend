import databases
import ormar
import uuid
import traceback
import sqlalchemy
from datetime import date, timedelta, datetime, time
from typing import Optional, List, ForwardRef
from enum import Enum
from ormar import property_field, pre_update
from pydantic import Json
from sqlalchemy import MetaData, create_engine
from sqlalchemy.sql import func
from app.env import (
    DATABASE_HOST,
    DATABASE_PORT,
    DATABASE_USER,
    DATABASE_PASSWORD,
    DATABASE_NAME,
    DAY_SHIFT_BEGIN,
    DAY_SHIFT_END,
    PY_ENV,
    TZ,
)


DATABASE_URI = f"mysql+aiomysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

api_db = databases.Database(DATABASE_URI, max_size=50)

metadata = MetaData()

MissionRef = ForwardRef("Mission")
AuditLogHeaderRef = ForwardRef("AuditLogHeader")
UserRef = ForwardRef("User")
DeviceRef = ForwardRef("Device")


def generate_uuidv4():
    return str(uuid.uuid4())


def get_ntz_now():
    return datetime.now()


def get_ntz_min():
    return datetime.fromisoformat("1990-01-01 00:00:00")


def transaction(func):
    async def wrapper(*args, **_args):
        # print("in transaction wrapper",args,_args)
        transaction = await api_db.transaction(isolation="serializable")
        result = None
        try:
            result = await func(*args, **_args)
        except Exception as e:
            print(e)
            traceback.print_exc()
            await transaction.rollback()
            raise e
        else:
            await transaction.commit()
            return result

    return wrapper


class UserLevel(Enum):
    maintainer = 1  # 維修人員
    manager = 2  # 線長
    supervisor = 3  # 組長
    chief = 4  # 課級
    admin = 5  # 管理員


class ShiftType(Enum):
    day = 1
    night = 2


ShiftInterval = {
    ShiftType.day: [
        time.fromisoformat(DAY_SHIFT_BEGIN),
        time.fromisoformat(DAY_SHIFT_END)
    ],
    ShiftType.night: [
        time.fromisoformat(DAY_SHIFT_END),
        time.fromisoformat(DAY_SHIFT_BEGIN)
    ]
}


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


class Shift(ormar.Model):
    class Meta(MainMeta):
        pass
    id: int = ormar.Integer(primary_key=True, index=True, autoincrement=False, choices=list(ShiftType), nullable=False)
    shift_beg_time = ormar.Time(timezone=True, nullable=False)
    shift_end_time = ormar.Time(timezone=True, nullable=False)


class FactoryMap(ormar.Model):
    class Meta(MainMeta):
        tablename = "factory_maps"

    id: int = ormar.Integer(primary_key=True, index=True)
    name: str = ormar.String(max_length=100, index=True, unique=True)
    map: Json = ormar.JSON()
    related_devices: Json = ormar.JSON()
    image: bytes = ormar.LargeBinary(max_length=5242880, nullable=True)
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


class User(ormar.Model):
    class Meta(MainMeta):
        pass

    badge: str = ormar.String(primary_key=True, max_length=100, index=True)
    username: str = ormar.String(max_length=50, nullable=False)
    password_hash: str = ormar.String(max_length=100, nullable=True)
    workshop: FactoryMap = ormar.ForeignKey(FactoryMap, ondelete="SET NULL", nullable=True)
    superior: UserRef = ormar.ForeignKey(UserRef, on_delete="SET NULL", nullable=True)
    level: int = ormar.SmallInteger(choices=list(UserLevel), nullable=False)
    shift: Shift = ormar.ForeignKey(Shift, on_delete="SET NULL", nullable=True)
    change_pwd: bool = ormar.Boolean(server_default="0", nullable=True)
    ####################
    status: str = ormar.String(max_length=15, default=WorkerStatusEnum.leave, choices=list(WorkerStatusEnum))
    at_device: DeviceRef = ormar.ForeignKey(DeviceRef, ondelete="SET NULL", nullable=True)
    dispatch_count: int = ormar.Integer(default=0, nullable=True)
    check_alive_time: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    shift_beg_date: datetime = ormar.DateTime(default=get_ntz_min, timezone=True)
    finish_event_date: datetime = ormar.DateTime(default=get_ntz_min, timezone=True)
    ####################
    login_date: datetime = ormar.DateTime(default=get_ntz_min, timezone=True)
    logout_date: datetime = ormar.DateTime(default=get_ntz_min, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


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
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


class UserDeviceLevel(ormar.Model):
    class Meta(MainMeta):
        tablename = "user_device_levels"
        constraints = [ormar.UniqueColumns("device", "user")]

    id: int = ormar.Integer(primary_key=True, index=True)
    user: User = ormar.ForeignKey(User, index=True, ondelete="CASCADE", related_name="device_levels")
    device: Device = ormar.ForeignKey(Device, index=True, ondelete="CASCADE")
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


class MissionEvent(ormar.Model):
    class Meta(MainMeta):
        tablename = "mission_events"
        constraints = [ormar.UniqueColumns("event_id", "table_name", "mission")]

    id: int = ormar.Integer(primary_key=True)

    mission: MissionRef = ormar.ForeignKey(
        MissionRef,
        index=True,
        ondelete="CASCADE",
        related_name="events"
    )

    event_id: int = ormar.Integer(nullable=False)
    category: int = ormar.Integer(nullable=False)
    message: str = ormar.String(max_length=100, nullable=True)
    host: str = ormar.String(max_length=50, nullable=False)
    table_name: str = ormar.String(max_length=50, nullable=False)
    done_verified: bool = ormar.Boolean(default=False)
    event_beg_date: datetime = ormar.DateTime(nullable=True)
    event_end_date: datetime = ormar.DateTime(nullable=True)
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


class Mission(ormar.Model):

    class Meta(MainMeta):
        tablename = "missions"

    id: int = ormar.Integer(primary_key=True, index=True)
    device: Device = ormar.ForeignKey(Device, ondelete="CASCADE")
    worker: User = ormar.ForeignKey(User, ondelete="CASCADE", related_name="accepted_mission")
    rejections: Optional[List[User]] = ormar.ManyToMany(User, related_name="rejected_mission")
    name: str = ormar.String(max_length=100, nullable=False)
    description: str = ormar.String(max_length=256)

    is_emergency: bool = ormar.Boolean(default=False, nullable=True)
    is_cancel: bool = ormar.Boolean(default=False, nullable=True)
    is_overtime: bool = ormar.Boolean(default=False, nullable=True)
    is_autocanceled: bool = ormar.Boolean(default=False, nullable=True)
    is_lonely: bool = ormar.Boolean(default=False, nullable=True)  # if no worker could be assigned
    is_shifted: bool = ormar.Boolean(default=False, nullable=True)  # if mission complete due to shifting

    notify_send_date: datetime = ormar.DateTime(nullable=True)
    notify_recv_date: datetime = ormar.DateTime(nullable=True)

    accept_recv_date: datetime = ormar.DateTime(nullable=True)

    repair_beg_date: datetime = ormar.DateTime(nullable=True)
    repair_end_date: datetime = ormar.DateTime(nullable=True)

    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)

    @property_field
    def mission_duration(self) -> timedelta:
        if self.repair_end_date is not None:
            return self.repair_end_date - self.created_date
        else:
            return get_ntz_now() - self.created_date

    @property_field
    def repair_duration(self) -> Optional[timedelta]:
        if self.repair_beg_date is not None:
            if self.repair_end_date is not None:
                return self.repair_end_date - self.repair_beg_date
            else:
                return get_ntz_now() - self.repair_beg_date
        else:
            return None

    @property_field
    def assign_duration(self) -> Optional[timedelta]:
        if self.notify_send_date is not None:
            if self.repair_start_date is not None:
                return self.repair_start_date - self.notify_send_date
            else:
                return get_ntz_now() - self.notify_send_date
        else:
            return None

    @property_field
    def accept_duration(self) -> Optional[timedelta]:
        if self.notify_send_date is not None:
            if self.accept_recv_date is not None:
                return self.accept_recv_date - self.notify_send_date
            else:
                return get_ntz_now() - self.notify_send_date
        else:
            return None

    @property_field
    def is_accepted(self) -> bool:
        return self.accept_recv_date is not None

    @property_field
    def is_started(self) -> bool:
        return self.repair_beg_date is not None

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
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    description: str = ormar.String(max_length=256, nullable=True)


class WhitelistDevice(ormar.Model):

    class Meta(MainMeta):
        tablename = "whitelist_devices"

    id: int = ormar.Integer(primary_key=True)
    device: Device = ormar.ForeignKey(Device, unique=True, ondelete='CASCADE', nullable=False)
    workers: List[User] = ormar.ManyToMany(User, related_name="whitelist_devices")
    created_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)
    updated_date: datetime = ormar.DateTime(default=get_ntz_now, timezone=True)


MissionEvent.update_forward_refs()
User.update_forward_refs()


@pre_update([User, Device, FactoryMap, Mission, MissionEvent, UserDeviceLevel, WhitelistDevice])
async def before_update(sender, instance, **kwargs):
    instance.updated_date = get_ntz_now()
