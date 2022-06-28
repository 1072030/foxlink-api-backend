import unittest
import dotenv
import os
from datetime import datetime

dotenv.load_dotenv('ntust.env')

from app.utils.utils import get_shift_type_now, get_shift_type_by_datetime
from app.core.database import ShiftType

class DutyShiftTestModule(unittest.TestCase):
    def test_shift_type(self):
        os.environ['DAY_SHIFT_BEGIN'] = '07:55'
        os.environ['DAY_SHIFT_END'] = '00:55'
        dt = datetime.now().replace(hour=22, minute=30)
        self.assertEqual(ShiftType.night, get_shift_type_by_datetime(dt))

        dt = datetime.now().replace(hour=0, minute=30)
        self.assertEqual(ShiftType.day, get_shift_type_by_datetime(dt))


        os.environ['DAY_SHIFT_BEGIN'] = '07:55'
        os.environ['DAY_SHIFT_END'] = '19:55'

        dt = datetime.now().replace(hour=12, minute=30)
        self.assertEqual(ShiftType.day, get_shift_type_by_datetime(dt))

        dt = datetime.now().replace(hour=14, minute=30)
        self.assertEqual(ShiftType.night, get_shift_type_by_datetime(dt))

if __name__ == "__main__":
    unittest.main()