import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.event_reminder_scheduler import _day_reminder_window


class DayReminderWindowTests(unittest.TestCase):
    def test_waits_until_1900_moscow(self):
        self.assertIsNone(_day_reminder_window(datetime(2026, 9, 28, 15, 59, tzinfo=timezone.utc)))
        self.assertEqual(
            _day_reminder_window(datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)),
            (
                datetime(2026, 9, 28, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc),
            ),
        )

    def test_late_poll_still_targets_tomorrow_only(self):
        self.assertEqual(
            _day_reminder_window(datetime(2026, 12, 31, 20, 30, tzinfo=timezone.utc)),
            (
                datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc),
                datetime(2027, 1, 1, 21, 0, tzinfo=timezone.utc),
            ),
        )


if __name__ == "__main__":
    unittest.main()
