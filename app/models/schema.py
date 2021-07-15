from app.core.database import User
from typing import Optional
from pydantic import BaseModel, EmailStr


# * User
class UserBase(BaseModel):
    email: EmailStr
    phone: str
    full_name: str


class UserCreate(UserBase):
    password: str


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
    machine_id: int


class MissionUpdate(MissionBase):
    name: Optional[str]
    machine_id: Optional[int]


class MissionCancel(BaseModel):
    mission_id: int
    reason: str
