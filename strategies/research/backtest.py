"""Next-open paper backtest.

A signal at the close of bar t is filled at the open of bar t+1.
Realized points exist only after a round trip closes. Open positions are not given a PnL.
"""

from __future__ import annotations

import numpy as np

from quality_observation import summarize_closed


def run_backtest(open_prices, signal, fill: str = "next_open") -> list:
    opens = np.asarray(open_prices, dtype=float)
    desired = np.asarray(signal, dtype=float)
    if len(opens) != len(desired):
        raise ValueError("signal and opens must have the same length")
    position = np.zeros(len(opens), dtype=float)
    if fill == "next_open" and len(opens) > 1:
        position[1:] = desired[:-1]
    elif fill == "same_open":
        position[:] = desired
    else:
        raise ValueError(f"unknown fill {fill}")
    trades = []
    current = 0.0
    entry_index = None
    entry_price = None
    for index in range(len(opens)):
        nxt = float(position[index])
        if nxt == current:
            continue
        if current != 0.0 and entry_index is not None:
            points = (float(opens[index]) - float(entry_price)) * current
            trades.append(
                {
                    "points": float(points),
                    "entry_index": int(entry_index),
                    "decision_index": int(entry_index if fill == "same_open" else entry_index - 1),
                    "exit_index": int(index),
                    "entry_price": float(entry_price),
                    "exit_price": float(opens[index]),
                    "side": "LONG" if current > 0 else "SHORT",
                }
            )
        if nxt != 0.0:
            entry_index = index
            entry_price = float(opens[index])
        else:
            entry_index = None
            entry_price = None
        current = nxt
    return trades


def split_trades(trades: list, split_index: int) -> tuple:
    train, holdout = [], []
    for trade in trades:
        if trade["decision_index"] >= split_index:
            holdout.append(trade)
        else:
            train.append(trade)
    return train, holdout


def score_frame(open_prices, signal, split_fraction: float = 0.70, fill: str = "next_open") -> dict:
    trades = run_backtest(open_prices, signal, fill=fill)
    split_index = int(len(open_prices) * split_fraction)
    train, holdout = split_trades(trades, split_index)
    return {
        "split_index": split_index,
        "train": summarize_closed(train),
        "holdout": summarize_closed(holdout),
    }
