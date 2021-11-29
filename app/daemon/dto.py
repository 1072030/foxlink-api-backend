from pydantic import BaseModel
import datetime


class Event(BaseModel):
    id: int
    line: str
    device_name: str
    category: int
    start_time: datetime.datetime
    end_time: datetime.datetime
    message: str
    start_file_name: str
    end_file_name: str
