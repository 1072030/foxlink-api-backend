import unittest
import dotenv
import os
from datetime import datetime

dotenv.load_dotenv('ntust.env')

from app.utils.utils import get_current_shift_time_interval, get_shift_type_by_datetime
from app.core.database import ShiftType

class DutyShiftTestModule(unittest.TestCase):
    def test_shift_type(self):
        os.environ['DAY_SHIFT_BEGIN'] = '07:55'
        os.environ['DAY_SHIFT_END'] = '00:55'
        dt = datetime.now().replace(hour=22, minute=30)
        self.assertEqual(ShiftType.night, get_shift_type_by_datetime(dt))

        dt = datetime.now().replace(hour=0, minute=30)
        self.assertEqual(ShiftType.day, get_shift_type_by_datetime(dt))


        os.environ['DAY_SHIFT_BEGIN'] = '07:40'
        os.environ['DAY_SHIFT_END'] = '20:00'

        dt = datetime.now().replace(hour=12, minute=30)
        self.assertEqual(ShiftType.night, get_shift_type_by_datetime(dt))

        dt = datetime.now().replace(hour=12, minute=30)
        self.assertEqual(ShiftType.night, get_shift_type_by_datetime(dt))

    def test_current_shift_time_interval(self):
        os.environ['DAY_SHIFT_BEGIN'] = '07:40'
        os.environ['DAY_SHIFT_END'] = '20:00'

        get_current_shift_time_interval()


if __name__ == "__main__":
    unittest.main()