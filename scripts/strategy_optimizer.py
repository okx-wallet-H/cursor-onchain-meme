#!/usr/bin/env python3
"""Analyze paper-trade history and recommend strategy parameters."""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.json"
TRADE_LOG = ROOT / "data" / "trade_log.jsonl"
STATE_PATH = ROOT / "data" / "state.json"
OUT_PATH = ROOT / "config" / "strategy_recommendation.json"


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def trade_rows():
    rows = []
    for item in read_jsonl(TRADE_LOG):
        if item.get("type") != "SELL":
            continue
        pnl = item.get("realized_pnl_usd")
        if pnl is None:
            continue
        rows.append({
            "symbol": item.get("symbol"),
            "pnl_usd": float(pnl),
            "pnl_pct": float(item.get("realized_pnl_pct") or 0),
            "exit_reason": item.get("exit_reason"),
            "score": item.get("score"),
            "wallet_type_label": item.get("wallet_type_label"),
            "sold_ratio_pct": item.get("sold_ratio_pct"),
            "trigger_wallet_count": item.get("trigger_wallet_count"),
            "holders": item.get("holders"),
            "top10_holder_pct": item.get("top10_holder_pct"),
            "win": float(pnl) > 0,
        })
    state = load_json(STATE_PATH, {})
    for pos in state.get("closed_positions", []):
        pnl = pos.get("realized_pnl_usd")
        if pnl is None:
            continue
        snap = pos.get("signal_snapshot") or {}
        rows.append({
            "symbol": pos.get("symbol"),
            "pnl_usd": float(pnl),
            "pnl_pct": float(pos.get("realized_pnl_pct") or 0),
            "exit_reason": pos.get("exit_reason"),
            "score": pos.get("score") or snap.get("score"),
            "wallet_type_label": snap.get("wallet_type_label"),
            "sold_ratio_pct": snap.get("sold_ratio_pct"),
            "trigger_wallet_count": snap.get("trigger_wallet_count"),
            "holders": snap.get("holders"),
            "top10_holder_pct": snap.get("top10_holder_pct"),
            "win": float(pnl) > 0,
        })
    dedup = {}
    for r in rows:
        key = (r.get("symbol"), r.get("pnl_usd"), r.get("exit_reason"))
        dedup[key] = r
    return list(dedup.values())


def bucket_stats(rows, key, bins=None):
    groups = defaultdict(list)
    for r in rows:
        val = r.get(key)
        if val is None:
            continue
        if bins:
            label = None
            for name, lo, hi in bins:
                if lo <= float(val) < hi:
                    label = name
                    break
            if label is None:
                continue
            groups[label].append(r["pnl_usd"])
        else:
            groups[str(val)].append(r["pnl_usd"])
    out = []
    for label, pnls in sorted(groups.items(), key=lambda x: statistics.mean(x[1]) if x[1] else -999, reverse=True):
        out.append({
            "bucket": label,
            "trades": len(pnls),
            "avg_pnl_usd": round(statistics.mean(pnls), 2) if pnls else 0,
            "win_rate_pct": round(100 * sum(1 for p in pnls if p > 0) / len(pnls), 1) if pnls else 0,
        })
    return out


def analyze():
    rows = trade_rows()
    wins = [r for r in rows if r["win"]]
    losses = [r for r in rows if not r["win"]]
    total_pnl = sum(r["pnl_usd"] for r in rows)

    insights = []
    if wins:
        avg_win_score = statistics.mean([r["score"] for r in wins if r.get("score")])
        avg_loss_score = statistics.mean([r["score"] for r in losses if r.get("score")]) if losses else 0
        insights.append(f"Winners avg score {avg_win_score:.1f} vs losers {avg_loss_score:.1f}")

    whale_wins = sum(1 for r in wins if r.get("wallet_type_label") == "Whale")
    sm_losses = sum(1 for r in losses if r.get("wallet_type_label") == "SmartMoney")
    if whale_wins or sm_losses:
        insights.append(f"Whale wins {whale_wins}/{len(wins)}; SmartMoney losses {sm_losses}/{len(losses)}")

    sold_win = statistics.mean([r["sold_ratio_pct"] for r in wins if r.get("sold_ratio_pct") is not None]) if wins else None
    sold_loss = statistics.mean([r["sold_ratio_pct"] for r in losses if r.get("sold_ratio_pct") is not None]) if losses else None
    if sold_win is not None and sold_loss is not None:
        insights.append(f"Winners sold_ratio ~{sold_win:.0f}% vs losers ~{sold_loss:.0f}%")

    recommended = {
        "strategy_version": "v4-whale-low-sold",
        "sim_enabled": False,
        "chain": "solana",
        "initial_cash_usd": 1000.0,
        "scan_interval_seconds": 1800,
        "max_positions": 3,
        "position_cash_pct": 0.08,
        "max_position_cash_pct": 0.12,
        "min_cash_reserve_pct": 0.2,
        "take_profit_pct": 35.0,
        "stop_loss_pct": -12.0,
        "cooldown_rounds": 4,
        "max_stop_losses_before_ban": 2,
        "min_trigger_wallet_count": 4,
        "min_signal_score": 80,
        "min_smart_money_score": 90,
        "signal_limit": 50,
        "wallet_types": "3",
        "min_holders": 250,
        "max_top10_holder_pct": 22.0,
        "max_sold_ratio_pct": 50.0,
        "min_market_cap_usd": 30000.0,
        "max_market_cap_usd": 500000.0,
        "price_poll_sleep_seconds": 0.2,
        "notes": [
            "Paused by default after review; resume with ./scripts/resume_sim.sh",
            "Whale-only; max_sold_ratio 50% (51-75% bucket was 0% win rate)",
            "min_score 80; smaller size (8%) and max 3 positions",
            "TP 35% / SL -12% from winner/loser sold_ratio spread",
        ],
    }

    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "sample_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(rows), 1) if rows else 0,
        "total_realized_pnl_usd": round(total_pnl, 2),
        "insights": insights,
        "by_wallet_type": bucket_stats(rows, "wallet_type_label"),
        "by_score": bucket_stats(rows, "score", [
            ("80+", 80, 999),
            ("72-80", 72, 80),
            ("60-72", 60, 72),
            ("<60", 0, 60),
        ]),
        "by_sold_ratio": bucket_stats(rows, "sold_ratio_pct", [
            ("<50", 0, 50),
            ("50-65", 50, 65),
            ("65-75", 65, 75),
            (">75", 75, 999),
        ]),
        "recommended_config": recommended,
    }


def apply_recommendation():
    report = analyze()
    rec = report["recommended_config"]
    current = load_json(CONFIG_PATH, {})
    rec["initial_cash_usd"] = current.get("initial_cash_usd", 1000.0)
    rec["scan_interval_seconds"] = current.get("scan_interval_seconds", 3600)
    CONFIG_PATH.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    OUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Write recommended config to config.json")
    args = p.parse_args()
    if args.apply:
        report = apply_recommendation()
    else:
        report = analyze()
        OUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "sample_trades": report["sample_trades"],
        "win_rate_pct": report["win_rate_pct"],
        "total_realized_pnl_usd": report["total_realized_pnl_usd"],
        "insights": report["insights"],
        "recommended": report["recommended_config"]["strategy_version"],
    }, indent=2, ensure_ascii=False))
