from typing import List, Optional
from pydantic.types import Json
from app.core.database import FactoryMap
from fastapi.exceptions import HTTPException


# TODO: Implement this
async def validate(factory_map: FactoryMap):
    return True


async def import_new_map(name: str, matrix: List[List[int]]):
    factory_map = FactoryMap(name=name, map=matrix)

    try:
        await factory_map.save()
    except:
        raise HTTPException(
            status_code=500, detail="cannot store factory map into database"
        )


async def get_all_maps() -> List[FactoryMap]:
    return await FactoryMap.objects.exclude_fields(["map"]).all()


async def get_map_by_id(id: int) -> Optional[FactoryMap]:
    return await FactoryMap.objects.filter(id=id).get_or_none()
