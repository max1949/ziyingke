import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Production_Hybrid_Monitor import Production_Hybrid_Monitor  # noqa: E402
from quality_observation import (  # noqa: E402
    audit_frame,
    decide_ship,
    default_setting,
    quality_pass,
    replay_frame,
    select_by_train,
    summarize_closed,
)


class ObservationContractTests(unittest.TestCase):
    def test_empty_realized_points_stay_null(self):
        summary = summarize_closed([])
        self.assertIsNone(summary["realized_points"])
        self.assertIsNone(summary["profit_factor"])
        self.assertFalse(quality_pass(summary))

    def test_known_round_trips(self):
        summary = summarize_closed([{"points": 3.0}, {"points": -1.0}])
        self.assertEqual(summary["realized_points"], 2.0)
        self.assertEqual(summary["profit_factor"], 3.0)
        self.assertEqual(summary["closed_trades"], 2)
        self.assertEqual(summary["max_drawdown_points"], 1.0)
        self.assertFalse(quality_pass(summary))

    def test_quality_requires_eight_positive_trades(self):
        trades = [{"points": 1.0} for _ in range(8)]
        summary = summarize_closed(trades)
        self.assertTrue(quality_pass(summary))
        summary["realized_points"] = -1
        self.assertFalse(quality_pass(summary))

    def test_selection_uses_train_not_holdout(self):
        rows = [
            {
                "setting": {"fast_window": 10},
                "train": {"closed_trades": 8, "realized_points": 1.0},
                "holdout": {"closed_trades": 8, "realized_points": 100.0, "profit_factor": 2.0, "gross_loss_points": 1.0, "quality_pass": True},
            },
            {
                "setting": {"fast_window": 20},
                "train": {"closed_trades": 8, "realized_points": 5.0},
                "holdout": {"closed_trades": 1, "realized_points": -50.0, "profit_factor": 0.2, "gross_loss_points": 50.0, "quality_pass": False},
            },
        ]
        chosen = select_by_train(rows)
        self.assertEqual(chosen["setting"]["fast_window"], 20)
        self.assertIsNone(decide_ship(chosen, {"fast_window": 10}))

    def test_short_window_has_no_pnl_field(self):
        index = pd.date_range("2024-01-02 09:00", periods=100, freq="min")
        frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=index)
        audit = audit_frame(frame, "RB")
        self.assertFalse(audit["observation_window_ok"])
        self.assertNotIn("realized_points", audit)
        self.assertNotIn("pnl", audit)

    def test_short_replay_does_not_invent_pnl(self):
        index = pd.date_range("2024-01-02 09:00", periods=30, freq="min")
        frame = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index)
        result = replay_frame(Production_Hybrid_Monitor, frame, "CU", default_setting(Production_Hybrid_Monitor))
        self.assertFalse(result["initialized_4h"])
        self.assertIsNone(result["summary"]["realized_points"])
        self.assertEqual(result["summary"]["closed_trades"], 0)
        self.assertEqual(result["live_deny_count"], 0)
        self.assertFalse(result["allow_live_trading"])
        self.assertEqual(result["execution_mode"], "PAPER")


if __name__ == "__main__":
    unittest.main()
