"""Paper keepers from the frozen screen. Live orders are refused."""

from __future__ import annotations

import json
from pathlib import Path

from vnpy_compat import CtaTemplate

REPORT = Path(__file__).resolve().parent / "output" / "qualified_strategies_report.json"


class KeeperTemplate(CtaTemplate):
    allow_live_trading = False
    parameters = ["allow_live_trading"]
    author = "paper-screen"
    family = ""
    timeframe = ""
    keeper_params: dict = {}

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting or {})
        self.allow_live_trading = False
        self.live_deny_count = 0

    def send_order(self, direction, offset, price, volume, stop=False, lock=False, net=False):
        mode = getattr(self.cta_engine, "execution_mode", None)
        paper = mode in {"PAPER", "BACKTEST"} or self.cta_engine.__class__.__name__ in {
            "PaperCtaEngine",
            "BacktestingEngine",
        }
        if not paper:
            self.live_deny_count += 1
            self.write_log("LIVE_DENY keeper cannot send real-money orders")
            return []
        return super().send_order(direction, offset, price, volume, stop, lock, net)


def _load_rows() -> list:
    if not REPORT.exists():
        return []
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    return list(payload.get("keepers") or [])


def _build(row: dict):
    class Generated(KeeperTemplate):
        family = row["family"]
        timeframe = row["timeframe"]
        keeper_params = dict(row["params"])

    Generated.__name__ = row["class_name"]
    return Generated


KEEPER_ROWS = _load_rows()
KEEPERS = []
for _row in KEEPER_ROWS:
    _cls = _build(_row)
    globals()[_cls.__name__] = _cls
    KEEPERS.append(_cls)
