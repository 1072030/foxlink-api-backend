from typing import Any, Optional, List
from pydantic import BaseModel
import datetime
from app.core.database import Mission, MissionEvent, ShiftType, UserLevel


# * User
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


class UserOut(UserBase):
    workshop: str
    is_active: bool
    is_admin: bool
    is_changepwd: bool

class UserOutWithWorkTime(UserOut):
    work_time: int

class UserChangePassword(BaseModel):
    old_password: str
    new_password: str


# * Mission
class MissionBase(BaseModel):
    description: Optional[str]


class MissionCreate(MissionBase):
    name: str
    device: str
    required_expertises: List[str]
    related_event_id: Optional[int]


class MissionUpdate(MissionBase):
    name: Optional[str]
    device_id: Optional[str]


class DeviceDto(BaseModel):
    device_id: str
    device_name: str
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
    event_start_date: datetime.datetime
    event_end_date: Optional[datetime.datetime]

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
    created_date: datetime.datetime
    updated_date: datetime.datetime

    @classmethod
    def from_mission(cls, m: Mission):
        return cls(
            mission_id=m.id,
            name=m.name,
            device=DeviceDto(
                device_id=m.device.id,
                device_name=m.device.device_name,
                project=m.device.project,
                process=m.device.process,
                line=m.device.line,
            ),
            description=m.description,
            is_started=m.is_started,
            is_closed=m.is_closed,
            is_cancel=m.is_cancel,
            assignees=[UserNameDto(username=u.username, full_name=u.full_name) for u in m.assignees],
            events=[MissionEventOut.from_missionevent(e) for e in m.missionevents],
            created_date=m.created_date,
            updated_date=m.updated_date,
        )


class SubordinateOut(BaseModel):
    username: str
    full_name: str
    shift: ShiftType

class ImportDevicesOut(BaseModel):
    device_ids: List[str]
    parameters: Optional[Any]