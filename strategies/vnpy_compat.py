"""Minimal vn.py CTA surface used when veighna's vnpy package is not installed.

BarGenerator matches vnpy/trader/utility.py on master as of 2026-11-06:

- minute windows finish when ``(minute + 1) % window == 0``
- recommended minute windows are the divisors of 60 listed by vn.py
  (2, 3, 5, 6, 10, 15, 20, 30). A 4-hour series is not a minute window.
- hour windows finish on minute == 59, or when the clock hour changes
- the minute==59 branch is checked before the hour-change branch
- multi-hour windows count finished hour bars; they are not clock-aligned
  00/04/08/12/16/20 blocks
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Callable, Optional


class Direction(Enum):
    LONG = "多"
    SHORT = "空"


class Offset(Enum):
    OPEN = "开"
    CLOSE = "平"


class Interval(Enum):
    MINUTE = "1m"
    HOUR = "1h"
    DAILY = "d"


RECOMMENDED_MINUTE_WINDOWS = (2, 3, 5, 6, 10, 15, 20, 30)


def minute_window_divides_60(window: int) -> bool:
    return isinstance(window, int) and window > 0 and (60 % window) == 0


class BarData:
    def __init__(
        self,
        symbol: str = "",
        exchange: str = "",
        datetime: Optional[datetime] = None,
        interval: Optional[Interval] = None,
        volume: float = 0.0,
        turnover: float = 0.0,
        open_interest: float = 0.0,
        open_price: float = 0.0,
        high_price: float = 0.0,
        low_price: float = 0.0,
        close_price: float = 0.0,
        gateway_name: str = "",
    ) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.datetime = datetime
        self.interval = interval
        self.volume = float(volume or 0.0)
        self.turnover = float(turnover or 0.0)
        self.open_interest = float(open_interest or 0.0)
        self.open_price = float(open_price or 0.0)
        self.high_price = float(high_price or 0.0)
        self.low_price = float(low_price or 0.0)
        self.close_price = float(close_price or 0.0)
        self.gateway_name = gateway_name


class ArrayManager:
    """Rolling OHLC window. SMA / ATR are defined on this window, same idea as vn.py."""

    def __init__(self, size: int = 100) -> None:
        self.count = 0
        self.size = int(size)
        self.inited = False
        self.open = [0.0] * self.size
        self.high = [0.0] * self.size
        self.low = [0.0] * self.size
        self.close = [0.0] * self.size
        self.volume = [0.0] * self.size

    def update_bar(self, bar: BarData) -> None:
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True
        for series, value in (
            (self.open, bar.open_price),
            (self.high, bar.high_price),
            (self.low, bar.low_price),
            (self.close, bar.close_price),
            (self.volume, bar.volume),
        ):
            series[:-1] = series[1:]
            series[-1] = float(value)

    def sma(self, n: int, array: bool = False) -> float:
        if n <= 0 or self.count < n:
            return float("nan")
        window = self.close[-n:]
        value = sum(window) / float(n)
        if array:
            return value
        return value

    def atr(self, n: int, array: bool = False) -> float:
        if n <= 0 or len(self.close) < n + 1:
            return float("nan")
        trs = []
        for i in range(1, len(self.close)):
            high = self.high[i]
            low = self.low[i]
            prev = self.close[i - 1]
            trs.append(max(high - low, abs(high - prev), abs(low - prev)))
        if len(trs) < n:
            return float("nan")
        value = sum(trs[:n]) / float(n)
        for tr in trs[n:]:
            value = (value * (n - 1) + tr) / float(n)
        return value


class BarGenerator:
    def __init__(
        self,
        on_bar: Callable,
        window: int = 0,
        on_window_bar: Optional[Callable] = None,
        interval: Interval = Interval.MINUTE,
        daily_end=None,
    ) -> None:
        self.bar = None
        self.on_bar = on_bar
        self.interval = interval
        self.interval_count = 0
        self.hour_bar = None
        self.daily_bar = None
        self.window = window
        self.window_bar = None
        self.on_window_bar = on_window_bar
        self.last_tick = None
        self.daily_end = daily_end
        if self.interval == Interval.DAILY and not self.daily_end:
            raise RuntimeError("合成日K线必须传入每日收盘时间")

    def update_bar(self, bar: BarData) -> None:
        if self.interval == Interval.MINUTE:
            self.update_bar_minute_window(bar)
        elif self.interval == Interval.HOUR:
            self.update_bar_hour_window(bar)
        else:
            raise NotImplementedError("daily bar synthesis is not used by these strategies")

    def update_bar_minute_window(self, bar: BarData) -> None:
        if not self.window_bar:
            dt = bar.datetime.replace(second=0, microsecond=0)
            self.window_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
            )
        else:
            self.window_bar.high_price = max(self.window_bar.high_price, bar.high_price)
            self.window_bar.low_price = min(self.window_bar.low_price, bar.low_price)

        self.window_bar.close_price = bar.close_price
        self.window_bar.volume += bar.volume
        self.window_bar.turnover += bar.turnover
        self.window_bar.open_interest = bar.open_interest

        if self.window and not (bar.datetime.minute + 1) % self.window:
            if self.on_window_bar:
                self.on_window_bar(self.window_bar)
            self.window_bar = None

    def update_bar_hour_window(self, bar: BarData) -> None:
        if not self.hour_bar:
            dt = bar.datetime.replace(minute=0, second=0, microsecond=0)
            self.hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            return

        finished_bar = None
        if bar.datetime.minute == 59:
            self.hour_bar.high_price = max(self.hour_bar.high_price, bar.high_price)
            self.hour_bar.low_price = min(self.hour_bar.low_price, bar.low_price)
            self.hour_bar.close_price = bar.close_price
            self.hour_bar.volume += bar.volume
            self.hour_bar.turnover += bar.turnover
            self.hour_bar.open_interest = bar.open_interest
            finished_bar = self.hour_bar
            self.hour_bar = None
        elif bar.datetime.hour != self.hour_bar.datetime.hour:
            finished_bar = self.hour_bar
            dt = bar.datetime.replace(minute=0, second=0, microsecond=0)
            self.hour_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=dt,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
        else:
            self.hour_bar.high_price = max(self.hour_bar.high_price, bar.high_price)
            self.hour_bar.low_price = min(self.hour_bar.low_price, bar.low_price)
            self.hour_bar.close_price = bar.close_price
            self.hour_bar.volume += bar.volume
            self.hour_bar.turnover += bar.turnover
            self.hour_bar.open_interest = bar.open_interest

        if finished_bar:
            self.on_hour_bar(finished_bar)

    def on_hour_bar(self, bar: BarData) -> None:
        if self.window == 1:
            if self.on_window_bar:
                self.on_window_bar(bar)
            return

        if not self.window_bar:
            self.window_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=bar.datetime,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
            )
        else:
            self.window_bar.high_price = max(self.window_bar.high_price, bar.high_price)
            self.window_bar.low_price = min(self.window_bar.low_price, bar.low_price)

        self.window_bar.close_price = bar.close_price
        self.window_bar.volume += bar.volume
        self.window_bar.turnover += bar.turnover
        self.window_bar.open_interest = bar.open_interest
        self.interval_count += 1
        if self.window and not self.interval_count % self.window:
            self.interval_count = 0
            if self.on_window_bar:
                self.on_window_bar(self.window_bar)
            self.window_bar = None


class CtaTemplate:
    author = ""
    parameters: list = []
    variables: list = []

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        self.cta_engine = cta_engine
        self.strategy_name = strategy_name
        self.vt_symbol = vt_symbol
        self.inited = False
        self.trading = False
        self.pos = 0
        self.update_setting(setting or {})

    def update_setting(self, setting: dict) -> None:
        for name in self.parameters:
            if name in setting:
                setattr(self, name, setting[name])

    def write_log(self, msg: str) -> None:
        writer = getattr(self.cta_engine, "write_log", None)
        if writer:
            writer(msg, self)

    def load_bar(self, days: int, interval: Interval = Interval.MINUTE, callback=None, use_database: bool = False) -> None:
        self.cta_engine.load_bar(self.vt_symbol, days, interval, callback or self.on_bar, use_database)

    def send_order(self, direction, offset, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        if not self.trading:
            return []
        return self.cta_engine.send_order(self, direction, offset, price, volume, stop, lock, net)

    def buy(self, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        return self.send_order(Direction.LONG, Offset.OPEN, price, volume, stop, lock, net)

    def sell(self, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        return self.send_order(Direction.SHORT, Offset.CLOSE, price, volume, stop, lock, net)

    def short(self, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        return self.send_order(Direction.SHORT, Offset.OPEN, price, volume, stop, lock, net)

    def cover(self, price, volume, stop: bool = False, lock: bool = False, net: bool = False):
        return self.send_order(Direction.LONG, Offset.CLOSE, price, volume, stop, lock, net)

    def on_init(self) -> None:
        pass

    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def on_bar(self, bar: BarData) -> None:
        pass

    def on_trade(self, trade) -> None:
        pass

    def on_order(self, order) -> None:
        pass
