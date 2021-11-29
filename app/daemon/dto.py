from pydantic import BaseModel
from typing import Optional
import datetime


class Event(BaseModel):
    id: int
    project: str
    line: str
    device_name: str
    category: int
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime]
    message: str
    start_file_name: str
    end_file_name: str
