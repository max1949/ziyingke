"""Close-only signals. Bar t may use prices through the close of bar t and no later bar."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(values: np.ndarray, length: int) -> np.ndarray:
    alpha = 2.0 / (length + 1.0)
    out = np.empty(len(values), dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _sma(values: np.ndarray, length: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if length <= 0 or len(values) < length:
        return out
    window = np.cumsum(values)
    out[length - 1] = window[length - 1] / length
    for i in range(length, len(values)):
        out[i] = (window[i] - window[i - length]) / length
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(close), np.nan)
    if len(close) <= length:
        return out
    out[length] = float(np.mean(tr[1 : length + 1]))
    for i in range(length + 1, len(close)):
        out[i] = (out[i - 1] * (length - 1) + tr[i]) / length
    return out


def _rsi(close: np.ndarray, length: int) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, 0, None)
    out = np.full(len(close), np.nan)
    if len(close) <= length:
        return out
    avg_gain = float(np.mean(gain[1 : length + 1]))
    avg_loss = float(np.mean(loss[1 : length + 1]))
    out[length] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(length + 1, len(close)):
        avg_gain = (avg_gain * (length - 1) + gain[i]) / length
        avg_loss = (avg_loss * (length - 1) + loss[i]) / length
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def _hold(entry_long, entry_short, exit_long, exit_short, flat_at=None) -> np.ndarray:
    signal = np.zeros(len(entry_long), dtype=float)
    pos = 0.0
    for i in range(len(signal)):
        if flat_at is not None and flat_at[i]:
            pos = 0.0
        elif pos > 0 and exit_long[i]:
            pos = 0.0
        elif pos < 0 and exit_short[i]:
            pos = 0.0
        if pos == 0.0:
            if entry_long[i]:
                pos = 1.0
            elif entry_short[i]:
                pos = -1.0
        elif pos > 0 and entry_short[i] and not entry_long[i]:
            pos = -1.0
        elif pos < 0 and entry_long[i] and not entry_short[i]:
            pos = 1.0
        signal[i] = pos
    return signal


def _cross_hold(fast: np.ndarray, slow: np.ndarray, long_only: bool = False, short_only: bool = False) -> np.ndarray:
    signal = np.zeros(len(fast), dtype=float)
    for i in range(len(fast)):
        if np.isnan(fast[i]) or np.isnan(slow[i]):
            signal[i] = 0.0
            continue
        if fast[i] > slow[i] and not short_only:
            signal[i] = 1.0
        elif fast[i] < slow[i] and not long_only:
            signal[i] = -1.0
        else:
            signal[i] = 0.0
    return signal


def _donchian_edges(high, low, length):
    hh = pd.Series(high).rolling(length, min_periods=length).max().shift(1).to_numpy()
    ll = pd.Series(low).rolling(length, min_periods=length).min().shift(1).to_numpy()
    return hh, ll


def signal_ema_cross(df, params, long_only=False, short_only=False):
    close = df["close"].to_numpy(dtype=float)
    return _cross_hold(_ema(close, int(params["fast"])), _ema(close, int(params["slow"])), long_only, short_only)


def signal_sma_cross(df, params, long_only=False, short_only=False):
    close = df["close"].to_numpy(dtype=float)
    return _cross_hold(_sma(close, int(params["fast"])), _sma(close, int(params["slow"])), long_only, short_only)


def signal_donchian(df, params):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    length = int(params["length"])
    hh, ll = _donchian_edges(high, low, length)
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        if np.isnan(hh[i]) or np.isnan(ll[i]):
            signal[i] = pos
            continue
        if close[i] > hh[i]:
            pos = 1.0
        elif close[i] < ll[i]:
            pos = -1.0
        signal[i] = pos
    return signal


def signal_keltner(df, params):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    mid = _ema(close, int(params["length"]))
    atr = _atr(high, low, close, int(params["length"]))
    width = float(params["width"]) * atr
    upper = mid + width
    lower = mid - width
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        if np.isnan(upper[i]):
            signal[i] = 0.0
            continue
        if close[i] > upper[i]:
            pos = 1.0
        elif close[i] < lower[i]:
            pos = -1.0
        signal[i] = pos
    return signal


def signal_bb(df, params, fade: bool):
    close = df["close"].to_numpy(dtype=float)
    length = int(params["length"])
    mid = _sma(close, length)
    std = pd.Series(close).rolling(length, min_periods=length).std(ddof=0).to_numpy()
    upper = mid + float(params["width"]) * std
    lower = mid - float(params["width"]) * std
    if fade:
        entry_long = close < lower
        entry_short = close > upper
        exit_long = close >= mid
        exit_short = close <= mid
        entry_long = np.where(np.isnan(lower), False, entry_long)
        entry_short = np.where(np.isnan(upper), False, entry_short)
        exit_long = np.where(np.isnan(mid), False, exit_long)
        exit_short = np.where(np.isnan(mid), False, exit_short)
        return _hold(entry_long, entry_short, exit_long, exit_short)
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        if np.isnan(upper[i]):
            signal[i] = pos
            continue
        if close[i] > upper[i]:
            pos = 1.0
        elif close[i] < lower[i]:
            pos = -1.0
        signal[i] = pos
    return signal


def signal_rsi_fade(df, params):
    close = df["close"].to_numpy(dtype=float)
    rsi = _rsi(close, int(params["length"]))
    low = float(params["low"])
    high = float(params["high"])
    entry_long = rsi < low
    entry_short = rsi > high
    exit_long = rsi >= 50
    exit_short = rsi <= 50
    for arr in (entry_long, entry_short, exit_long, exit_short):
        np.nan_to_num(arr, copy=False, nan=0.0)
    return _hold(entry_long.astype(bool), entry_short.astype(bool), exit_long.astype(bool), exit_short.astype(bool))


def signal_zscore(df, params):
    close = df["close"].to_numpy(dtype=float)
    length = int(params["length"])
    mid = _sma(close, length)
    std = pd.Series(close).rolling(length, min_periods=length).std(ddof=0).to_numpy()
    z = (close - mid) / std
    level = float(params["level"])
    entry_long = z < -level
    entry_short = z > level
    exit_long = z >= 0
    exit_short = z <= 0
    valid = ~np.isnan(z)
    return _hold(valid & entry_long, valid & entry_short, valid & exit_long, valid & exit_short)


def signal_consec(df, params):
    close = df["close"].to_numpy(dtype=float)
    n = int(params["length"])
    down = np.zeros(len(close), dtype=bool)
    up = np.zeros(len(close), dtype=bool)
    for i in range(n, len(close)):
        window = close[i - n + 1 : i + 1]
        prev = close[i - n : i]
        down[i] = bool(np.all(window < prev))
        up[i] = bool(np.all(window > prev))
    entry_long = down
    entry_short = up
    exit_long = close > pd.Series(close).rolling(n, min_periods=n).mean().to_numpy()
    exit_short = close < pd.Series(close).rolling(n, min_periods=n).mean().to_numpy()
    exit_long = np.where(np.isnan(exit_long), False, exit_long)
    exit_short = np.where(np.isnan(exit_short), False, exit_short)
    return _hold(entry_long, entry_short, exit_long.astype(bool), exit_short.astype(bool))


def signal_ts_momentum(df, params):
    close = df["close"].to_numpy(dtype=float)
    n = int(params["length"])
    ret = np.full(len(close), np.nan)
    ret[n:] = close[n:] - close[:-n]
    signal = np.zeros(len(close))
    signal[ret > 0] = 1.0
    signal[ret < 0] = -1.0
    return signal


def signal_roc(df, params):
    return signal_ts_momentum(df, params)


def signal_macd(df, params):
    close = df["close"].to_numpy(dtype=float)
    macd = _ema(close, int(params["fast"])) - _ema(close, int(params["slow"]))
    line = _ema(macd, int(params["signal"]))
    return _cross_hold(macd, line)


def signal_triple(df, params):
    close = df["close"].to_numpy(dtype=float)
    fast = _ema(close, int(params["fast"]))
    mid = _ema(close, int(params["mid"]))
    slow = _ema(close, int(params["slow"]))
    signal = np.zeros(len(close))
    long = (fast > mid) & (mid > slow)
    short = (fast < mid) & (mid < slow)
    signal[long] = 1.0
    signal[short] = -1.0
    return signal


def signal_pullback(df, params):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    slow = _ema(close, int(params["slow"]))
    fast = _ema(close, int(params["fast"]))
    atr = _atr(high, low, close, 14)
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        if np.isnan(slow[i]) or np.isnan(fast[i]) or np.isnan(atr[i]):
            signal[i] = pos
            continue
        trend_up = close[i] > slow[i]
        trend_down = close[i] < slow[i]
        touched = abs(close[i] - fast[i]) <= atr[i]
        resume_up = close[i] > fast[i]
        resume_down = close[i] < fast[i]
        if trend_up and touched and resume_up:
            pos = 1.0
        elif trend_down and touched and resume_down:
            pos = -1.0
        elif trend_up and close[i] < slow[i]:
            pos = 0.0
        elif trend_down and close[i] > slow[i]:
            pos = 0.0
        signal[i] = pos
    return signal


def signal_rsi_dip(df, params):
    close = df["close"].to_numpy(dtype=float)
    trend = _ema(close, int(params["trend"]))
    rsi = _rsi(close, int(params["rsi"]))
    dip = float(params["dip"])
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        if np.isnan(trend[i]) or np.isnan(rsi[i]):
            signal[i] = pos
            continue
        if close[i] > trend[i] and rsi[i] < dip:
            pos = 1.0
        elif close[i] < trend[i] and rsi[i] > 100 - dip:
            pos = -1.0
        elif pos > 0 and (close[i] < trend[i] or rsi[i] > 55):
            pos = 0.0
        elif pos < 0 and (close[i] > trend[i] or rsi[i] < 45):
            pos = 0.0
        signal[i] = pos
    return signal


def signal_gap(df, params, fade: bool):
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    threshold = float(params["threshold"])
    signal = np.zeros(len(close))
    for i in range(1, len(close)):
        base = close[i - 1]
        if base == 0:
            continue
        gap = open_[i] / base - 1.0
        if gap > threshold:
            signal[i] = -1.0 if fade else 1.0
        elif gap < -threshold:
            signal[i] = 1.0 if fade else -1.0
    # Decision uses today's open. Shift so the backtest, which fills next open
    # from the previous close-signal, instead treats this as an open decision
    # for the same bar: store it one bar earlier is wrong. Callers use
    # score_open_signal for this family.
    return signal


def signal_nr_break(df, params):
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    length = int(params["length"])
    ratio = float(params["ratio"])
    span = high - low
    median = pd.Series(span).rolling(length, min_periods=length).median().shift(1).to_numpy()
    hh, ll = _donchian_edges(high, low, length)
    signal = np.zeros(len(close))
    pos = 0.0
    armed = False
    for i in range(len(close)):
        if np.isnan(median[i]) or np.isnan(hh[i]):
            signal[i] = pos
            continue
        if span[i] < median[i] * ratio:
            armed = True
        if armed and close[i] > hh[i]:
            pos = 1.0
            armed = False
        elif armed and close[i] < ll[i]:
            pos = -1.0
            armed = False
        signal[i] = pos
    return signal


def signal_squeeze(df, params):
    close = df["close"].to_numpy(dtype=float)
    length = int(params["length"])
    mid = _sma(close, length)
    std = pd.Series(close).rolling(length, min_periods=length).std(ddof=0)
    width = (float(params["width"]) * std / pd.Series(mid)).to_numpy()
    rank = pd.Series(width).rolling(length, min_periods=length).quantile(float(params["quantile"])).shift(1).to_numpy()
    hh, ll = _donchian_edges(df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float), length)
    signal = np.zeros(len(close))
    pos = 0.0
    armed = False
    for i in range(len(close)):
        if np.isnan(rank[i]) or np.isnan(width[i]) or np.isnan(hh[i]):
            signal[i] = pos
            continue
        if width[i] < rank[i]:
            armed = True
        if armed and close[i] > hh[i]:
            pos = 1.0
            armed = False
        elif armed and close[i] < ll[i]:
            pos = -1.0
            armed = False
        signal[i] = pos
    return signal


def signal_chandelier(df, params):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    trend = _ema(close, int(params["trend"]))
    atr = _atr(high, low, close, int(params["atr"]))
    mult = float(params["mult"])
    signal = np.zeros(len(close))
    pos = 0.0
    extreme = None
    for i in range(len(close)):
        if np.isnan(trend[i]) or np.isnan(atr[i]):
            signal[i] = pos
            continue
        if pos > 0:
            extreme = high[i] if extreme is None else max(extreme, high[i])
            if close[i] < extreme - mult * atr[i] or close[i] < trend[i]:
                pos = 0.0
                extreme = None
        elif pos < 0:
            extreme = low[i] if extreme is None else min(extreme, low[i])
            if close[i] > extreme + mult * atr[i] or close[i] > trend[i]:
                pos = 0.0
                extreme = None
        if pos == 0.0:
            if close[i] > trend[i]:
                pos = 1.0
                extreme = high[i]
            elif close[i] < trend[i]:
                pos = -1.0
                extreme = low[i]
        signal[i] = pos
    return signal


def _calendar_ids(index: pd.DatetimeIndex) -> np.ndarray:
    return index.normalize().to_numpy()


def signal_prior_day(df, params=None):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    days = _calendar_ids(df.index)
    day_high = {}
    day_low = {}
    for i, day in enumerate(days):
        day_high[day] = max(day_high.get(day, high[i]), high[i])
        day_low[day] = min(day_low.get(day, low[i]), low[i])
    signal = np.zeros(len(close))
    pos = 0.0
    prev_day = None
    y_high = None
    y_low = None
    for i, day in enumerate(days):
        if prev_day is None:
            prev_day = day
        elif day != prev_day:
            y_high = day_high[prev_day]
            y_low = day_low[prev_day]
            prev_day = day
            pos = 0.0
        if y_high is None:
            signal[i] = 0.0
            continue
        if close[i] > y_high:
            pos = 1.0
        elif close[i] < y_low:
            pos = -1.0
        signal[i] = pos
    return signal


def signal_orb(df, params=None):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    days = _calendar_ids(df.index)
    signal = np.zeros(len(close))
    pos = 0.0
    current = None
    first_high = None
    first_low = None
    seen = 0
    for i, day in enumerate(days):
        if day != current:
            current = day
            first_high = high[i]
            first_low = low[i]
            seen = 1
            pos = 0.0
            signal[i] = 0.0
            continue
        seen += 1
        last = i + 1 == len(days) or days[i + 1] != day
        if seen > 1 and not last:
            if close[i] > first_high:
                pos = 1.0
            elif close[i] < first_low:
                pos = -1.0
        if last:
            pos = 0.0
        signal[i] = pos
    return signal


def signal_mtf_dip(df, params, daily: pd.DataFrame):
    """Hourly RSI dip only in the direction of the previous completed daily EMA."""
    close = df["close"].to_numpy(dtype=float)
    rsi = _rsi(close, int(params["rsi"]))
    daily_close = daily["close"].to_numpy(dtype=float)
    trend = _ema(daily_close, int(params["trend"]))
    daily_dir = np.where(daily_close > trend, 1.0, np.where(daily_close < trend, -1.0, 0.0))
    daily_dir = pd.Series(daily_dir, index=daily.index).shift(1)
    mapped = daily_dir.reindex(df.index.normalize()).to_numpy()
    dip = float(params["dip"])
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        direction = mapped[i]
        if np.isnan(rsi[i]) or np.isnan(direction):
            signal[i] = pos
            continue
        if direction > 0 and rsi[i] < dip:
            pos = 1.0
        elif direction < 0 and rsi[i] > 100 - dip:
            pos = -1.0
        elif pos > 0 and (direction <= 0 or rsi[i] > 60):
            pos = 0.0
        elif pos < 0 and (direction >= 0 or rsi[i] < 40):
            pos = 0.0
        signal[i] = pos
    return signal


def signal_mtf_break(df, params, higher: pd.DataFrame):
    """Break a 1-hour Donchian only in the direction of the previous 4-hour EMA."""
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    hh, ll = _donchian_edges(high, low, int(params["length"]))
    h_close = higher["close"].to_numpy(dtype=float)
    trend = _ema(h_close, int(params["trend"]))
    h_dir = np.where(h_close > trend, 1.0, np.where(h_close < trend, -1.0, 0.0))
    h_dir = pd.Series(h_dir, index=higher.index).shift(1)
    mapped = h_dir.reindex(df.index, method="ffill").to_numpy()
    signal = np.zeros(len(close))
    pos = 0.0
    for i in range(len(close)):
        direction = mapped[i]
        if np.isnan(hh[i]) or np.isnan(direction):
            signal[i] = pos
            continue
        if direction > 0 and close[i] > hh[i]:
            pos = 1.0
        elif direction < 0 and close[i] < ll[i]:
            pos = -1.0
        elif direction > 0 and close[i] < ll[i]:
            pos = 0.0
        elif direction < 0 and close[i] > hh[i]:
            pos = 0.0
        elif direction == 0:
            pos = 0.0
        signal[i] = pos
    return signal


FAMILY_BUILDERS = {
    "ema_cross": signal_ema_cross,
    "sma_cross": signal_sma_cross,
    "ema_cross_long": lambda df, params: signal_ema_cross(df, params, long_only=True),
    "donchian": signal_donchian,
    "keltner": signal_keltner,
    "bb_break": lambda df, params: signal_bb(df, params, fade=False),
    "bb_fade": lambda df, params: signal_bb(df, params, fade=True),
    "rsi_fade": signal_rsi_fade,
    "zscore": signal_zscore,
    "consec": signal_consec,
    "ts_momentum": signal_ts_momentum,
    "macd": signal_macd,
    "triple_ema": signal_triple,
    "pullback": signal_pullback,
    "rsi_dip": signal_rsi_dip,
    "gap_follow": lambda df, params: signal_gap(df, params, fade=False),
    "gap_fade": lambda df, params: signal_gap(df, params, fade=True),
    "nr_break": signal_nr_break,
    "squeeze": signal_squeeze,
    "chandelier": signal_chandelier,
    "prior_day": signal_prior_day,
    "orb": signal_orb,
    "mtf_dip": signal_mtf_dip,
    "mtf_break": signal_mtf_break,
}
