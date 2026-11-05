import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from keepers import KEEPERS  # noqa: E402
from research.backtest import run_backtest  # noqa: E402
from research.gate import keeper_decision  # noqa: E402


def _summary(trades, points, profit_factor):
    return {
        "closed_trades": trades,
        "realized_points": points,
        "profit_factor": profit_factor,
        "gross_loss_points": 1.0 if profit_factor is not None else 0.0,
    }


class GateTests(unittest.TestCase):
    def test_two_symbols_required(self):
        decision = keeper_decision(
            {
                "CU": _summary(10, 5.0, 1.2),
                "SR": _summary(10, -1.0, 0.8),
            }
        )
        self.assertFalse(decision["keeper"])
        self.assertEqual(decision["awful_symbols"], ["SR"])

    def test_two_clean_passes_are_a_keeper(self):
        decision = keeper_decision(
            {
                "CU": _summary(12, 4.0, 1.3),
                "SR": _summary(9, 2.0, 1.1),
                "I": _summary(3, None, None),
            }
        )
        self.assertTrue(decision["keeper"])
        self.assertCountEqual(decision["passing_symbols"], ["CU", "SR"])

    def test_keepers_refuse_live_orders(self):
        self.assertGreaterEqual(len(KEEPERS), 1)

        class Live:
            def send_order(self, *args, **kwargs):
                raise AssertionError("live gateway was called")

            def write_log(self, *args, **kwargs):
                pass

            def load_bar(self, *args, **kwargs):
                pass

        for cls in KEEPERS:
            strategy = cls(Live(), "paper", "CU.SHFE", {"allow_live_trading": True})
            strategy.trading = True
            self.assertFalse(strategy.allow_live_trading)
            self.assertEqual(strategy.buy(1, 1), [])
            self.assertEqual(strategy.live_deny_count, 1)

    def test_next_open_does_not_use_same_bar(self):
        trades = run_backtest([10, 11, 13, 12], [1, 1, 0, 0])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_price"], 11)
        self.assertEqual(trades[0]["exit_price"], 12)
        self.assertEqual(trades[0]["points"], 1)


if __name__ == "__main__":
    unittest.main()
