"""Shared CTA logic for the 2=3=5 / 1=23=5 production scripts.

The previous files asked a minute-mode bar generator for a 4-bar window
and fed it hour bars. Hour bars are stamped at minute 0, and a minute
window finishes only when ``(minute + 1) % window == 0``, so the 4-hour
callback never ran. ``am_4h.inited`` stayed false and ``on_bar`` returned
before any signal. 1-hour and 4-hour bars are now both folded from
1-minute bars with ``Interval.HOUR``, which is the vn.py rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_VEIGHNA = Path("C:/veighna_studio/Lib/site-packages")
for _path in (_VEIGHNA, _DIR):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from vnpy_ctastrategy import ArrayManager, BarGenerator, CtaTemplate
    from vnpy.trader.constant import Interval
    from vnpy.trader.object import BarData
except ImportError:
    try:
        from vnpy.app.cta_strategy import ArrayManager, BarGenerator, CtaTemplate
        from vnpy.trader.constant import Interval
        from vnpy.trader.object import BarData
    except ImportError:
        from vnpy_compat import ArrayManager, BarData, BarGenerator, CtaTemplate, Interval


def as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


class HybridCtaBase(CtaTemplate):
    author = "Architect"

    fast_window = 10
    atr_window = 20
    low_pnl_atr = 1.5
    mid_pnl_atr = 3.5
    fixed_size = 1
    total_pos_limit = 1
    price_offset = 2.0
    allow_live_trading = False
    bar_warmup_days = 120
    alignment_mode = "strict"
    exit_mode = "absolute"

    parameters = [
        "fast_window",
        "atr_window",
        "low_pnl_atr",
        "mid_pnl_atr",
        "fixed_size",
        "total_pos_limit",
        "price_offset",
        "allow_live_trading",
        "bar_warmup_days",
        "alignment_mode",
        "exit_mode",
    ]
    variables = [
        "dir_4h",
        "dir_1h",
        "dir_15m",
        "dir_1m",
        "stage_235",
        "stage_1235",
        "entry_price",
    ]

    enable_235 = True
    enable_1235 = True
    log_heartbeat = False

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.allow_live_trading = as_bool(self.allow_live_trading)
        if self.alignment_mode not in {"strict", "four_hour_lead"}:
            raise ValueError(f"alignment_mode must be strict or four_hour_lead, got {self.alignment_mode!r}")
        if self.exit_mode not in {"absolute", "signed"}:
            raise ValueError(f"exit_mode must be absolute or signed, got {self.exit_mode!r}")
        if float(self.mid_pnl_atr) <= float(self.low_pnl_atr):
            raise ValueError("mid_pnl_atr must be greater than low_pnl_atr")

        self.dir_4h = 0
        self.dir_1h = 0
        self.dir_15m = 0
        self.dir_1m = 0
        self.stage_235 = 0
        self.stage_1235 = 0
        self.entry_price = 0.0
        self._entry_submitted = False
        self._exit_submitted = False
        self.live_deny_count = 0
        self.last_log_time = None
        self.stats = {
            "bars_seen": 0,
            "bars_ready": 0,
            "align_235": 0,
            "four_hour_bars": 0,
            "hour_bars": 0,
            "m15_bars": 0,
            "stage235_2": 0,
            "stage235_3": 0,
            "stage235_4": 0,
            "stage1235_2": 0,
            "stage1235_3": 0,
            "stage1235_4": 0,
            "fire_235": 0,
            "fire_1235": 0,
            "exits": 0,
            "order_blocked": 0,
        }

        am_1m_size = max(30, int(self.atr_window) + 2, int(self.fast_window) + 2)
        self.am_4h = ArrayManager(35)
        self.am_1h = ArrayManager(30)
        self.am_15m = ArrayManager(30)
        self.am_1m = ArrayManager(am_1m_size)
        # 15-minute: minute window, 15 divides 60.
        # 1-hour and 4-hour: hour interval fed with 1-minute bars.
        # Do not chain the 4-hour generator off on_1h_bar in minute mode.
        self.bg_15m = BarGenerator(self.on_bar, 15, self.on_15m_bar, Interval.MINUTE)
        self.bg_1h = BarGenerator(self.on_bar, 1, self.on_1h_bar, Interval.HOUR)
        self.bg_4h = BarGenerator(self.on_bar, 4, self.on_4h_bar, Interval.HOUR)

    def on_init(self):
        self.write_log(f"开始预热 {self.bar_warmup_days} 天数据以初始化 4H 指标...")
        self.load_bar(int(self.bar_warmup_days))

    def on_bar(self, bar: BarData):
        self.stats["bars_seen"] += 1
        self.bg_15m.update_bar(bar)
        self.bg_1h.update_bar(bar)
        self.bg_4h.update_bar(bar)
        self.am_1m.update_bar(bar)

        if not (self.am_1m.inited and self.am_4h.inited):
            return

        if self._paper_like() and not self.trading:
            self.trading = True
            self.inited = True

        self.stats["bars_ready"] += 1
        self.dir_1m = self._direction(bar.close_price, self.am_1m)
        if self.pos == 0 and self._active_orders() == 0:
            self._entry_submitted = False
            self._exit_submitted = False

        if self.log_heartbeat:
            if not self.last_log_time or (bar.datetime - self.last_log_time).days >= 1:
                self.write_log(
                    f"[逻辑心跳] 4H:{self.dir_4h} | 1H:{self.dir_1h} | 15M:{self.dir_15m} | "
                    f"1M:{self.dir_1m} | 235阶段:{self.stage_235} | 1235阶段:{self.stage_1235}"
                )
                self.last_log_time = bar.datetime

        if self._can_enter():
            if self.enable_235:
                self.scan_235_logic(bar)
            if self.enable_1235 and self._can_enter():
                self.scan_1235_logic(bar)

        if self.pos != 0:
            self.check_exit(bar)

    def _paper_like(self) -> bool:
        mode = getattr(self.cta_engine, "execution_mode", None)
        if mode in {"PAPER", "BACKTEST"}:
            return True
        return self.cta_engine.__class__.__name__ in {"PaperCtaEngine", "BacktestingEngine"}

    def _execution_allowed(self) -> bool:
        if as_bool(self.allow_live_trading):
            return True
        return self._paper_like()

    def send_order(self, direction, offset, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        if not self._execution_allowed():
            self.live_deny_count += 1
            self.write_log("LIVE_DENY real-money order blocked; allow_live_trading default is false")
            return []
        return super().send_order(direction, offset, price, volume, stop, lock, net)

    def _active_orders(self) -> int:
        counter = getattr(self.cta_engine, "active_order_count", None)
        if counter is None:
            return 0
        return int(counter())

    def _can_enter(self) -> bool:
        if abs(self.pos) >= float(self.total_pos_limit):
            return False
        if self._entry_submitted:
            return False
        return True

    def _direction(self, close_price: float, am: ArrayManager) -> int:
        if am.count < int(self.fast_window):
            return 0
        sma = am.sma(int(self.fast_window))
        if sma != sma:
            return 0
        return 1 if close_price > sma else -1

    def _trend_235(self) -> int:
        if self.dir_4h == 0:
            return 0
        if self.alignment_mode == "strict":
            if self.dir_4h == self.dir_1h:
                return self.dir_4h
            return 0
        if self.dir_1h == -self.dir_4h:
            return 0
        return self.dir_4h

    def scan_235_logic(self, bar: BarData):
        trend = self._trend_235()
        if trend != 0:
            self.stats["align_235"] += 1
            if self.stage_235 == 0 and self.dir_15m == -trend:
                self.stage_235 = 2
                self.stats["stage235_2"] += 1
                self.write_log(f"{bar.datetime} - [2=3=5] 进入第 2 阶段：15M 洗盘")
            elif self.stage_235 == 2 and self.dir_15m == trend:
                self.stage_235 = 3
                self.stats["stage235_3"] += 1
                self.write_log(f"{bar.datetime} - [2=3=5] 进入第 3 阶段：15M 回正")
            elif self.stage_235 == 3 and self.dir_1m == -trend:
                self.stage_235 = 4
                self.stats["stage235_4"] += 1
                self.write_log(f"{bar.datetime} - [2=3=5] 进入第 4 阶段：1M 诱空/诱多")
            elif self.stage_235 == 4 and self.dir_1m == trend:
                self.fire_order(trend, "235")
                self.stage_235 = 0
        else:
            if self.stage_235 != 0:
                self.write_log(f"{bar.datetime} - [2=3=5] 趋势共振断开，状态重置")
            self.stage_235 = 0

    def scan_1235_logic(self, bar: BarData):
        if self.dir_4h != 0:
            trend = self.dir_4h
            if self.stage_1235 == 0 and self.dir_1h == -trend and self.dir_15m == -trend:
                self.stage_1235 = 2
                self.stats["stage1235_2"] += 1
                self.write_log(f"{bar.datetime} - [1=23=5] 进入第 2 阶段：深幅洗盘")
            elif self.stage_1235 == 2 and self.dir_1h == trend and self.dir_15m == trend:
                self.stage_1235 = 3
                self.stats["stage1235_3"] += 1
                self.write_log(f"{bar.datetime} - [1=23=5] 进入第 3 阶段：大级别回正")
            elif self.stage_1235 == 3 and self.dir_1m == -trend:
                self.stage_1235 = 4
                self.stats["stage1235_4"] += 1
            elif self.stage_1235 == 4 and self.dir_1m == trend:
                self.fire_order(trend, "1235")
                self.stage_1235 = 0
        else:
            self.stage_1235 = 0

    def fire_order(self, direction: int, label: str):
        if not self._can_enter():
            return
        price = float(self.am_1m.close[-1])
        offset = float(self.price_offset)
        if direction == 1:
            orderids = self.buy(price + offset, self.fixed_size)
        else:
            orderids = self.short(price - offset, self.fixed_size)
        if not orderids:
            self.stats["order_blocked"] += 1
            return
        self._entry_submitted = True
        self.entry_price = price
        key = "fire_235" if label == "235" else "fire_1235"
        self.stats[key] += 1
        self.write_log(f"信号触发开仓 {label}")

    def check_exit(self, bar: BarData):
        atr = self.am_1m.atr(int(self.atr_window))
        if atr is None or atr != atr or atr == 0:
            return
        direction = 1 if self.pos > 0 else -1
        signed = (bar.close_price - self.entry_price) * direction / atr
        if self.exit_mode == "absolute":
            distance = abs(signed)
            if distance < self.low_pnl_atr and self.dir_1m == -direction:
                self.close_pos(bar, "低幅度 1M 反转退出")
            elif self.low_pnl_atr <= distance < self.mid_pnl_atr and self.dir_15m == -direction:
                self.close_pos(bar, "中幅度 15M 反转退出")
            elif distance >= self.mid_pnl_atr and self.dir_1h == -direction:
                self.close_pos(bar, "高幅度 1H 反转退出")
            return
        if signed <= -float(self.low_pnl_atr) and self.dir_1m == -direction:
            self.close_pos(bar, "亏损达阈值且 1M 反向")
        elif 0 < signed < float(self.low_pnl_atr) and self.dir_1m == -direction:
            self.close_pos(bar, "低获利 1M 反转退出")
        elif float(self.low_pnl_atr) <= signed < float(self.mid_pnl_atr) and self.dir_15m == -direction:
            self.close_pos(bar, "中获利 15M 反转退出")
        elif signed >= float(self.mid_pnl_atr) and self.dir_1h == -direction:
            self.close_pos(bar, "高获利 1H 反转退出")

    def close_pos(self, bar: BarData, reason: str):
        # Keep a single working exit. Stacked sells fill after the position is
        # flat and reverse it, because position changes with order direction.
        # Replacing the working exit lets the limit follow the latest bar.
        canceller = getattr(self.cta_engine, "cancel_all", None)
        if canceller:
            canceller()
            self._exit_submitted = False
        elif self._exit_submitted:
            return
        offset = float(self.price_offset)
        if self.pos > 0:
            orderids = self.sell(bar.close_price - offset, abs(self.pos))
        else:
            orderids = self.cover(bar.close_price + offset, abs(self.pos))
        if not orderids:
            self.stats["order_blocked"] += 1
            return
        self._exit_submitted = True
        self.stats["exits"] += 1
        self.write_log(f"平仓触发: {reason}")

    def on_trade(self, trade):
        if self.pos == 0:
            self._entry_submitted = False
            self._exit_submitted = False

    def on_15m_bar(self, bar: BarData):
        self.stats["m15_bars"] += 1
        self.am_15m.update_bar(bar)
        if self.am_15m.count < int(self.fast_window):
            return
        self.dir_15m = self._direction(bar.close_price, self.am_15m)

    def on_1h_bar(self, bar: BarData):
        self.stats["hour_bars"] += 1
        self.am_1h.update_bar(bar)
        if self.am_1h.count < int(self.fast_window):
            return
        self.dir_1h = self._direction(bar.close_price, self.am_1h)

    def on_4h_bar(self, bar: BarData):
        self.stats["four_hour_bars"] += 1
        self.am_4h.update_bar(bar)
        if self.am_4h.count < int(self.fast_window):
            return
        self.dir_4h = self._direction(bar.close_price, self.am_4h)
