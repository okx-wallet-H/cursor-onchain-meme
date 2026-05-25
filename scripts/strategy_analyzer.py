"""Analyze paper-trading history and suggest strategy tweaks."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "strategy_analysis.json"


def _bucket_score(score):
    if score is None:
        return "unknown"
    score = float(score)
    if score >= 80:
        return "80+"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "<60"


def _trade_row(pos, status):
    snap = pos.get("signal_snapshot") or {}
    pnl = pos.get("realized_pnl_usd") if status == "closed" else pos.get("unrealized_pnl_usd")
    pnl_pct = pos.get("realized_pnl_pct") if status == "closed" else pos.get("unrealized_pnl_pct")
    return {
        "symbol": pos.get("symbol"),
        "status": status,
        "exit_reason": pos.get("exit_reason"),
        "score": pos.get("score"),
        "wallet_type": snap.get("wallet_type_label") or snap.get("wallet_type"),
        "sold_ratio_pct": snap.get("sold_ratio_pct"),
        "trigger_wallet_count": snap.get("trigger_wallet_count"),
        "pnl_usd": pnl,
        "pnl_pct": pnl_pct,
    }


def analyze_state(state, config):
    closed = state.get("closed_positions", [])
    open_pos = list(state.get("positions", {}).values())
    rows = [_trade_row(p, "closed") for p in closed] + [_trade_row(p, "open") for p in open_pos]

    def stats(items):
        if not items:
            return {"count": 0, "win_rate": None, "avg_pnl_pct": None, "total_pnl_usd": 0.0}
        wins = [x for x in items if (x.get("pnl_usd") or 0) > 0]
        return {
            "count": len(items),
            "win_rate": round(len(wins) / len(items), 4),
            "avg_pnl_pct": round(sum(float(x.get("pnl_pct") or 0) for x in items) / len(items), 4),
            "total_pnl_usd": round(sum(float(x.get("pnl_usd") or 0) for x in items), 4),
        }

    by_wallet = defaultdict(list)
    by_sold = {"low_sold<=50": [], "mid_sold_51_75": [], "high_sold>75": []}
    by_score = defaultdict(list)

    for row in rows:
        by_wallet[row.get("wallet_type") or "unknown"].append(row)
        by_score[_bucket_score(row.get("score"))].append(row)
        sold = float(row.get("sold_ratio_pct") or 0)
        if sold <= 50:
            by_sold["low_sold<=50"].append(row)
        elif sold <= 75:
            by_sold["mid_sold_51_75"].append(row)
        else:
            by_sold["high_sold>75"].append(row)

    initial = float(config.get("initial_cash_usd", 1000))
    equity = float(state.get("last_equity_usd", initial))
    closed_only = [r for r in rows if r["status"] == "closed"]

    recommendations = []
    whale = stats(by_wallet.get("Whale", []))
    sm = stats(by_wallet.get("SmartMoney", []))
    if whale.get("count") and sm.get("count"):
        if (whale.get("avg_pnl_pct") or 0) > (sm.get("avg_pnl_pct") or 0) + 10:
            recommendations.append("prefer_whale_signals: SmartMoney underperforms Whale in sample")
    high_sold = stats(by_sold["high_sold>75"])
    low_sold = stats(by_sold["low_sold<=50"])
    if high_sold.get("count") and (high_sold.get("avg_pnl_pct") or 0) < -5:
        recommendations.append("tighten_max_sold_ratio_pct: sold_ratio>75 correlates with losses")
    low_score = stats(by_score["<60"] + by_score["60-69"])
    if low_score.get("count") and (low_score.get("avg_pnl_pct") or 0) < 0:
        recommendations.append("raise_min_signal_score: scores below 70 show negative expectancy")

    return {
        "strategy_version": config.get("strategy_version"),
        "round": state.get("round"),
        "equity_usd": round(equity, 4),
        "total_return_pct": round((equity / initial - 1) * 100, 4),
        "realized_pnl_usd": float(state.get("realized_pnl_usd", 0)),
        "closed_trades": len(closed),
        "open_trades": len(open_pos),
        "overall_closed": stats(closed_only),
        "by_wallet_type": {k: stats(v) for k, v in by_wallet.items()},
        "by_sold_ratio": {k: stats(v) for k, v in by_sold.items()},
        "by_score_bucket": {k: stats(v) for k, v in by_score.items()},
        "recommendations": recommendations,
        "recent_trades": rows[-10:],
    }


def save_analysis(state, config):
    payload = analyze_state(state, config)
    ANALYSIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload
