from typing import List
from fastapi import APIRouter, Depends
from app.services.user import get_users, create_user
from app.services.auth import get_current_active_user
from app.models.schema import User, UserCreate

router = APIRouter(prefix="/users")


@router.get("/", response_model=List[User], tags=["users"])
async def read_all_users(token: str = Depends(get_current_active_user)):
    return await get_users()


@router.post("/", tags=["users"])
async def create_a_new_user(dto: UserCreate):
    return await create_user(dto)
