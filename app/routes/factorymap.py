from typing import List, Optional
from fastapi import APIRouter
from app.core.database import FactoryMap

from app.services.factorymap import get_all_factory_maps

router = APIRouter(prefix="/factory-map")


@router.get("/", response_model=List[Optional[FactoryMap]], tags=["factory_maps"])
async def get_a_factory_map_by_query(
    id: Optional[int] = None, name: Optional[str] = None
):
    query = {"id": id, "name": name}
    query = {k: v for k, v in query.items() if v is not None}
    return await FactoryMap.objects.filter(**query).all()  # type: ignore
