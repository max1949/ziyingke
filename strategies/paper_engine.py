"""Paper CTA engine. Live gateways are refused.

Fills follow vn.py BacktestingEngine.cross_limit_order for bar mode:
a resting limit is eligible on a later bar, long fills when order price >= bar low,
short fills when order price <= bar high, and the fill price is the more
favorable of the limit and that bar's open.
"""

from __future__ import annotations

from typing import List, Optional


def _enum_name(value) -> str:
    name = getattr(value, "name", None)
    if name in {"LONG", "SHORT", "OPEN", "CLOSE"}:
        return name
    raw = getattr(value, "value", value)
    mapping = {
        "LONG": "LONG",
        "SHORT": "SHORT",
        "OPEN": "OPEN",
        "CLOSE": "CLOSE",
        "多": "LONG",
        "空": "SHORT",
        "开": "OPEN",
        "平": "CLOSE",
    }
    if raw not in mapping:
        raise ValueError(f"unsupported order field: {value!r}")
    return mapping[raw]


class PaperOrder:
    def __init__(self, orderid: str, direction: str, offset: str, price: float, volume: float) -> None:
        self.orderid = orderid
        self.direction = direction
        self.offset = offset
        self.price = float(price)
        self.volume = float(volume)
        self.status = "SUBMITTING"


class PaperTrade:
    def __init__(self, tradeid: str, direction: str, offset: str, price: float, volume: float, dt, order_price: float) -> None:
        self.tradeid = tradeid
        self.direction = direction
        self.offset = offset
        self.price = float(price)
        self.volume = float(volume)
        self.datetime = dt
        self.order_price = float(order_price)

    def as_dict(self) -> dict:
        return {
            "tradeid": self.tradeid,
            "direction": self.direction,
            "offset": self.offset,
            "price": self.price,
            "volume": self.volume,
            "datetime": self.datetime.isoformat() if hasattr(self.datetime, "isoformat") else str(self.datetime),
            "order_price": self.order_price,
        }


class PositionLedger:
    """Realized points come only from fills. Open PnL stays a separate mark."""

    def __init__(self) -> None:
        self.pos = 0.0
        self.avg = 0.0
        self.realized = 0.0
        self.closed: List[dict] = []
        self.entry_time = None
        self.entry_price = None

    def apply(self, trade: PaperTrade) -> None:
        qty = trade.volume if trade.direction == "LONG" else -trade.volume
        if self.pos == 0 or self.pos * qty > 0:
            new_pos = self.pos + qty
            if self.pos == 0:
                self.entry_time = trade.datetime
                self.entry_price = trade.price
                self.avg = trade.price
            else:
                self.avg = (self.avg * abs(self.pos) + trade.price * abs(qty)) / abs(new_pos)
            self.pos = new_pos
            return

        close_qty = min(abs(self.pos), abs(qty))
        sign = 1.0 if self.pos > 0 else -1.0
        points = (trade.price - self.avg) * sign * close_qty
        self.realized += points
        self.closed.append(
            {
                "points": points,
                "volume": close_qty,
                "entry_time": self.entry_time,
                "entry_price": self.entry_price,
                "exit_time": trade.datetime,
                "exit_price": trade.price,
                "side": "LONG" if sign > 0 else "SHORT",
            }
        )
        self.pos = self.pos + qty
        if self.pos == 0:
            self.avg = 0.0
            self.entry_time = None
            self.entry_price = None
        else:
            self.avg = trade.price
            self.entry_time = trade.datetime
            self.entry_price = trade.price

    def unrealized(self, mark: float) -> Optional[float]:
        if self.pos == 0:
            return None
        return (float(mark) - self.avg) * self.pos


class PaperCtaEngine:
    execution_mode = "PAPER"

    def __init__(self) -> None:
        self.strategy = None
        self.logs: List[str] = []
        self.orders: List[PaperOrder] = []
        self.trades: List[PaperTrade] = []
        self.active: dict = {}
        self.ledger = PositionLedger()
        self._seq = 0
        self.bar = None
        self.load_bar_calls = []

    def write_log(self, msg: str, strategy=None) -> None:
        if len(self.logs) < 2000:
            self.logs.append(str(msg))

    def load_bar(self, vt_symbol, days, interval, callback, use_database: bool = False) -> None:
        self.load_bar_calls.append({"vt_symbol": vt_symbol, "days": days, "interval": str(interval)})

    def active_order_count(self) -> int:
        return len(self.active)

    def cancel_all(self) -> None:
        for order in self.active.values():
            order.status = "CANCELLED"
        self.active.clear()

    def send_order(self, strategy, direction, offset, price, volume, stop=False, lock=False, net=False):
        if self.execution_mode == "LIVE":
            self.write_log("LIVE_DENY paper engine refused a live gateway send", strategy)
            return []
        if stop:
            self.write_log("STOP_ORDER_NOT_USED limit orders only", strategy)
        self._seq += 1
        order = PaperOrder(str(self._seq), _enum_name(direction), _enum_name(offset), price, volume)
        self.orders.append(order)
        self.active[order.orderid] = order
        return [order.orderid]

    def new_bar(self, bar) -> None:
        self.bar = bar
        self.cross_limit_orders()
        strategy = self.strategy
        if strategy is None:
            return
        strategy.on_bar(bar)

    def cross_limit_orders(self) -> None:
        bar = self.bar
        if bar is None:
            return
        long_cross_price = bar.low_price
        short_cross_price = bar.high_price
        long_best = bar.open_price
        short_best = bar.open_price
        for order in list(self.active.values()):
            if order.status == "SUBMITTING":
                order.status = "NOTTRADED"
            long_cross = (
                order.direction == "LONG"
                and long_cross_price > 0
                and order.price >= long_cross_price
            )
            short_cross = (
                order.direction == "SHORT"
                and short_cross_price > 0
                and order.price <= short_cross_price
            )
            if not long_cross and not short_cross:
                continue
            order.status = "ALLTRADED"
            self.active.pop(order.orderid, None)
            if long_cross:
                trade_price = min(order.price, long_best)
                pos_change = order.volume
            else:
                trade_price = max(order.price, short_best)
                pos_change = -order.volume
            self._seq += 1
            trade = PaperTrade(
                str(self._seq),
                order.direction,
                order.offset,
                trade_price,
                order.volume,
                bar.datetime,
                order.price,
            )
            self.trades.append(trade)
            self.ledger.apply(trade)
            if self.strategy is not None:
                self.strategy.pos += pos_change
                self.strategy.on_trade(trade)
