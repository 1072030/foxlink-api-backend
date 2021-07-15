from app.models.schema import MachineCreate, MachineUpdate
from typing import Dict, List, Any
from app.core.database import Machine
from fastapi.exceptions import HTTPException


async def get_machines() -> List[Machine]:
    machines = await Machine.objects.fields(["id", "name", "manual"]).all()
    return machines


async def get_machine_by_id(id: int) -> Machine:
    try:
        item = await Machine.objects.filter(id=id).get()
        return item
    except:
        raise HTTPException(
            status_code=404, detail="the machine with this id is not found"
        )


async def create_machine(dto: MachineCreate):
    try:
        machine = await Machine.objects.create(name=dto.name, manual=dto.manual)
    except:
        raise HTTPException(
            status_code=500, detail="raise a error when inserting machine into databse"
        )

    return machine


async def update_machine(machine_id: int, dto: MachineUpdate) -> Machine:
    machine = await get_machine_by_id(machine_id)

    updateDict: Dict[str, Any] = {}

    try:
        if dto.manual is not None:
            updateDict["manual"] = dto.manual

        if dto.name is not None:
            updateDict["name"] = dto.name

        updated_machine = await machine.update(None, **updateDict)

        return updated_machine
    except:
        raise HTTPException(
            status_code=500, detail="raise a error when updating machine into databse"
        )

async def delete_machine_by_id(machine_id: int):
    affected_rows = await Machine.objects.delete(id=machine_id)

    if affected_rows != 1:
        raise HTTPException(status_code=404, detail="machine with this id is not found")
