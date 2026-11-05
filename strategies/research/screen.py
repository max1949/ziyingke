"""One-shot paper screen. Parameters are chosen on copper and sugar train only."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.backtest import score_frame
from research.gate import OBSERVATION_STOP_UTC, SOAK_END_SEARCH, keeper_decision
from research.resample import resample_four_hours, resample_hours
from research.signals import FAMILY_BUILDERS
from quality_observation import quality_pass

DATA = Path(r"C:\Users\Administrator\quantlab\data\market_data")
OUT = Path(__file__).resolve().parents[1] / "output" / "qualified_strategies_report.json"
SELECT = ("CU", "SR")
EVAL_ORDER = ("CU", "SR", "I", "MA", "RB", "AU", "IF")

GRIDS = {
    "ema_cross": [{"fast": fast, "slow": slow} for fast in (8, 20) for slow in (40, 80, 120) if slow >= fast * 2],
    "sma_cross": [{"fast": fast, "slow": slow} for fast in (10, 20) for slow in (40, 80) if slow >= fast * 2],
    "ema_cross_long": [{"fast": 10, "slow": 40}, {"fast": 20, "slow": 80}],
    "donchian": [{"length": length} for length in (20, 40, 55, 89, 120)],
    "keltner": [{"length": length, "width": width} for length in (20, 40) for width in (1.5, 2.5)],
    "bb_break": [{"length": length, "width": width} for length in (20, 40) for width in (2.0, 2.5)],
    "bb_fade": [{"length": length, "width": width} for length in (20, 40) for width in (2.0, 2.5)],
    "rsi_fade": [{"length": length, "low": low, "high": high} for length in (7, 14) for low, high in ((30, 70), (20, 80))],
    "zscore": [{"length": length, "level": level} for length in (20, 40) for level in (1.5, 2.0, 2.5)],
    "consec": [{"length": length} for length in (3, 4, 5)],
    "ts_momentum": [{"length": length} for length in (10, 20, 40, 60)],
    "macd": [{"fast": 12, "slow": 26, "signal": 9}, {"fast": 8, "slow": 21, "signal": 5}],
    "triple_ema": [{"fast": 5, "mid": 20, "slow": 60}, {"fast": 10, "mid": 30, "slow": 90}],
    "pullback": [{"fast": fast, "slow": slow} for fast in (10, 20) for slow in (40, 80) if slow > fast],
    "rsi_dip": [{"trend": trend, "rsi": 14, "dip": dip} for trend in (40, 80) for dip in (30, 40)],
    "gap_follow": [{"threshold": threshold} for threshold in (0.0, 0.003, 0.008)],
    "gap_fade": [{"threshold": threshold} for threshold in (0.0, 0.003, 0.008)],
    "nr_break": [{"length": length, "ratio": ratio} for length in (10, 20) for ratio in (0.6, 0.8)],
    "squeeze": [{"length": 20, "width": 2.0, "quantile": quantile} for quantile in (0.2, 0.35)],
    "chandelier": [{"trend": trend, "atr": 14, "mult": mult} for trend in (20, 40) for mult in (2.0, 3.0)],
    "prior_day": [{}],
    "orb": [{}],
}

TIMEFRAMES = {
    "prior_day": {"1h", "4h"},
    "orb": {"1h", "4h"},
}

FILL = {"gap_follow": "same_open", "gap_fade": "same_open"}


def load_daily(symbol: str) -> pd.DataFrame | None:
    path = DATA / f"{symbol}_1d.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path).sort_index()
    frame = frame[~frame.index.duplicated(keep="first")]
    bad = (frame["high"] < frame["low"]) | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    frame = frame.loc[~bad]
    if len(frame) < 200:
        return None
    span_days = (frame.index.max() - frame.index.min()).total_seconds() / 86400.0
    if span_days < 200:
        return None
    return frame


def _public(summary: dict) -> dict:
    return {
        "closed_trades": summary["closed_trades"],
        "realized_points": summary["realized_points"],
        "profit_factor": summary["profit_factor"],
        "max_drawdown_points": summary["max_drawdown_points"],
        "win_rate": summary["win_rate"],
        "quality_pass": quality_pass(summary),
        "pnl_source": summary["pnl_source"],
    }


def evaluate(family: str, params: dict, frames: dict) -> dict:
    builder = FAMILY_BUILDERS[family]
    fill = FILL.get(family, "next_open")
    out = {}
    for symbol, frame in frames.items():
        signal = builder(frame, params)
        scored = score_frame(frame["open"].to_numpy(), signal, fill=fill)
        out[symbol] = {"train": _public(scored["train"]), "holdout": _public(scored["holdout"])}
    return out


def screen(frames: dict, timeframe: str) -> dict:
    rejected = []
    keepers = []
    for family, grid in GRIDS.items():
        allowed = TIMEFRAMES.get(family)
        if allowed is not None and timeframe not in allowed:
            continue
        print(f"{timeframe} family {family} grid {len(grid)}", flush=True)
        best = None
        best_key = None
        for params in grid:
            try:
                scored = {
                    symbol: score_frame(
                        frames[symbol]["open"].to_numpy(),
                        FAMILY_BUILDERS[family](frames[symbol], params),
                        fill=FILL.get(family, "next_open"),
                    )
                    for symbol in SELECT
                }
            except Exception as exc:
                rejected.append({"family": family, "params": params, "reason": f"error:{type(exc).__name__}:{exc}"})
                continue
            if not (quality_pass(scored["CU"]["train"]) and quality_pass(scored["SR"]["train"])):
                continue
            key = min(scored["CU"]["train"]["realized_points"], scored["SR"]["train"]["realized_points"])
            if best is None or key > best_key:
                best = params
                best_key = key
        if best is None:
            rejected.append({"family": family, "reason": "no copper-and-sugar train pass"})
            continue
        full = evaluate(family, best, frames)
        decision = keeper_decision({symbol: row["holdout"] for symbol, row in full.items()})
        row = {
            "family": family,
            "timeframe": timeframe,
            "params": best,
            "train_min_points": best_key,
            "symbols": full,
            **decision,
            "allow_live_trading": False,
            "class_name": "Keeper_" + "".join(part.capitalize() for part in family.split("_")) + "_" + timeframe,
        }
        if decision["keeper"]:
            keepers.append(row)
            print(f"  KEEP {family} {decision['passing_symbols']}", flush=True)
        else:
            rejected.append({**row, "reason": "holdout gate"})
            print(f"  reject {family} pass={decision['passing_symbols']} awful={decision['awful_symbols']}", flush=True)
    return {"keepers": keepers, "rejected": rejected}


def main() -> None:
    frames = {}
    audits = []
    for symbol in EVAL_ORDER:
        frame = load_daily(symbol)
        if frame is None:
            audits.append({"symbol": symbol, "usable_daily": False})
            continue
        frames[symbol] = frame
        audits.append(
            {
                "symbol": symbol,
                "usable_daily": True,
                "rows": int(len(frame)),
                "start": str(frame.index.min()),
                "end": str(frame.index.max()),
            }
        )
    if "CU" not in frames or "SR" not in frames:
        raise SystemExit("copper and sugar daily bars are required")
    intraday = {}
    for symbol in ("CU", "SR", "I", "MA"):
        path = DATA / f"{symbol}_1m.parquet"
        if not path.exists():
            continue
        print(f"resample {symbol}", flush=True)
        hours = resample_hours(pd.read_parquet(path).sort_index())
        intraday[symbol] = {"1h": hours, "4h": resample_four_hours(hours)}
    packs = {"1d": frames}
    if len(intraday) == 4:
        packs["1h"] = {symbol: bundle["1h"] for symbol, bundle in intraday.items()}
        packs["4h"] = {symbol: bundle["4h"] for symbol, bundle in intraday.items()}
    keepers = []
    rejected = []
    for timeframe, pack in packs.items():
        part = screen(pack, timeframe)
        keepers.extend(part["keepers"])
        rejected.extend(part["rejected"])
    result = {"keepers": keepers, "rejected": rejected}
    report = {
        "line": "strategies_paper_evaluation",
        "observation_stop_utc": OBSERVATION_STOP_UTC,
        "soak_end_search": SOAK_END_SEARCH,
        "live_trading": "DENY",
        "banned_promotion": "copper-only ATR 1.0/2.5 signed hybrid exit",
        "gate": {
            "train_symbols": list(SELECT),
            "holdout_fraction": 0.30,
            "quality_pass": "closed_trades>=8, realized_points>0, profit_factor>1 when defined",
            "keeper": "at least two symbols quality_pass on holdout, and no symbol with >=8 trades and profit factor < 0.90",
            "pnl": "gross price points from paper fills; null when there is no closed trade; commission not invented",
        },
        "audits": audits,
        "keeper_count": len(result["keepers"]),
        "keepers": result["keepers"],
        "rejected_count": len(result["rejected"]),
        "rejected": [{k: v for k, v in row.items() if k != "symbols"} | {"holdout_pass": row.get("passing_symbols"), "awful": row.get("awful_symbols")} for row in result["rejected"]],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"keepers {report['keeper_count']} wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
