from typing import Optional, List
from pydantic import BaseModel
import datetime
from app.core.database import UserLevel


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
    is_active: bool
    is_admin: bool
    is_changepwd: bool


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


class MissionDto(BaseModel):
    mission_id: int
    device: "DeviceDto"
    name: str
    description: str
    assignees: List[str]
    is_started: bool
    is_closed: bool
    done_verified: bool
    event_start_date: Optional[datetime.datetime]
    event_end_date: Optional[datetime.datetime]
    created_date: datetime.datetime
    updated_date: datetime.datetime


class DeviceDto(BaseModel):
    device_id: str
    device_name: str
    project: str
    process: str
    line: int

