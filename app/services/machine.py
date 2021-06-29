from typing import List
from app.core.database import Machine
from fastapi.exceptions import HTTPException


async def get_machines() -> List[Machine]:
    machines = await Machine.objects.select_all().all()
    return machines


async def create_machine(machine: Machine):
    try:
        await machine.save()
    except:
        raise HTTPException(
            status_code=400, detail="raise a error when inserting mission into databse"
        )

    return machine

