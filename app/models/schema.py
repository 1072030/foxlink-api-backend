from typing import List, Optional
from pydantic import BaseModel, EmailStr


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
