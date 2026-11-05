"""Fold 1-minute bars with the same hour rules as vn.py BarGenerator.

Minute 59 closes an hour. An hour change closes an unfinished hour.
The minute==59 check happens first, and the hour comparison does not
look at the calendar date. That matches vn.py, including its quirk.
Four-hour bars count finished hour bars; they are not clock-aligned.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def _stamp_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def resample_hours(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    idx = frame.index
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    volumes = frame["volume"].to_numpy(dtype=float) if "volume" in frame.columns else None
    stamps = idx.to_pydatetime()
    rows = []
    hour_bar = None
    for i, dt in enumerate(stamps):
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        volume = 0.0 if volumes is None else float(volumes[i])
        if hour_bar is None:
            hour_bar = [_stamp_hour(dt), float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]), volume]
            continue
        if dt.minute == 59:
            hour_bar[2] = max(hour_bar[2], float(highs[i]))
            hour_bar[3] = min(hour_bar[3], float(lows[i]))
            hour_bar[4] = float(closes[i])
            hour_bar[5] += volume
            rows.append(hour_bar)
            hour_bar = None
        elif dt.hour != hour_bar[0].hour:
            rows.append(hour_bar)
            hour_bar = [_stamp_hour(dt), float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]), volume]
        else:
            hour_bar[2] = max(hour_bar[2], float(highs[i]))
            hour_bar[3] = min(hour_bar[3], float(lows[i]))
            hour_bar[4] = float(closes[i])
            hour_bar[5] += volume
    out = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    if out.empty:
        return out
    return out.set_index("datetime")


def resample_four_hours(hour_frame: pd.DataFrame) -> pd.DataFrame:
    """Count every four finished hour bars, matching vn.py interval_count."""
    if hour_frame is None or len(hour_frame) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    rows = []
    window = None
    count = 0
    for dt, row in hour_frame.iterrows():
        if window is None:
            window = [dt, float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume)]
        else:
            window[2] = max(window[2], float(row.high))
            window[3] = min(window[3], float(row.low))
            window[4] = float(row.close)
            window[5] += float(row.volume)
        count += 1
        if count % 4 == 0:
            rows.append(window)
            window = None
            count = 0
    out = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
    if out.empty:
        return out
    return out.set_index("datetime")
