from app.models.schema import FactoryMapCreate
from typing import List
from fastapi import APIRouter, Depends
from app.services.factory_map import import_new_map, get_all_maps, get_map_by_id
from app.services.auth import get_admin_active_user, get_current_active_user
from app.core.database import FactoryMap, User

router = APIRouter(prefix="/factory-map")


@router.get("/", response_model=List[FactoryMap], tags=["factory_map"])
async def read_all_factory_maps(user: User = Depends(get_admin_active_user)):
    return await get_all_maps()


@router.post("/", tags=["factory_map"], status_code=201)
async def create_a_new_factory_map(
    dto: FactoryMapCreate, user: User = Depends(get_admin_active_user)
):
    return await import_new_map(dto.name, dto.matrix)


@router.get("/{map_id}", response_model=FactoryMap, tags=["factory_map"])
async def get_factory_map_by_id(
    map_id: int, user: User = Depends(get_admin_active_user)
):
    return await get_map_by_id(map_id)

