from datetime import date
from typing import List, Optional
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import relationship


# * User
class UserBase(BaseModel):
    email: EmailStr
    phone: str
    full_name: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    password_hash: str
    is_active: bool


class UserChangePassword(BaseModel):
    old_password: str
    new_password: str


# * Machine
class MachineBase(BaseModel):
    name: str
    manual: Optional[str]


class MachineCreate(MachineBase):
    pass


class Machine(MachineBase):
    id: int


# * Mission
class MissionBase(BaseModel):
    name: str
    description: Optional[str]


class MissionCreate(MissionBase):
    machine_id: int


class Mission(MissionBase):
    id: int
    created_date: date
    updated_date: date
    closed_date: Optional[date]
