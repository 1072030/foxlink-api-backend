from app.models.schema import MachineCreate
from typing import List
from app.core.database import Machine
from fastapi.exceptions import HTTPException


async def get_machines() -> List[Machine]:
    machines = await Machine.objects.fields(["id", "name", "manual"]).all()
    return machines


async def get_machine_by_id(id: int) -> Machine:
    item = await Machine.objects.filter(id=id).get()
    return item


async def create_machine(dto: MachineCreate):
    try:
        machine = await Machine.objects.create(name=dto.name, manual=dto.manual)
    except:
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse"
        )

    return machine

