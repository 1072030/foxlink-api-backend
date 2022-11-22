from datetime import datetime
import math
from typing import Dict, List, Tuple
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    CategoryPRI,
    WorkerStatus,
    WorkerStatusEnum,
    api_db,
)
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
from fastapi import UploadFile
import pandas as pd
from foxlink_dispatch.dispatch import data_convert
from app.foxlink.db import foxlink_dbs
from app.foxlink.utils import assemble_device_id
from sqlalchemy.sql import func
import traceback
import asyncio
from datetime import datetime

data_converter = data_convert()

@api_db.transaction()
async def import_devices(excel_file: UploadFile) -> Tuple[List[str], pd.DataFrame]:
    try:
        frame: pd.DataFrame = pd.read_excel(await excel_file.read(), sheet_name=0)

        workshops =  frame["workshop"].drop_duplicates()

        create_device_bulk: Dict[str, List[Device]] = {}
        update_device_bulk: Dict[str, List[Device]] = {}

        workshop_entity_dict: Dict[str, FactoryMap] = {}

        # first create workshop if not exists
        for workshop in workshops:
            factory = await FactoryMap.objects.filter(name=workshop).get_or_none()

            if not factory:
                factory =  await FactoryMap.objects.create(
                    name=workshop, related_devices="[]", map="[]"
                )

            workshop_entity_dict[workshop] = factory
            create_device_bulk[workshop] = []
            update_device_bulk[workshop] = []

        # create/update devices
        for index, row in frame.iterrows():
            is_rescue: bool = row["project"] == "rescue"
            line: int  = int(row["line"]) if not math.isnan(row["line"]) else None
            workshop: str = row["workshop"]
            project: str = row["project"]
            process: str = row["process"] if type(row["process"]) is str else None
            device_name: str = row["device_name"]
            x_axis: float = float(row["x_axis"])
            y_axis: float = float(row["y_axis"])
            sop_link: str = row["sop_link"]
            
            device_id: str = assemble_device_id(
                project, 
                workshop if is_rescue else line,
                device_name
            )
            
            if is_rescue:
                device_cname = f"{workshop} - {row['device_name']} 號救援站"
            else:
                device_cname = await foxlink_dbs.get_device_cname(
                    workshop,
                    project,
                    line,
                    device_name
                )

            device = Device(
                id = device_id,
                project = project,
                process = process,
                device_name= device_name,
                line = line,
                x_axis = x_axis,
                y_axis = y_axis,
                sop_link = sop_link,
                is_rescue = is_rescue,
                workshop = workshop_entity_dict[workshop].id,
                device_cname=device_cname,
                updated_date=datetime.now()
            )        

            

            # categorize device object type.
            if await Device.objects.filter(id=device_id).exists():
                update_device_bulk[workshop].append(device)
            else:  
                create_device_bulk[workshop].append(device)
            
            # configure frame for further needs.
            frame.at[index, "id"] = device_id

    

        # update workshap entity & remove unlisted devices
        current_all_device_ids: List[str] = []
        for workshop in workshops:
            _workshop = await FactoryMap.objects.exclude_fields(["map", "image"]).get(name=workshop)
            current_workshop_device_ids = [ 
                device.id for device in (
                    update_device_bulk[workshop] + create_device_bulk[workshop] 
                )
            ]

            current_all_device_ids += current_workshop_device_ids
            
            # update devices
            if(len(update_device_bulk[workshop]) > 0):
                sample = update_device_bulk[workshop][0]
                await Device.objects.bulk_update(
                    objects=update_device_bulk[workshop],
                    columns=sample.dict(exclude_defaults=True)
                )

            # create devices
            if(len(create_device_bulk[workshop]) > 0):
                await Device.objects.bulk_create(create_device_bulk[workshop])

            params = await calcuate_factory_layout_matrix(workshop, frame)
            
        await Device.objects.exclude(id__in=current_all_device_ids).delete(each=True)

        return frame["id"].unique().tolist(), params

    except Exception as e :
        print(e)
        traceback.print_exc()
        raise e

# TODO: remove orphan category priorities
# 匯入 Device's Category & Priority
@api_db.transaction()
async def import_workshop_events(excel_file: UploadFile) -> pd.DataFrame:
    """
    Return: parameters in pandas format
    """
    raw_excel: bytes = await excel_file.read()
    data = data_converter.fn_proj_eventbooks(excel_file.filename, raw_excel)
    df, param = data["result"], data["parameter"]

    project_name = df["project"].unique()[0]

    for device_name in df["Device_Name"].unique():
        devices = await Device.objects.filter(
            project__iexact=project_name,
            device_name__iexact=device_name.replace(" ", "_"),
        ).all()

        for d in devices:
            await d.categorypris.clear()

    for index, row in data["result"].iterrows():
        if math.isnan(row["优先顺序"]):
            continue

        devices = await Device.objects.filter(
            project__iexact=row["project"],
            device_name__iexact=row["Device_Name"].replace(" ", "_"),
        ).all()

        # await CategoryPRI.objects.filter(devices=devices).delete(each=True)

        p = await CategoryPRI.objects.create(
            category=row["Category"], message=row["MESSAGE"], priority=row["优先顺序"],
        )

        for d in devices:
            await p.devices.add(d)  # type: ignore

    return param


