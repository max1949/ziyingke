import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vnpy_compat import (  # noqa: E402
    RECOMMENDED_MINUTE_WINDOWS,
    BarData,
    BarGenerator,
    Interval,
    minute_window_divides_60,
)


def bar(dt, open_=1.0, high=1.0, low=1.0, close=1.0, volume=1.0):
    return BarData(
        symbol="CU",
        exchange="SHFE",
        datetime=dt,
        open_price=open_,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=volume,
    )


class BarRuleTests(unittest.TestCase):
    def test_recommended_minute_windows_match_vnpy_notice(self):
        self.assertEqual(RECOMMENDED_MINUTE_WINDOWS, (2, 3, 5, 6, 10, 15, 20, 30))
        self.assertTrue(minute_window_divides_60(15))
        self.assertFalse(minute_window_divides_60(7))
        self.assertIn(15, RECOMMENDED_MINUTE_WINDOWS)

    def test_fifteen_minute_window_closes_on_minute_14(self):
        got = []
        start = datetime(2024, 1, 2, 9, 0)
        generator = BarGenerator(lambda _bar: None, 15, got.append, Interval.MINUTE)
        generator.update_bar(bar(start, 10, 12, 9, 11, 3))
        generator.update_bar(bar(start + timedelta(minutes=14), 11, 14, 8, 13, 4))
        self.assertEqual(len(got), 1)
        finished = got[0]
        self.assertEqual(finished.datetime, start)
        self.assertEqual(finished.open_price, 10)
        self.assertEqual(finished.high_price, 14)
        self.assertEqual(finished.low_price, 8)
        self.assertEqual(finished.close_price, 13)
        self.assertEqual(finished.volume, 7)

    def test_clock_hour_timestamps_do_not_finish_a_four_minute_window(self):
        got = []
        generator = BarGenerator(lambda _bar: None, 4, got.append, Interval.MINUTE)
        for hour in range(10):
            generator.update_bar(bar(datetime(2024, 1, 2, hour, 0)))
        self.assertEqual(got, [])

    def test_hour_bar_finishes_at_minute_59(self):
        got = []
        generator = BarGenerator(lambda _bar: None, 1, got.append, Interval.HOUR)
        generator.update_bar(bar(datetime(2024, 1, 2, 10, 0), 10, 11, 9, 10.5, 1))
        self.assertEqual(got, [])
        generator.update_bar(bar(datetime(2024, 1, 2, 10, 30), 10.5, 12, 10, 11, 2))
        generator.update_bar(bar(datetime(2024, 1, 2, 10, 59), 11, 13, 10.5, 12.5, 3))
        self.assertEqual(len(got), 1)
        finished = got[0]
        self.assertEqual(finished.datetime, datetime(2024, 1, 2, 10, 0))
        self.assertEqual(finished.open_price, 10)
        self.assertEqual(finished.high_price, 13)
        self.assertEqual(finished.low_price, 9)
        self.assertEqual(finished.close_price, 12.5)
        self.assertEqual(finished.volume, 6)

    def test_hour_change_pushes_an_unfinished_hour(self):
        got = []
        generator = BarGenerator(lambda _bar: None, 1, got.append, Interval.HOUR)
        generator.update_bar(bar(datetime(2024, 1, 2, 11, 0), 1, 2, 1, 1.5, 1))
        generator.update_bar(bar(datetime(2024, 1, 2, 11, 30), 1.5, 2, 1.2, 1.4, 1))
        generator.update_bar(bar(datetime(2024, 1, 2, 13, 30), 2, 3, 2, 2.5, 1))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].datetime, datetime(2024, 1, 2, 11, 0))
        self.assertEqual(got[0].close_price, 1.4)

    def test_minute_59_is_applied_before_hour_change(self):
        got = []
        generator = BarGenerator(lambda _bar: None, 1, got.append, Interval.HOUR)
        generator.update_bar(bar(datetime(2024, 1, 2, 10, 0), 1, 1, 1, 1, 1))
        generator.update_bar(bar(datetime(2024, 1, 2, 11, 59), 5, 6, 4, 5, 2))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].datetime, datetime(2024, 1, 2, 10, 0))
        self.assertEqual(got[0].close_price, 5)
        self.assertEqual(got[0].volume, 3)

    def test_four_hour_window_counts_finished_hours(self):
        got = []
        generator = BarGenerator(lambda _bar: None, 4, got.append, Interval.HOUR)
        start = datetime(2024, 1, 2, 9, 0)
        for offset in range(240):
            generator.update_bar(bar(start + timedelta(minutes=offset), close=100 + offset))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].datetime, datetime(2024, 1, 2, 9, 0))
        self.assertEqual(got[0].open_price, 1)
        self.assertEqual(got[0].close_price, 100 + 239)


if __name__ == "__main__":
    unittest.main()
