from enum import Enum
from typing import Any, Optional, List
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from app.core.database import (
    CategoryPRI,
    Device,
    Mission,
    MissionEvent,
    ShiftType,
    UserLevel,
    WorkerStatusEnum,
)

# * User
class WorkerAttendance(BaseModel):
    date: date
    login_datetime: datetime
    logout_datetime: Optional[datetime]
    logout_reason: Optional[str]


class WorkerSummary(BaseModel):
    total_accepted_count_this_week: int
    total_accepted_count_this_month: int
    total_rejected_count_this_week: int
    total_rejected_count_this_month: int


class UserBase(BaseModel):
    username: str
    full_name: str
    expertises: List[str]
    level: UserLevel


class UserCreate(UserBase):
    workshop: Optional[int]
    password: str


class UserPatch(BaseModel):
    full_name: Optional[str]
    expertises: Optional[List[str]]
    password: Optional[str]


class UserOut(UserBase):
    workshop: str
    is_active: bool
    is_admin: bool
    is_changepwd: bool


class UserOutWithWorkTimeAndSummary(UserOut):
    at_device: str
    work_time: int
    summary: Optional[WorkerSummary]


class UserChangePassword(BaseModel):
    old_password: str
    new_password: str


# * Mission
class MissionBase(BaseModel):
    description: Optional[str]


class MissionUpdate(MissionBase):
    name: Optional[str]
    device_id: Optional[str]
    is_cancel: Optional[bool]


class DeviceDto(BaseModel):
    device_id: str
    device_name: str
    device_cname: Optional[str]
    workshop: Optional[str]
    project: str
    process: Optional[str]
    line: Optional[int]


class UserNameDto(BaseModel):
    username: str
    full_name: str


class MissionEventOut(BaseModel):
    category: int
    message: str
    done_verified: bool
    event_start_date: datetime
    event_end_date: Optional[datetime]

    @classmethod
    def from_missionevent(cls, e: MissionEvent):
        return cls(
            category=e.category,
            message=e.message,
            done_verified=e.done_verified,
            event_start_date=e.event_start_date,
            event_end_date=e.event_end_date,
        )


class MissionDto(BaseModel):
    mission_id: int
    device: DeviceDto
    name: str
    description: str
    assignees: List[UserNameDto]
    events: List[MissionEventOut]
    is_started: bool
    is_closed: bool
    is_cancel: bool
    is_emergency: bool
    created_date: datetime
    updated_date: datetime

    @classmethod
    def from_mission(cls, m: Mission):
        return cls(
            mission_id=m.id,
            name=m.name,
            device=DeviceDto(
                device_id=m.device.id,
                device_name=m.device.device_name,
                device_cname=m.device.device_cname,
                workshop=m.device.workshop.name,
                project=m.device.project,
                process=m.device.process,
                line=m.device.line,
            ),
            description=m.description,
            is_started=m.is_started,
            is_closed=m.is_closed,
            is_cancel=m.is_cancel,
            is_emergency=m.is_emergency,
            assignees=[
                UserNameDto(username=u.username, full_name=u.full_name)
                for u in m.assignees
            ],
            events=[MissionEventOut.from_missionevent(e) for e in m.missionevents],
            created_date=m.created_date,
            updated_date=m.updated_date,
        )


class WorkerStatusDto(BaseModel):
    worker_id: str
    worker_name: str
    last_event_end_date: datetime
    at_device: Optional[str]
    status: WorkerStatusEnum
    total_dispatches: int
    mission_duration: Optional[float]


class SubordinateOut(WorkerStatusDto):
    shift: ShiftType


class ImportDevicesOut(BaseModel):
    device_ids: List[str]
    parameter: Optional[str]


class DeviceExp(BaseModel):
    project: str
    process: Optional[str]
    device_name: str
    line: int
    exp: int


class UserOverviewOut(BaseModel):
    username: str
    full_name: str
    workshop: Optional[str]
    level: int
    shift: Optional[ShiftType]
    superior: Optional[str]
    experiences: List[DeviceExp]


class DayAndNightUserOverview(BaseModel):
    day_shift: List[UserOverviewOut]
    night_shift: List[UserOverviewOut]


class DeviceOut(BaseModel):
    id: str
    project: str
    process: Optional[str]
    line: Optional[int]
    device_name: str
    device_cname: Optional[str]
    workshop: str
    x_axis: float
    y_axis: float
    is_rescue: bool
    sop_link: Optional[str]

    @classmethod
    def from_device(cls, device: Device):
        return cls(
            id=device.id,
            project=device.project,
            process=device.process,
            line=device.line,
            device_name=device.device_name,
            device_cname=device.device_cname,
            workshop=device.workshop.name,
            sop_link=device.sop_link,
            x_axis=device.x_axis,
            y_axis=device.y_axis,
            is_rescue=device.is_rescue,
        )


class CategoryPriorityDeviceInfo(BaseModel):
    device_id: str
    project: str
    line: int
    device_name: str


class CategoryPriorityOut(BaseModel):
    category: int
    priority: int
    message: str
    devices: List[CategoryPriorityDeviceInfo]

    @classmethod
    def from_categorypri(cls, pri: CategoryPRI):
        obj = cls(
            category=pri.category,
            priority=pri.priority,
            message=pri.message,
            devices=[],
        )

        if pri.devices is not None:
            obj.devices = [
                CategoryPriorityDeviceInfo(
                    device_id=x.id,
                    project=x.project,
                    line=x.line,
                    device_name=x.device_name,
                )
                for x in pri.devices
                if pri.devices is not None
            ]

        return obj


class WorkerMissionStats(BaseModel):
    username: str
    full_name: str
    count: int


class DeviceStatusEnum(Enum):
    working = 0
    repairing = 1
    halt = 2


class DeviceStatus(BaseModel):
    device_id: str
    x_axis: float
    y_axis: float
    status: DeviceStatusEnum
