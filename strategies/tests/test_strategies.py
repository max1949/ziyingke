import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paper_engine import PaperCtaEngine  # noqa: E402
from Production_Hybrid1235_235 import Production_Hybrid1235_235, Production_Hybrid_235  # noqa: E402
from Production_Hybrid_Monitor import Production_Hybrid_Monitor  # noqa: E402
from Strategy_1235_Deep import Strategy_1235_Deep  # noqa: E402
from Strategy_235_Standard import Strategy_235_Standard  # noqa: E402
from vnpy_compat import BarData  # noqa: E402


class LiveEngine:
    def __init__(self):
        self.sent = []

    def send_order(self, *args, **kwargs):
        self.sent.append(args)
        return ["LIVE-1"]

    def write_log(self, msg, strategy=None):
        pass

    def load_bar(self, *args, **kwargs):
        pass

    def active_order_count(self):
        return 0


def flat_bars(count, start=None):
    start = start or datetime(2024, 1, 2, 9, 0)
    bars = []
    for offset in range(count):
        bars.append(
            BarData(
                symbol="CU",
                exchange="SHFE",
                datetime=start + timedelta(minutes=offset),
                open_price=100,
                high_price=100,
                low_price=100,
                close_price=100,
                volume=1,
            )
        )
    return bars


def replay(cls, bars, setting=None):
    engine = PaperCtaEngine()
    strategy = cls(engine, "test", "CU.SHFE", setting or {})
    engine.strategy = strategy
    for item in bars:
        engine.new_bar(item)
    return engine, strategy


class StrategyTests(unittest.TestCase):
    def test_historical_import_name(self):
        self.assertIs(Production_Hybrid_235, Production_Hybrid1235_235)

    def test_monitor_keeps_original_thresholds_and_live_deny(self):
        self.assertEqual(Production_Hybrid_Monitor.low_pnl_atr, 1.5)
        self.assertEqual(Production_Hybrid_Monitor.mid_pnl_atr, 3.5)
        self.assertEqual(Production_Hybrid_Monitor.exit_mode, "absolute")
        self.assertEqual(Production_Hybrid_Monitor.alignment_mode, "strict")
        self.assertFalse(Production_Hybrid_Monitor.allow_live_trading)
        self.assertEqual(Production_Hybrid1235_235.exit_mode, "absolute")
        self.assertEqual(Strategy_235_Standard.low_pnl_atr, 1.5)

    def test_live_default_deny(self):
        engine = LiveEngine()
        strategy = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {})
        self.assertFalse(strategy.allow_live_trading)
        strategy.trading = True
        self.assertEqual(strategy.buy(100, 1), [])
        self.assertEqual(engine.sent, [])
        self.assertEqual(strategy.live_deny_count, 1)

        allowed = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {"allow_live_trading": "false"})
        self.assertFalse(allowed.allow_live_trading)
        explicit = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {"allow_live_trading": True})
        explicit.trading = True
        self.assertEqual(explicit.buy(100, 1), ["LIVE-1"])
        self.assertEqual(len(engine.sent), 1)

    def test_instances_do_not_share_direction_state(self):
        engine = LiveEngine()
        first = Production_Hybrid_Monitor(engine, "a", "CU.SHFE", {})
        second = Production_Hybrid_Monitor(engine, "b", "CU.SHFE", {})
        first.dir_4h = 1
        self.assertEqual(second.dir_4h, 0)

    def test_single_logic_flags(self):
        self.assertTrue(Strategy_235_Standard.enable_235)
        self.assertFalse(Strategy_235_Standard.enable_1235)
        self.assertFalse(Strategy_1235_Deep.enable_235)
        self.assertTrue(Strategy_1235_Deep.enable_1235)

    def test_235_stage_machine_fires_one_paper_order(self):
        engine = PaperCtaEngine()
        strategy = Strategy_235_Standard(engine, "test", "CU.SHFE", {})
        engine.strategy = strategy
        strategy.trading = True
        strategy.am_1m.close[-1] = 100
        strategy.dir_4h = 1
        strategy.dir_1h = 1
        strategy.dir_15m = -1
        strategy.dir_1m = 1
        stamp = datetime(2024, 1, 2, 10, 0)
        sample = BarData(symbol="CU", exchange="SHFE", datetime=stamp, open_price=100, high_price=101, low_price=99, close_price=100, volume=1)
        strategy.scan_235_logic(sample)
        self.assertEqual(strategy.entry_stage, 2)
        strategy.dir_15m = 1
        strategy.scan_235_logic(sample)
        self.assertEqual(strategy.stage_235, 3)
        strategy.dir_1m = -1
        strategy.scan_235_logic(sample)
        self.assertEqual(strategy.stage_235, 4)
        strategy.dir_1m = 1
        strategy.scan_235_logic(sample)
        self.assertEqual(strategy.stage_235, 0)
        self.assertEqual(strategy.stats["fire_235"], 1)
        self.assertEqual(len(engine.orders), 1)
        self.assertEqual(engine.orders[0].direction, "LONG")

    def test_alignment_break_resets_stage(self):
        engine = PaperCtaEngine()
        strategy = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {})
        engine.strategy = strategy
        strategy.stage_235 = 2
        strategy.dir_4h = 1
        strategy.dir_1h = -1
        sample = BarData(symbol="CU", exchange="SHFE", datetime=datetime(2024, 1, 2, 10, 0), open_price=1, high_price=1, low_price=1, close_price=1, volume=1)
        strategy.scan_235_logic(sample)
        self.assertEqual(strategy.stage_235, 0)

    def test_exit_is_not_duplicated_while_the_first_order_rests(self):
        engine = PaperCtaEngine()
        strategy = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {})
        engine.strategy = strategy
        strategy.trading = True
        strategy.pos = 1
        strategy.entry_price = 100
        strategy.dir_1m = -1
        strategy.am_1m.atr = lambda n, array=False: 1.0
        sample = BarData(
            symbol="CU",
            exchange="SHFE",
            datetime=datetime(2024, 1, 2, 10, 0),
            open_price=100,
            high_price=100,
            low_price=100,
            close_price=100,
            volume=1,
        )
        strategy.check_exit(sample)
        strategy.check_exit(sample)
        self.assertEqual(len(engine.active), 1)
        self.assertGreaterEqual(len(engine.orders), 1)

    def test_zero_atr_exit_does_not_raise(self):
        engine = PaperCtaEngine()
        strategy = Production_Hybrid_Monitor(engine, "test", "CU.SHFE", {})
        engine.strategy = strategy
        strategy.pos = 1
        strategy.entry_price = 100
        strategy.am_1m.atr = lambda n, array=False: 0.0
        sample = BarData(symbol="CU", exchange="SHFE", datetime=datetime(2024, 1, 2, 10, 0), open_price=100, high_price=100, low_price=100, close_price=100, volume=1)
        strategy.check_exit(sample)
        self.assertEqual(strategy.stats["exits"], 0)

    def test_flat_history_initializes_four_hour_without_inventing_pnl(self):
        engine, strategy = replay(Production_Hybrid_Monitor, flat_bars(8400))
        self.assertEqual(strategy.stats["four_hour_bars"], 35)
        self.assertTrue(strategy.am_4h.inited)
        self.assertEqual(strategy.stats["fire_235"], 0)
        self.assertEqual(strategy.stats["fire_1235"], 0)
        self.assertEqual(engine.ledger.closed, [])
        self.assertIsNone(engine.ledger.unrealized(100))

    def test_sources_do_not_chain_hour_bars_through_a_minute_generator(self):
        for path in ROOT.glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0]
                self.assertNotIn("on_1h_bar, 4", code)
                self.assertNotIn("on_1h_bar,4", code)


