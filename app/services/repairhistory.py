from typing import List
from app.core.database import RepairHistory, User
from fastapi.exceptions import HTTPException


async def get_histories() -> List[RepairHistory]:
    histories = await RepairHistory.objects.all()
    return histories


async def get_history_by_id(history_id: int) -> RepairHistory:
    try:
        history = await RepairHistory.objects.get(id=history_id)
        return history
    except:
        raise HTTPException(status_code=404, detail="history with this id is not found")


async def get_histories_by_user(user: User) -> List[RepairHistory]:
    return await RepairHistory.objects.filter(mission__assignee__id=user.id).all()
