from pydantic.types import Json
from app.core.database import User
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# * User
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    expertises: List[str]


class UserCreate(UserBase):
    password: str


class UserPatch(BaseModel):
    email: Optional[EmailStr]
    full_name: Optional[str]
    expertises: Optional[List[str]]


class UserOut(UserBase):
    id: int
    is_active: bool
    is_admin: bool


class UserChangePassword(BaseModel):
    old_password: str
    new_password: str


# * Machine
class MachineBase(BaseModel):
    name: str
    manual: Optional[str]


class MachineCreate(MachineBase):
    pass


class MachineUpdate(BaseModel):
    name: Optional[str]
    manual: Optional[str]


# * Mission
class MissionBase(BaseModel):
    description: Optional[str]


class MissionCreate(MissionBase):
    name: str
    device: int
    required_expertises: List[str]


class MissionUpdate(MissionBase):
    name: Optional[str]
    device_id: Optional[str]


class MissionCancel(BaseModel):
    mission_id: int
    reason: str


# * RepairHistory
class RepairHistoryBase(BaseModel):
    machine_status: Optional[str]
    cause_of_issue: Optional[str]
    issue_solution: Optional[str]
    canceled_reason: Optional[str]
    is_cancel: bool


class RepairHistoryCreate(RepairHistoryBase):
    mission: int


# * Factory Map
class FactoryMapBase(BaseModel):
    name: str
    matrix: List[List[int]]


class FactoryMapCreate(FactoryMapBase):
    pass
