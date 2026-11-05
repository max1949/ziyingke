"""Keeper rule for the strategies paper line.

Observation stops at 2026-11-15T16:00:00Z. Local journals do not define a
strategies SOAK_END. The dated stop that does exist is the JCD factory
PROJECT_END_EXCLUSIVE, and this line uses that same instant.

A keeper is one frozen parameter set. Train on copper and sugar only.
Holdout is the last 30 percent of each symbol and is not used to pick
parameters. At least two symbols must clear the existing quality_pass
rule. A symbol with eight or more holdout trades and profit factor below
0.90 rejects the candidate. Live trading stays off.
"""

from __future__ import annotations

OBSERVATION_STOP_UTC = "2026-11-15T16:00:00+00:00"
SOAK_END_SEARCH = {
    "strategies_tree": "no SOAK_END and no 截止到11月15 marker",
    "journals": "SOAK_END mostly N/A; no strategies soak end on 2026-11-15",
    "aligned_to": "JCD PROJECT_END_EXCLUSIVE 2026-11-15T16:00:00+00:00",
}

from quality_observation import quality_pass


def not_awful(summary: dict) -> bool:
    if summary.get("closed_trades", 0) < 8:
        return True
    profit_factor = summary.get("profit_factor")
    if profit_factor is None:
        points = summary.get("realized_points")
        return points is not None and points > 0
    return float(profit_factor) >= 0.90


def keeper_decision(holdouts: dict) -> dict:
    passing = [symbol for symbol, summary in holdouts.items() if quality_pass(summary)]
    awful = [
        symbol
        for symbol, summary in holdouts.items()
        if summary.get("closed_trades", 0) >= 8 and not not_awful(summary)
    ]
    return {
        "passing_symbols": passing,
        "awful_symbols": awful,
        "keeper": len(passing) >= 2 and not awful,
    }
