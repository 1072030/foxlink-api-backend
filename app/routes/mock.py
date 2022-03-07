from typing import List, Optional
from databases import Database
from fastapi import APIRouter, Depends
from app.core.database import FactoryMap, User
from app.services.auth import get_admin_active_user
import random, os, datetime
import pandas as pd
from app.env import (
    FOXLINK_DB_USER,
    FOXLINK_DB_PWD,
    FOXLINK_DB_HOST,
    FOXLINK_DB_PORT,
)

router = APIRouter(prefix="/mock")

test_data = pd.read_excel(
    f"{os.path.dirname(__file__)}/../../foxlink_dispatch/test_data/正崴MySQL事件View表_測試用.xlsx"
)

_db = Database(
    f"mysql://{FOXLINK_DB_USER}:{FOXLINK_DB_PWD}@{FOXLINK_DB_HOST}:{FOXLINK_DB_PORT}"
)


@router.post("/", tags=["testing"])
async def create_mock_foxlink_event(user: User = Depends(get_admin_active_user),):
    random_data = test_data.iloc[random.randint(0, len(test_data))]
    await _db.execute("CREATE DATABASE IF NOT EXISTS `aoi`;")

    await _db.execute(
        f"""
    CREATE TABLE IF NOT EXISTS `aoi`.`{random_data['project']}` (
    `ID` int unsigned NOT NULL AUTO_INCREMENT,
    `Line` varchar(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `Device_Name` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `Category` int unsigned NOT NULL,
    `Start_Time` datetime DEFAULT NULL,
    `End_Time` datetime DEFAULT NULL,
    `Message` varchar(40) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `START_FILE_NAME` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `END_FILE_NAME` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    PRIMARY KEY (`ID`),
    KEY `start_index` (`Start_Time`),
    KEY `end_index` (`End_Time`)
    ) ENGINE=InnoDB AUTO_INCREMENT=2156775 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    )

    stmt = f"INSERT INTO `aoi`.`{random_data['project']}` (ID, Line, Device_Name, Category, Start_Time, Message) VALUES (:id, :line, :device_name, :category, :start_time, :message);"
    await _db.execute(
        stmt,
        {
            "id": random_data["ID"].item(),
            "line": random_data["Line"].item(),
            "device_name": random_data["Device_Name"],
            "category": random_data["Category"].item(),
            "start_time": datetime.datetime.utcnow(),
            "message": random_data["Message"],
        },
    )
