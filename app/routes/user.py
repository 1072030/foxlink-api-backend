from typing import List
from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from app.services.user import get_users, create_user, get_password_hash, update_user
from app.services.auth import get_current_active_user, verify_password
from app.models.schema import User, UserCreate, UserChangePassword

router = APIRouter(prefix="/users")


@router.get("/", response_model=List[User], tags=["users"])
async def read_all_users(user: User = Depends(get_current_active_user)):
    return await get_users()


@router.post("/", tags=["users"])
async def create_a_new_user(dto: UserCreate):
    return await create_user(dto)


@router.post("/change-password", tags=["users"])
async def change_password(
    dto: UserChangePassword, user: User = Depends(get_current_active_user)
):
    if not verify_password(dto.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="The old password is not matched")

    await update_user(user.id, password_hash=get_password_hash(dto.new_password))
