import math
from typing import Dict, List, Optional, Tuple
from app.core.database import (
    User,
    Device,
    UserDeviceLevel,
    FactoryMap,
    CategoryPRI,
    database,
)
from fastapi.exceptions import HTTPException
from app.services.user import get_password_hash
from fastapi import UploadFile
import pandas as pd
from foxlink_dispatch.dispatch import data_convert
from app.foxlink_db import foxlink_db

data_converter = data_convert()


def generate_device_id(project: str, line: int, device_name: str) -> str:
    return f"{project}@{int(line)}@{device_name}"


@database.transaction()
async def import_devices(excel_file: UploadFile) -> Tuple[List[str], pd.DataFrame]:
    raw_excel: bytes = await excel_file.read()
    frame: pd.DataFrame = pd.read_excel(raw_excel, sheet_name=0)
    workshop_name: str = frame.workshop.unique()[0]

    create_device_bulk: List[Device] = []
    update_device_bulk: List[Device] = []
    device_name_dict: Dict[str, bool] = {}

    device_infos = await foxlink_db.get_device_cname(workshop_name)

    # if device_infos is not None:
    #     for d in create_device_bulk:
    #         d.device_cname =

    for index, row in frame.iterrows():
        workshop = await FactoryMap.objects.exclude_fields(
            ["related_devices", "map", "image"]
        ).get_or_none(name=row["workshop"])

        if workshop is None:
            workshop = await FactoryMap.objects.create(
                name=row["workshop"], related_devices="[]", map="[]"
            )

        is_rescue: bool = row["project"] == "rescue"

        if is_rescue:
            device_id = f"{row['project']}@{row['workshop']}@{row['device_name']}"
        else:
            device_id = generate_device_id(
                row["project"], row["line"], row["device_name"]
            )
        frame.at[index, "id"] = device_id
        device_name_dict[device_id] = True

        device = Device(
            id=device_id,
            project=row["project"],
            process=row["process"] if type(row["process"]) is str else None,
            device_name=row["device_name"],
            line=int(row["line"]) if math.isnan(row["line"]) == False else None,
            x_axis=float(row["x_axis"]),
            y_axis=float(row["y_axis"]),
            sop_link=row["sop_link"],
            is_rescue=is_rescue,
            workshop=workshop,
        )

        if device.is_rescue:
            device.device_cname = f"{workshop_name} - {device.device_name} 號救援站"

        if device_infos is not None and not device.is_rescue:
            mapping_project = [k for k in device_infos.keys() if device.project in k]
            if len(mapping_project) != 0:
                infos = device_infos[mapping_project[0]]
                for item in infos:
                    if (
                        item["Line"] == device.line
                        and item["Device_Name"] == device.device_name
                    ):
                        device.device_cname = ", ".join(item["Dev_Func"])
                        break

        is_device_existed = await Device.objects.filter(id=device_id).count()
        if is_device_existed == 0:
            create_device_bulk.append(device)
        else:
            update_device_bulk.append(device)

    w = await FactoryMap.objects.exclude_fields(["map", "image"]).get(
        name=workshop_name
    )

    bulk_delete_ids: List[str] = []

    for original_d in w.related_devices:
        if original_d not in device_name_dict.keys():
            bulk_delete_ids.append(original_d)

    await Device.objects.filter(id__in=bulk_delete_ids).delete(each=True)

    if len(update_device_bulk) != 0:
        await Device.objects.bulk_update(update_device_bulk)
    if len(create_device_bulk) != 0:
        await Device.objects.bulk_create(create_device_bulk)
    # calcuate factroy map matrix
    params = await calcuate_factory_layout_matrix(workshop_name, frame)

    return frame["id"].unique().tolist(), params


# TODO: remove orphan category priorities
# 匯入 Device's Category & Priority
@database.transaction()
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


async def calcuate_factory_layout_matrix(
    workshop_name: str, frame: pd.DataFrame
) -> pd.DataFrame:
    data = data_converter.fn_factorymap(frame)
    matrix: List[List[float]] = []

    for index, row in data["result"].iterrows():
        native_arr = [float(x) for x in row.values.tolist()]
        matrix.append(native_arr)

    await FactoryMap.objects.filter(name=workshop_name).update(
        related_devices=data["result"].columns.values.tolist(), map=matrix
    )

    return data["parameter"]


@database.transaction()
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
    update_user_bulk: List[User] = []
    for index, row in factory_worker_info.iterrows():
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
                is_active=True,
                expertises=[],
                level=row["job"],
            )
            create_user_bulk.append(worker)
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

    await User.objects.bulk_update(
        update_user_bulk, columns=["full_name", "location", "level"]
    )
    await User.objects.bulk_create(create_user_bulk)

    # remove original device levels
    for username in full_name_mapping.values():
        await UserDeviceLevel.objects.select_related("device").filter(
            user=username
        ).delete(each=True)

    for index, row in factory_worker_info.iterrows():
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
        await UserDeviceLevel.objects.bulk_create(bulk)

    return params

