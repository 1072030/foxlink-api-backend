from app.models.schema import RepairHistoryCreate
from typing import List, Optional
from app.core.database import RepairHistory, User
from fastapi.exceptions import HTTPException


async def create_history_for_mission(dto: RepairHistoryCreate):
    try:
        history = await RepairHistory.objects.create(**dto.dict())

        return history
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="cannot create a repair history into databse" + str(e),
        )


async def get_histories(**kwargs) -> List[RepairHistory]:
    filtered = {k: v for k, v in kwargs.items() if v is not None}

    histories = await RepairHistory.objects.filter(**filtered).all()
    return histories


async def get_history_by_id(history_id: int) -> RepairHistory:
    try:
        history = await RepairHistory.objects.get(id=history_id)
        return history
    except:
        raise HTTPException(status_code=404, detail="history with this id is not found")


async def get_histories_by_user(user: User) -> List[RepairHistory]:
    return await RepairHistory.objects.filter(mission__assignee__id=user.id).all()
