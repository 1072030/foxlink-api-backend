from fastapi import APIRouter

router = APIRouter(prefix="/stats")


@router.get("/", tags=["statistics"])
async def get_statistics_info():
    ...