class FillTests(unittest.TestCase):
    def test_limit_cross_matches_next_bar_vnpy_prices(self):
        engine = PaperCtaEngine()

        class Holder:
            pos = 0

            def on_bar(self, _bar):
                pass

            def on_trade(self, _trade):
                pass

        engine.strategy = Holder()
        first = BarData(symbol="CU", exchange="SHFE", datetime=datetime(2024, 1, 2, 10, 0), open_price=100, high_price=101, low_price=99, close_price=100, volume=1)
        engine.new_bar(first)
        engine.send_order(engine.strategy, "LONG", "OPEN", 100, 1)
        second = BarData(symbol="CU", exchange="SHFE", datetime=datetime(2024, 1, 2, 10, 1), open_price=100, high_price=102, low_price=98, close_price=101, volume=1)
        engine.new_bar(second)
        self.assertEqual(engine.strategy.pos, 1)
        self.assertEqual(engine.trades[0].price, 100)
        engine.send_order(engine.strategy, "SHORT", "CLOSE", 102, 1)
        third = BarData(symbol="CU", exchange="SHFE", datetime=datetime(2024, 1, 2, 10, 2), open_price=103, high_price=104, low_price=102, close_price=103, volume=1)
        engine.new_bar(third)
        self.assertEqual(engine.strategy.pos, 0)
        self.assertEqual(engine.trades[1].price, 103)
        self.assertEqual(engine.ledger.realized, 3)
        self.assertEqual(len(engine.ledger.closed), 1)


if __name__ == "__main__":
    unittest.main()
