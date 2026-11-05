"""Replay local 1-minute bars through the hybrid monitor on a paper engine.

Realized points are the sum of round-trip fill differences. If nothing closes,
realized points stay null. Live orders are forced off.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from paper_engine import PaperCtaEngine
from vnpy_compat import BarData

MIN_OBSERVATION_DAYS = 60
MIN_CLOSED_TRADES = 8
HOLDOUT_FRACTION = 0.30
# Exchange contract sizes (tons or index multiplier). Used only as a labeled
# conversion. They are not a broker statement and are not required for the gate.
CONTRACT_MULTIPLIER = {
    "CU": 5,
    "RB": 10,
    "AU": 1000,
    "AG": 15,
    "IF": 300,
    "IC": 200,
    "IH": 300,
    "SR": 10,
    "MA": 10,
    "TA": 5,
    "I": 100,
}
EXCHANGE = {
    "CU": "SHFE",
    "RB": "SHFE",
    "AU": "SHFE",
    "AG": "SHFE",
    "IF": "CFFEX",
    "IC": "CFFEX",
    "IH": "CFFEX",
    "SR": "CZCE",
    "MA": "CZCE",
    "TA": "CZCE",
    "I": "DCE",
}
PRIORITY = ["CU", "SR", "I", "MA", "RB", "AU", "IF"]
SETTING_KEYS = (
    "fast_window",
    "atr_window",
    "low_pnl_atr",
    "mid_pnl_atr",
    "alignment_mode",
    "exit_mode",
    "price_offset",
    "allow_live_trading",
)


def _py_dt(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    tzinfo = getattr(value, "tzinfo", None)
    if tzinfo is not None:
        value = value.replace(tzinfo=None)
    return value


def default_setting(strategy_cls) -> dict:
    setting = {name: getattr(strategy_cls, name) for name in SETTING_KEYS}
    setting["allow_live_trading"] = False
    return setting


def search_grid(strategy_cls) -> list:
    base = default_setting(strategy_cls)
    grid = []
    seen = set()
    for alignment_mode in ("strict", "four_hour_lead"):
        for exit_mode in ("absolute", "signed"):
            for fast_window in (10, 20):
                for low_pnl_atr, mid_pnl_atr in ((1.5, 3.5), (1.0, 2.5)):
                    setting = dict(base)
                    setting.update(
                        {
                            "alignment_mode": alignment_mode,
                            "exit_mode": exit_mode,
                            "fast_window": fast_window,
                            "low_pnl_atr": low_pnl_atr,
                            "mid_pnl_atr": mid_pnl_atr,
                            "allow_live_trading": False,
                        }
                    )
                    key = tuple(sorted((name, repr(setting[name])) for name in SETTING_KEYS))
                    if key in seen:
                        continue
                    seen.add(key)
                    grid.append(setting)
    return grid


def audit_frame(df: pd.DataFrame, symbol: str) -> dict:
    idx = df.index
    span_days = 0.0
    if len(df):
        span_days = (_py_dt(idx.max()) - _py_dt(idx.min())).total_seconds() / 86400.0
    deltas = idx.to_series().diff().dt.total_seconds()
    prices = df[["open", "high", "low", "close"]]
    prev = df["close"].shift(1)
    jump = (prev > 0) & ((df["close"] - prev).abs() / prev > 0.05)
    window_ok = bool(len(df) >= 8000 and span_days >= MIN_OBSERVATION_DAYS)
    report = {
        "symbol": symbol,
        "rows": int(len(df)),
        "start": _py_dt(idx.min()).isoformat() if len(df) else None,
        "end": _py_dt(idx.max()).isoformat() if len(df) else None,
        "span_days": round(span_days, 3),
        "duplicate_timestamps": int(idx.duplicated().sum()),
        "bad_high_low_rows": int((df["high"] < df["low"]).sum()) if len(df) else 0,
        "nonpositive_price_rows": int((prices <= 0).any(axis=1).sum()) if len(df) else 0,
        "median_step_seconds": None if deltas.dropna().empty else float(deltas.median()),
        "gaps_over_30m": int((deltas > 1800).sum()) if len(deltas) else 0,
        "close_jumps_over_5pct": int(jump.fillna(False).sum()) if len(df) else 0,
        "observation_window_ok": window_ok,
        "window_rule": f"at least {MIN_OBSERVATION_DAYS} calendar days and 8000 one-minute rows",
    }
    if not window_ok:
        report["skip_reason"] = "observation window shorter than the 4-hour warmup can support"
    return report


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    bad = (df["high"] < df["low"]) | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    kept = df.loc[~bad]
    return kept[~kept.index.duplicated(keep="first")]


def summarize_closed(closed: list) -> dict:
    if not closed:
        return {
            "closed_trades": 0,
            "realized_points": None,
            "gross_win_points": None,
            "gross_loss_points": None,
            "profit_factor": None,
            "win_rate": None,
            "max_drawdown_points": None,
            "pnl_source": None,
        }
    points = [float(trade["points"]) for trade in closed]
    wins = [value for value in points if value > 0]
    losses = [value for value in points if value < 0]
    gross_win = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "closed_trades": len(closed),
        "realized_points": float(sum(points)),
        "gross_win_points": gross_win,
        "gross_loss_points": gross_loss,
        "profit_factor": None if gross_loss == 0 else gross_win / gross_loss,
        "win_rate": len(wins) / len(points),
        "max_drawdown_points": drawdown,
        "pnl_source": "paper_limit_fills",
    }


def quality_pass(summary: dict) -> bool:
    if summary["closed_trades"] < MIN_CLOSED_TRADES:
        return False
    realized = summary["realized_points"]
    if realized is None or realized <= 0:
        return False
    if summary["profit_factor"] is None:
        return summary["gross_loss_points"] == 0
    return summary["profit_factor"] > 1.0


def select_by_train(rows: list) -> dict | None:
    eligible = [
        row
        for row in rows
        if row["train"]["closed_trades"] >= MIN_CLOSED_TRADES and row["train"]["realized_points"] is not None
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: float(row["train"]["realized_points"]))


def decide_ship(chosen: dict | None, defaults: dict) -> dict | None:
    if chosen is None:
        return None
    if not quality_pass(chosen["holdout"]):
        return None
    if _same_setting(chosen["setting"], defaults):
        return None
    return dict(chosen["setting"])


def _same_setting(left: dict, right: dict) -> bool:
    for name in SETTING_KEYS:
        if left.get(name) != right.get(name):
            return False
    return True


def _public_cny(symbol: str, points):
    if points is None or symbol not in CONTRACT_MULTIPLIER:
        return None
    return float(points) * CONTRACT_MULTIPLIER[symbol]


def replay_frame(strategy_cls, df: pd.DataFrame, symbol: str, setting: dict) -> dict:
    setting = dict(setting)
    setting["allow_live_trading"] = False
    exchange = EXCHANGE.get(symbol, "LOCAL")
    engine = PaperCtaEngine()
    strategy = strategy_cls(engine, f"obs_{symbol}", f"{symbol}.{exchange}", setting)
    engine.strategy = strategy
    strategy.on_init()
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy() if "volume" in df.columns else None
    interest = df["open_interest"].to_numpy() if "open_interest" in df.columns else None
    index = df.index
    total = len(df)
    for i in range(total):
        volume = 0.0 if volumes is None else float(volumes[i])
        oi = 0.0 if interest is None else float(interest[i])
        bar = BarData(
            symbol=symbol,
            exchange=exchange,
            datetime=_py_dt(index[i]),
            open_price=float(opens[i]),
            high_price=float(highs[i]),
            low_price=float(lows[i]),
            close_price=float(closes[i]),
            volume=volume,
            open_interest=oi,
        )
        engine.new_bar(bar)
        if i and i % 100000 == 0:
            print(f"  {symbol} {i}/{total} ready={strategy.stats['bars_ready']} fires={strategy.stats['fire_235'] + strategy.stats['fire_1235']}", flush=True)

    closed = []
    for trade in engine.ledger.closed:
        copied = dict(trade)
        copied["entry_time"] = _py_dt(trade["entry_time"])
        copied["exit_time"] = _py_dt(trade["exit_time"])
        closed.append(copied)
    summary = summarize_closed(closed)
    unrealized = None
    if engine.ledger.pos != 0 and len(df):
        unrealized = engine.ledger.unrealized(float(df["close"].iloc[-1]))
    summary["unrealized_points_mark"] = unrealized
    summary["open_pos"] = engine.ledger.pos
    summary["cny_using_public_multiplier"] = _public_cny(symbol, summary["realized_points"])
    summary["multiplier_note"] = (
        None
        if symbol not in CONTRACT_MULTIPLIER
        else f"{symbol} x{CONTRACT_MULTIPLIER[symbol]} public contract size; not broker cash"
    )
    if not strategy.am_4h.inited:
        summary["realized_points"] = None
        summary["pnl_source"] = None
        summary["cny_using_public_multiplier"] = None
        summary["block_reason"] = "4h_array_not_inited"
    return {
        "symbol": symbol,
        "execution_mode": engine.execution_mode,
        "allow_live_trading": strategy.allow_live_trading,
        "live_deny_count": strategy.live_deny_count,
        "bars": total,
        "initialized_4h": bool(strategy.am_4h.inited),
        "initialized_1m": bool(strategy.am_1m.inited),
        "stats": dict(strategy.stats),
        "orders": len(engine.orders),
        "fills": len(engine.trades),
        "summary": summary,
        "closed_trades": [
            {
                **trade,
                "entry_time": trade["entry_time"].isoformat(),
                "exit_time": trade["exit_time"].isoformat(),
            }
            for trade in closed
        ],
        "_closed_for_split": closed,
    }


def split_closed(closed: list, split_at) -> tuple:
    split_at = _py_dt(split_at)
    train, holdout = [], []
    for trade in closed:
        if _py_dt(trade["entry_time"]) < split_at:
            train.append(trade)
        else:
            holdout.append(trade)
    return train, holdout


def _iso_summary(summary: dict) -> dict:
    out = dict(summary)
    out["quality_pass"] = quality_pass(summary)
    return out


def evaluate_symbol(strategy_cls, df: pd.DataFrame, symbol: str, setting: dict) -> dict:
    result = replay_frame(strategy_cls, df, symbol, setting)
    closed = result.pop("_closed_for_split")
    split_at = df.index[int(len(df) * (1.0 - HOLDOUT_FRACTION))]
    train, holdout = split_closed(closed, split_at)
    result["split_at"] = _py_dt(split_at).isoformat()
    result["train"] = _iso_summary(summarize_closed(train))
    result["holdout"] = _iso_summary(summarize_closed(holdout))
    result["full"] = _iso_summary(result["summary"])
    return result


def run_search(strategy_cls, df: pd.DataFrame, symbol: str) -> dict:
    defaults = default_setting(strategy_cls)
    rows = []
    for index, setting in enumerate(search_grid(strategy_cls), start=1):
        print(f"search {index} {symbol} {setting['alignment_mode']} {setting['exit_mode']} fast={setting['fast_window']} atr={setting['low_pnl_atr']}/{setting['mid_pnl_atr']}", flush=True)
        result = evaluate_symbol(strategy_cls, df, symbol, setting)
        rows.append(
            {
                "setting": setting,
                "train": result["train"],
                "holdout": result["holdout"],
                "full_closed_trades": result["full"]["closed_trades"],
                "full_realized_points": result["full"]["realized_points"],
                "initialized_4h": result["initialized_4h"],
                "stats": result["stats"],
            }
        )
    chosen = select_by_train(rows)
    shipped = decide_ship(chosen, defaults)
    return {
        "searched": True,
        "grid_size": len(rows),
        "selected_by": "max train realized points among rows with at least 8 closed train trades",
        "holdout_used_for_selection": False,
        "chosen": None
        if chosen is None
        else {
            "setting": chosen["setting"],
            "train": chosen["train"],
            "holdout": chosen["holdout"],
        },
        "ship_setting": shipped,
        "rows": [
            {
                "setting": row["setting"],
                "train_closed": row["train"]["closed_trades"],
                "train_realized_points": row["train"]["realized_points"],
                "holdout_closed": row["holdout"]["closed_trades"],
                "holdout_realized_points": row["holdout"]["realized_points"],
                "holdout_quality_pass": row["holdout"]["quality_pass"],
            }
            for row in rows
        ],
    }


def load_observation_frame(path: Path, start: str) -> tuple:
    df = pd.read_parquet(path)
    df = df.sort_index()
    full_start = _py_dt(df.index.min()) if len(df) else None
    full_end = _py_dt(df.index.max()) if len(df) else None
    sliced = df.loc[pd.Timestamp(start):] if start else df
    return df, sliced, full_start, full_end


def build_report(data_dir: Path, start: str, extend_start: str, do_optimize: bool, strategy_cls) -> dict:
    files = {path.name.split("_")[0].upper(): path for path in sorted(data_dir.glob("*_1m.parquet"))}
    ordered = [name for name in PRIORITY if name in files] + [name for name in files if name not in PRIORITY]
    audits = []
    playable = []
    for symbol in ordered:
        full, sliced, full_start, full_end = load_observation_frame(files[symbol], start)
        audit = audit_frame(sliced, symbol)
        audit["file"] = str(files[symbol])
        audit["full_rows"] = int(len(full))
        audit["full_start"] = full_start.isoformat() if full_start else None
        audit["full_end"] = full_end.isoformat() if full_end else None
        audit["observation_start_requested"] = start
        audits.append(audit)
        if audit["observation_window_ok"]:
            playable.append((symbol, clean_frame(sliced), files[symbol]))

    defaults = default_setting(strategy_cls)
    played = []
    primary = None
    for symbol, frame, _path in playable[:2]:
        print(f"observe {symbol} rows={len(frame)} {frame.index.min()} -> {frame.index.max()}", flush=True)
        primary_result = evaluate_symbol(strategy_cls, frame, symbol, defaults)
        if (
            primary is None
            and primary_result["stats"]["fire_235"] + primary_result["stats"]["fire_1235"] == 0
            and extend_start
            and extend_start < start
        ):
            _full, extended, _a, _b = load_observation_frame(files[symbol], extend_start)
            extended_clean = clean_frame(extended)
            extended_audit = audit_frame(extended_clean, symbol)
            if extended_audit["observation_window_ok"] and len(extended_clean) > len(frame):
                print(f"extend {symbol} to {extend_start} rows={len(extended_clean)}", flush=True)
                primary_result = evaluate_symbol(strategy_cls, extended_clean, symbol, defaults)
                primary_result["window_extended_from"] = start
                primary_result["window_extended_to"] = extend_start
                frame = extended_clean
        primary_result.pop("_closed_for_split", None)
        if primary is None:
            primary = (symbol, frame, primary_result)
        played.append(primary_result)

    optimize = {"searched": False, "reason": "primary observation not run"}
    if primary is None:
        optimize = {"searched": False, "reason": "no symbol had a long enough 1-minute window"}
    else:
        symbol, frame, result = primary
        holdout_pass = result["holdout"]["quality_pass"]
        if holdout_pass:
            optimize = {
                "searched": False,
                "reason": "default setting already passed the holdout quality rule",
                "ship_setting": None,
            }
        elif not do_optimize:
            optimize = {"searched": False, "reason": "optimize disabled", "ship_setting": None}
        else:
            optimize = run_search(strategy_cls, frame, symbol)
            if optimize["ship_setting"] is None:
                optimize["reason"] = "no train-selected setting passed the untouched holdout"
            else:
                optimize["reason"] = "train-selected setting passed holdout; caller may update monitor defaults"

    return {
        "live_trading": "DENY",
        "allow_live_trading_default": False,
        "pnl_policy": "realized points from paper fills only; null when there is no closed round trip or the 4h window never initialized. Commission is not deducted and is not invented.",
        "quality_rule": {
            "min_closed_trades": MIN_CLOSED_TRADES,
            "min_observation_days": MIN_OBSERVATION_DAYS,
            "holdout_fraction": HOLDOUT_FRACTION,
            "requires_positive_realized_points": True,
            "requires_profit_factor_above_1_when_defined": True,
        },
        "bar_rules": {
            "source": "vnpy/trader/utility.py BarGenerator master checked 2026-11-06",
            "minute_finish": "(minute + 1) % window == 0",
            "hour_finish": "minute == 59, else clock-hour change; minute==59 is tested first",
            "four_hour": "Interval.HOUR window=4 counts finished hour bars from 1-minute input",
            "vnpy_installed": False,
        },
        "owner_gates": [
            "allow_live_trading stays false. A paper backtest is not permission to send real orders.",
            "QuantLab gate is PRODUCTION and production deploy stays human-gated. This run does not deploy QuantLab and does not start a gateway.",
            "QuantLab project agent execution is off. No order was sent to CTP, Binance, or any broker.",
            "Public contract multipliers are labels beside points. They are not broker cash PnL.",
        ],
        "defaults": defaults,
        "audits": audits,
        "observations": played,
        "optimize": optimize,
    }


def main() -> None:
    from Production_Hybrid_Monitor import Production_Hybrid_Monitor

    parser = argparse.ArgumentParser(description="Paper quality observation for the hybrid monitor")
    parser.add_argument("--data-dir", default=r"C:\Users\Administrator\quantlab\data\market_data")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--extend-start", default="2022-01-01")
    parser.add_argument("--no-optimize", action="store_true")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "output" / "quality_observation_report.json"))
    args = parser.parse_args()
    report = build_report(
        Path(args.data_dir),
        args.start,
        args.extend_start,
        do_optimize=not args.no_optimize,
        strategy_cls=Production_Hybrid_Monitor,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