async def calcuate_factory_layout_matrix(workshop: str, frame: pd.DataFrame) -> pd.DataFrame:
    data = data_converter.fn_factorymap(frame.loc[frame["workshop"]==workshop])
    matrix: List[List[float]] = []

    for index, row in data["result"].iterrows():
        native_arr = [float(x) for x in row.values.tolist()]
        matrix.append(native_arr)

    await FactoryMap.objects.filter(name=workshop).update(
        related_devices=data["result"].columns.values.tolist(), map=matrix
    )

    return data["parameter"]


# @api_db.transaction()
async def import_factory_worker_infos(
    workshop_name: str, excel_file: UploadFile
) -> pd.DataFrame:
    raw_excel: bytes = await excel_file.read()

    try:
        data = data_converter.fn_factory_worker_info(excel_file.filename, raw_excel)
    except Exception as e:
        raise HTTPException(status_code=400, detail=repr(e))

    factory_worker_info, params = data["result"], data["parameter"]
    workshop_id_mapping: Dict[str, int] = {}
    full_name_mapping: Dict[str, str] = {}
    create_user_bulk: List[User] = []
    create_workerstatus_bulk: List[WorkerStatus] = []
    update_user_bulk: List[User] = []
    _dframe_selected_columns = factory_worker_info[['workshop','worker_id','worker_name','job']].drop_duplicates()
    for index, row in  _dframe_selected_columns.iterrows():
        if workshop_id_mapping.get(row["workshop"]) is None:
            workshop = (
                await FactoryMap.objects.filter(name=row["workshop"])
                .fields(["id", "name"])
                .get_or_none()
            )

            if workshop is None:
                raise HTTPException(
                    status_code=400, detail=f"unknown workshop name: {row['workshop']}"
                )

            workshop_id_mapping[workshop.name] = workshop.id

        full_name_mapping[row["worker_name"]] = str(row["worker_id"])
        worker = await User.objects.get_or_none(username=row["worker_id"])

        # superior_id: Optional[str] = None
        # if row["員工名字"] != row["負責人"]:
        #     superior_id = str(
        #         worker_info[worker_info["員工名字"] == row["負責人"]]["員工工號"].item()
        #     )

        if (
            worker is None
            and len(
                [u for u in create_user_bulk if u.username == str(row["worker_id"])]
            )
            == 0
        ):
            worker = User(
                username=str(row["worker_id"]),
                full_name=row["worker_name"],
                password_hash=get_password_hash("foxlink"),
                location=workshop_id_mapping[row["workshop"]],
                expertises=[],
                level=row["job"],
            )
            create_user_bulk.append(worker)

            if not await WorkerStatus.objects.filter(worker=worker.username).exists():
                rescue_station = await Device.objects.filter(workshop=workshop_id_mapping[row["workshop"]], is_rescue=True).first()
                w_status = WorkerStatus(
                    worker=worker.username,
                    status=WorkerStatusEnum.leave.value,
                    at_device=rescue_station,
                    last_event_end_date=datetime.utcnow(),
                )
                create_workerstatus_bulk.append(w_status)
        else:
            worker = User(
                username=str(row["worker_id"]),
                full_name=row["worker_name"],
                location=workshop_id_mapping[row["workshop"]],
                level=row["job"],
                # ignore fields to prevent pydantic error
                expertises=[],
                password_hash="",
            )
            update_user_bulk.append(worker)

    delete_user_bulk: List[str] = []

    for w_id in workshop_id_mapping.values():
        all_workers_in_workshop = await User.objects.filter(location=w_id).all()

        for u in all_workers_in_workshop:
            if u.username not in full_name_mapping.values():
                delete_user_bulk.append(u.username)

    await User.objects.filter(username__in=delete_user_bulk).delete(each=True)

    if len(update_user_bulk) != 0:
        await User.objects.bulk_update(
            update_user_bulk, columns=["full_name", "location", "level"]
        )

    if len(create_user_bulk) != 0:
        await User.objects.bulk_create(create_user_bulk)

    if len(create_workerstatus_bulk) != 0:
        await WorkerStatus.objects.bulk_create(create_workerstatus_bulk)

    # remove original device levels
    # for username in full_name_mapping.values():
    #     await UserDeviceLevel.objects.select_related("device").filter(
    #         user=username
    #     ).delete(each=True)

    _dframe_selected_columns = factory_worker_info[[
        'workshop','process','project','device_name','worker_id','superior','shift','level'
    ]].drop_duplicates()
    for index, row in _dframe_selected_columns.iterrows():
        workshop = (
            await FactoryMap.objects.filter(name=row["workshop"])
            .fields(["id", "name"])
            .get()
        )

        related_devices = await Device.objects.filter(
            workshop=workshop.id,
            process=row["process"],
            project__iexact=row["project"],
            device_name=row["device_name"],
        ).all()

        bulk = []
        for d in related_devices:
            bulk.append(
                UserDeviceLevel(
                    device=d,
                    user=row["worker_id"],
                    superior=full_name_mapping.get(row["superior"]),
                    shift=row["shift"],
                    level=row["level"],
                )
            )

        if len(bulk) != 0:
            await UserDeviceLevel.objects.bulk_create(bulk)

    return params

