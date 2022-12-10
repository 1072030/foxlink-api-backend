
from typing import Optional
from datetime import datetime
from pydantic import BaseModel

class FoxlinkEvent(BaseModel):
    id: int
    project: str
    line: str
    device_name: str
    category: int
    start_time: datetime
    end_time: Optional[datetime]
    message: Optional[str]
    start_file_name: Optional[str]
    end_file_name: Optional[str]

