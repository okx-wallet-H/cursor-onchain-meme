#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_analyzer import save_analysis

try:
    from strategy_optimizer import analyze as optimize_analyze, apply_recommendation
except ImportError:
    optimize_analyze = apply_recommendation = None


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.json"
STATE_PATH = ROOT / "data" / "state.json"
TRADE_LOG_PATH = ROOT / "data" / "trade_log.jsonl"
OBS_LOG_PATH = ROOT / "data" / "observations.jsonl"
POSITIONS_CSV_PATH = ROOT / "data" / "positions.csv"
POSITION_SNAPSHOTS_PATH = ROOT / "data" / "position_snapshots.jsonl"
LESSONS_PATH = ROOT / "memory" / "lessons.md"
DASHBOARD_SNAPSHOT_PATH = ROOT / "dashboard" / "snapshot.json"
DASHBOARD_DATA_JS_PATH = ROOT / "dashboard" / "data.js"

WALLET_TYPE_LABEL = {"1": "SmartMoney", "2": "KOL", "3": "Whale"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts):
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def scan_interval_seconds(config):
    return float(config.get("scan_interval_seconds", 3600))


def seconds_until_next_round(state, config):
    last = parse_iso(state.get("last_round_at"))
    if last is None:
        return 0.0
    remaining = scan_interval_seconds(config) - (datetime.now(timezone.utc) - last).total_seconds()
    return max(0.0, remaining)


def record_tick(state, config):
    """Track scheduler heartbeats for dashboard online / continuous-mode display."""
    now = datetime.now(timezone.utc)
    interval = scan_interval_seconds(config)
    prev_at = parse_iso(state.get("last_tick_at"))
    if prev_at is not None:
        gap = (now - prev_at).total_seconds()
        if gap <= interval * 2.5:
            state["cumulative_online_seconds"] = round(
                float(state.get("cumulative_online_seconds", 0)) + gap, 1
            )
    state["last_tick_at"] = now.isoformat()
    state["tick_count"] = int(state.get("tick_count", 0)) + 1


def build_runtime_status(state, config):
    now = datetime.now(timezone.utc)
    interval = scan_interval_seconds(config)
    sim_enabled = config.get("sim_enabled") is not False
    last = parse_iso(state.get("last_tick_at"))
    started = parse_iso(state.get("sim_session_started_at"))
    since_tick = (now - last).total_seconds() if last else None
    mins = max(1, int(interval / 60))

    if not sim_enabled:
        status, label, continuous = "paused", "已暂停（非持续）", False
    elif since_tick is None:
        status, label, continuous = "starting", "启动中", True
    elif since_tick > interval * 2:
        status, label, continuous = "offline", "断线 · 未持续运行", False
    elif since_tick > interval * 1.5:
        status, label, continuous = "degraded", "可能断线", False
    else:
        status, label, continuous = "online", "持续运行中", True

    return {
        "sim_enabled": sim_enabled,
        "continuous_mode": continuous,
        "status": status,
        "status_label": label,
        "scan_interval_seconds": int(interval),
        "scan_interval_label": f"{mins} 分钟",
        "session_started_at": state.get("sim_session_started_at"),
        "last_tick_at": state.get("last_tick_at"),
        "seconds_since_last_tick": round(since_tick) if since_tick is not None else None,
        "session_uptime_seconds": round((now - started).total_seconds()) if started else 0,
        "cumulative_online_seconds": round(float(state.get("cumulative_online_seconds", 0))),
        "tick_count": int(state.get("tick_count", 0)),
    }


def advance_round_if_due(state, config, force=False):
    """Round = one signal-scan cycle per scan_interval (default 1h). Manual ticks within the window do not bump round."""
    if force:
        state["round"] = int(state.get("round", 0)) + 1
        state["last_round_at"] = now_iso()
        return True
    last = parse_iso(state.get("last_round_at"))
    if last is None:
        state["round"] = int(state.get("round", 0)) + 1
        state["last_round_at"] = now_iso()
        return True
    if (datetime.now(timezone.utc) - last).total_seconds() >= scan_interval_seconds(config):
        state["round"] = int(state.get("round", 0)) + 1
        state["last_round_at"] = now_iso()
        return True
    return False


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl_tail(path, limit=80):
    if not path.exists():
        return []
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines[-limit:]]


def normalize_trade_event(row):
    if row.get("type") not in ("BUY", "SELL"):
        return None
    if "symbol" in row:
        base = row
    else:
        pos = row.get("position") or {}
        base = {
            "ts": row.get("ts"),
            "type": row.get("type"),
            "round": row.get("round"),
            "trade_id": pos.get("trade_id"),
            "symbol": pos.get("symbol"),
            "name": pos.get("name"),
            "address": pos.get("address"),
            "entry_price": pos.get("entry_price"),
            "last_price": pos.get("last_price"),
            "cost_usd": pos.get("cost_usd"),
            "realized_pnl_usd": row.get("realized_pnl_usd"),
            "realized_pnl_pct": row.get("realized_pnl_pct"),
            "unrealized_pnl_pct": None,
            "exit_reason": row.get("exit_reason"),
        }
    is_sell = base.get("type") == "SELL"
    buy_price = base.get("entry_price")
    sell_price = base.get("last_price") if is_sell else None
    if is_sell:
        pnl_usd = base.get("realized_pnl_usd")
        pnl_pct = base.get("realized_pnl_pct")
    else:
        pnl_usd = None
        pnl_pct = base.get("unrealized_pnl_pct")
    return {
        "ts": base.get("ts"),
        "type": base.get("type"),
        "round": base.get("round"),
        "trade_id": base.get("trade_id"),
        "symbol": base.get("symbol"),
        "name": base.get("name"),
        "address": base.get("address"),
        "buy_price": buy_price,
        "sell_price": sell_price,
        "entry_price": buy_price,
        "last_price": base.get("last_price"),
        "cost_usd": base.get("cost_usd"),
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "realized_pnl_usd": base.get("realized_pnl_usd"),
        "realized_pnl_pct": base.get("realized_pnl_pct"),
        "unrealized_pnl_pct": base.get("unrealized_pnl_pct"),
        "exit_reason": base.get("exit_reason"),
    }


def build_position_ledger(report):
    rows = []
    for p in report.get("open_positions", []):
        rows.append({
            "trade_id": p.get("trade_id"),
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "status": "持仓中",
            "buy_price": p.get("entry_price"),
            "sell_price": None,
            "current_price": p.get("last_price"),
            "cost_usd": p.get("cost_usd"),
            "pnl_usd": p.get("unrealized_pnl_usd"),
            "pnl_pct": p.get("unrealized_pnl_pct"),
            "opened_at": p.get("opened_at"),
            "closed_at": None,
            "exit_reason": None,
        })
    for p in report.get("closed_positions", []):
        rows.append({
            "trade_id": p.get("trade_id"),
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "status": "已平仓",
            "buy_price": p.get("entry_price"),
            "sell_price": p.get("last_price"),
            "current_price": None,
            "cost_usd": p.get("cost_usd"),
            "pnl_usd": p.get("realized_pnl_usd"),
            "pnl_pct": p.get("realized_pnl_pct"),
            "opened_at": p.get("opened_at"),
            "closed_at": p.get("closed_at"),
            "exit_reason": p.get("exit_reason"),
        })
    rows.sort(key=lambda r: (r.get("status") != "持仓中", r.get("opened_at") or ""))
    return rows


def load_equity_curve():
    curve = []
    for path in sorted((ROOT / "reports").glob("report_round_*.json")):
        report = json.loads(path.read_text())
        summary = report.get("summary") or {}
        curve.append({
            "round": report.get("round"),
            "ts": report.get("ts"),
            "equity_usd": round(float(summary.get("equity_usd", 0)), 4),
            "cash_usd": round(float(summary.get("cash_usd", 0)), 4),
            "positions_value_usd": round(float(summary.get("positions_value_usd", 0)), 4),
            "open_positions": int(summary.get("open_positions", 0)),
        })
    return curve


def load_round_activity():
    activity = []
    for row in read_jsonl_tail(OBS_LOG_PATH, limit=500):
        if row.get("type") != "round_summary":
            continue
        activity.append({
            "round": row.get("round"),
            "ts": row.get("ts"),
            "signals": row.get("signals"),
            "candidates": row.get("candidates"),
            "opened": row.get("opened"),
            "positions": row.get("positions"),
        })
    return activity[-30:]


def export_dashboard_snapshot(state, config, report=None):
    if report is None:
        report = {
            "ts": now_iso(),
            "round": state.get("round", 0),
            "summary": estimate_equity(state, config, price_refresh=False),
            "open_positions": [enrich_position(p, config) for p in state["positions"].values()],
            "closed_positions": state.get("closed_positions", []),
            "reconciliation": {
                "initial_cash_usd": float(config["initial_cash_usd"]),
            },
        }
    summary = report.get("summary") or {}
    initial = float(config["initial_cash_usd"])
    equity = float(summary.get("equity_usd", initial))
    unrealized = round(
        sum(float(p.get("unrealized_pnl_usd") or 0) for p in report.get("open_positions", [])),
        4,
    )
    trades = [
        event for event in (normalize_trade_event(row) for row in read_jsonl_tail(TRADE_LOG_PATH, 120))
        if event
    ]
    payload = {
        "generated_at": now_iso(),
        "project": "meme-onchain-explorer",
        "chain": config.get("chain", "solana"),
        "round": int(state.get("round", 0)),
        "scan_count": int(state.get("scan_count", 0)),
        "last_round_at": state.get("last_round_at"),
        "next_round_in_seconds": round(seconds_until_next_round(state, config)),
        "updated_at": state.get("updated_at"),
        "config": {
            "initial_cash_usd": initial,
            "max_positions": int(config["max_positions"]),
            "position_cash_pct": float(config["position_cash_pct"]),
            "take_profit_pct": float(config["take_profit_pct"]),
            "stop_loss_pct": float(config["stop_loss_pct"]),
            "scan_interval_seconds": int(config.get("scan_interval_seconds", 3600)),
            "wallet_types": config.get("wallet_types"),
            "strategy_version": config.get("strategy_version"),
        },
        "summary": {
            **summary,
            "initial_cash_usd": initial,
            "total_pnl_usd": round(equity - initial, 4),
            "total_pnl_pct": round((equity / initial - 1) * 100, 4) if initial else 0.0,
            "unrealized_pnl_usd": unrealized,
        },
        "reconciliation": report.get("reconciliation"),
        "open_positions": report.get("open_positions", []),
        "closed_positions": report.get("closed_positions", []),
        "position_ledger": build_position_ledger(report),
        "equity_curve": load_equity_curve(),
        "round_activity": load_round_activity(),
        "recent_trades": trades[-40:],
        "risk": {
            "cooldowns": len(state.get("cooldowns", {})),
            "blacklist": len(state.get("blacklist", {})),
            "stop_loss_counts": len(state.get("stop_loss_counts", {})),
        },
        "strategy_analysis": save_analysis(state, config),
        "runtime": build_runtime_status(state, config),
    }
    save_json(DASHBOARD_SNAPSHOT_PATH, payload)
    DASHBOARD_DATA_JS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DATA_JS_PATH.write_text(
        "window.__SNAPSHOT__ = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    return payload


def append_lesson(text):
    with LESSONS_PATH.open("a") as f:
        f.write(f"\n### {now_iso()}\n\n{text.strip()}\n")


def run_onchainos(args):
    cmd = ["onchainos", *args]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=45)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip())
    out = proc.stdout.strip()
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-json onchainos output: {out[:500]}") from exc
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        raise RuntimeError(json.dumps(parsed, ensure_ascii=False))
    return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed


def init_state(config):
    ts = now_iso()
    return {
        "created_at": ts,
        "updated_at": ts,
        "sim_session_started_at": ts,
        "last_tick_at": None,
        "tick_count": 0,
        "cumulative_online_seconds": 0.0,
        "round": 0,
        "scan_count": 0,
        "last_round_at": None,
        "trade_seq": 0,
        "cash_usd": float(config["initial_cash_usd"]),
        "realized_pnl_usd": 0.0,
        "positions": {},
        "closed_positions": [],
        "cooldowns": {},
        "stop_loss_counts": {},
        "blacklist": {},
        "last_equity_usd": float(config["initial_cash_usd"]),
        "notes": [],
    }


def reset_sim_data(config):
    """Clear positions, logs, and restore initial cash for a fresh session."""
    state = init_state(config)
    for path in (TRADE_LOG_PATH, OBS_LOG_PATH, POSITION_SNAPSHOTS_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    save_json(STATE_PATH, state)
    export_positions_csv(state, config)
    return state


def next_trade_id(state):
    state["trade_seq"] = int(state.get("trade_seq", 0)) + 1
    return f"T{state['trade_seq']:06d}"


def wallet_type_label(wallet_type):
    return WALLET_TYPE_LABEL.get(str(wallet_type), str(wallet_type))


def signal_snapshot(signal):
    token = token_from_signal(signal)
    wallets = str(signal.get("triggerWalletAddress") or "")
    return {
        "chain": "solana",
        "token_address": token["address"],
        "symbol": token["symbol"],
        "name": token["name"],
        "holders": token["holders"],
        "market_cap_usd": round(token["market_cap_usd"], 4),
        "top10_holder_pct": round(token["top10_holder_pct"], 4),
        "wallet_type": str(signal.get("walletType", "")),
        "wallet_type_label": wallet_type_label(signal.get("walletType", "")),
        "trigger_wallet_count": int(fnum(signal.get("triggerWalletCount"))),
        "trigger_wallets": [w.strip() for w in wallets.split(",") if w.strip()],
        "signal_amount_usd": round(fnum(signal.get("amountUsd")), 4),
        "signal_price": fnum(signal.get("price")),
        "sold_ratio_pct": round(fnum(signal.get("soldRatioPercent")), 4),
        "signal_timestamp_ms": signal.get("timestamp"),
        "signal_cursor": signal.get("cursor"),
        "score": score_signal(signal),
    }


def tp_sl_prices(entry_price, config):
    if entry_price <= 0:
        return 0.0, 0.0
    tp = entry_price * (1 + float(config["take_profit_pct"]) / 100)
    sl = entry_price * (1 + float(config["stop_loss_pct"]) / 100)
    return round(tp, 12), round(sl, 12)


def position_metrics(pos, price=None):
    px = float(price if price is not None else pos.get("last_price", pos.get("entry_price", 0)))
    units = float(pos.get("units", 0))
    cost = float(pos.get("cost_usd", 0))
    market_value = units * px
    unrealized = market_value - cost
    pnl_pct = (px / float(pos["entry_price"]) - 1) * 100 if pos.get("entry_price") else 0.0
    return {
        "last_price": px,
        "market_value_usd": round(market_value, 4),
        "unrealized_pnl_usd": round(unrealized, 4),
        "unrealized_pnl_pct": round(pnl_pct, 4),
    }


def enrich_position(pos, config, price=None):
    snap = pos.get("signal_snapshot") or signal_snapshot(pos.get("signal") or {})
    entry = float(pos.get("entry_price", 0))
    tp, sl = tp_sl_prices(entry, config)
    metrics = position_metrics(pos, price)
    return {
        "trade_id": pos.get("trade_id"),
        "status": pos.get("status", "OPEN"),
        "address": pos.get("address"),
        "symbol": pos.get("symbol"),
        "name": pos.get("name"),
        "opened_at": pos.get("opened_at"),
        "closed_at": pos.get("closed_at"),
        "entry_round": pos.get("entry_round"),
        "exit_round": pos.get("exit_round"),
        "entry_price": entry,
        "signal_price": pos.get("signal_price", snap.get("signal_price")),
        "execution_price": entry,
        "last_price": metrics["last_price"],
        "take_profit_price": tp,
        "stop_loss_price": sl,
        "units": round(float(pos.get("units", 0)), 8),
        "cost_usd": round(float(pos.get("cost_usd", 0)), 4),
        "market_value_usd": metrics["market_value_usd"],
        "unrealized_pnl_usd": metrics["unrealized_pnl_usd"],
        "unrealized_pnl_pct": metrics["unrealized_pnl_pct"],
        "max_pnl_pct": round(float(pos.get("max_pnl_pct", 0)), 4),
        "min_pnl_pct": round(float(pos.get("min_pnl_pct", 0)), 4),
        "score": pos.get("score"),
        "wallet_type_label": snap.get("wallet_type_label"),
        "trigger_wallet_count": snap.get("trigger_wallet_count"),
        "trigger_wallets": snap.get("trigger_wallets", []),
        "signal_amount_usd": snap.get("signal_amount_usd"),
        "sold_ratio_pct": snap.get("sold_ratio_pct"),
        "holders": snap.get("holders"),
        "market_cap_usd": snap.get("market_cap_usd"),
        "top10_holder_pct": snap.get("top10_holder_pct"),
        "cash_before_buy": pos.get("cash_before_buy"),
        "cash_after_buy": pos.get("cash_after_buy"),
        "equity_at_entry": pos.get("equity_at_entry"),
        "exit_reason": pos.get("exit_reason"),
        "realized_pnl_usd": pos.get("realized_pnl_usd"),
        "realized_pnl_pct": pos.get("realized_pnl_pct"),
        "held_rounds": pos.get("held_rounds"),
        "signal_snapshot": snap,
    }


def load_state(config):
    state = load_json(STATE_PATH, init_state(config))
    state.setdefault("trade_seq", 0)
    state.setdefault("scan_count", 0)
    state.setdefault("closed_positions", [])
    state.setdefault("tick_count", 0)
    state.setdefault("cumulative_online_seconds", 0.0)
    if not state.get("sim_session_started_at"):
        state["sim_session_started_at"] = state.get("created_at") or now_iso()
    if not state.get("last_round_at"):
        state["last_round_at"] = state.get("updated_at") or state.get("created_at")
    for address, pos in list(state.get("positions", {}).items()):
        if not pos.get("trade_id"):
            pos["trade_id"] = next_trade_id(state)
        if not pos.get("signal_snapshot") and pos.get("signal"):
            pos["signal_snapshot"] = signal_snapshot(pos["signal"])
        if pos.get("signal_price") is None and pos.get("signal_snapshot"):
            pos["signal_price"] = pos["signal_snapshot"].get("signal_price")
    return state


def save_state(state, config=None):
    state["updated_at"] = now_iso()
    save_json(STATE_PATH, state)
    if config is not None:
        export_positions_csv(state, config)


def export_positions_csv(state, config):
    open_rows = []
    for pos in state["positions"].values():
        row = enrich_position(pos, config)
        row["status"] = "OPEN"
        open_rows.append(row)
    closed_rows = state.get("closed_positions", [])
    rows = open_rows + closed_rows
    if not rows:
        POSITIONS_CSV_PATH.write_text("")
        return

    fieldnames = [
        "trade_id", "status", "symbol", "name", "address",
        "opened_at", "closed_at", "entry_round", "exit_round",
        "entry_price", "signal_price", "execution_price", "last_price",
        "take_profit_price", "stop_loss_price",
        "units", "cost_usd", "market_value_usd",
        "unrealized_pnl_usd", "unrealized_pnl_pct",
        "realized_pnl_usd", "realized_pnl_pct",
        "max_pnl_pct", "min_pnl_pct", "held_rounds",
        "score", "wallet_type_label", "trigger_wallet_count",
        "signal_amount_usd", "sold_ratio_pct", "holders",
        "market_cap_usd", "top10_holder_pct",
        "cash_before_buy", "cash_after_buy", "equity_at_entry",
        "exit_reason", "trigger_wallets",
    ]
    with POSITIONS_CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["trigger_wallets"] = "|".join(row.get("trigger_wallets") or [])
            writer.writerow(out)


def append_position_snapshot(state, config, round_no):
    for address, pos in state["positions"].items():
        enriched = enrich_position(pos, config)
        append_jsonl(POSITION_SNAPSHOTS_PATH, {
            "ts": now_iso(),
            "round": round_no,
            "type": "position_snapshot",
            **{k: enriched[k] for k in enriched if k != "signal_snapshot"},
        })


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def token_from_signal(signal):
    token = signal.get("token") or {}
    return {
        "address": token.get("tokenAddress") or signal.get("tokenAddress"),
        "symbol": token.get("symbol") or "",
        "name": token.get("name") or "",
        "holders": fnum(token.get("holders")),
        "market_cap_usd": fnum(token.get("marketCapUsd")),
        "top10_holder_pct": fnum(token.get("top10HolderPercent")),
    }


def score_signal(signal):
    token = token_from_signal(signal)
    wallet_type = str(signal.get("walletType", ""))
    trigger_count = fnum(signal.get("triggerWalletCount"))
    sold_ratio = fnum(signal.get("soldRatioPercent"))
    amount_usd = fnum(signal.get("amountUsd"))

    score = 0.0
    score += min(trigger_count, 8) * 10
    score += 18 if wallet_type == "3" else 10 if wallet_type == "1" else 4
    score += min(amount_usd / 100.0, 15)
    score += max(0.0, 20 - sold_ratio / 5)
    if sold_ratio > 50:
        score -= (sold_ratio - 50) * 1.2
    score += 8 if token["holders"] >= 500 else 4 if token["holders"] >= 150 else 0
    score -= max(0.0, token["top10_holder_pct"] - 20) * 0.8
    return round(score, 2)


def reject_reasons(signal, state, config):
    token = token_from_signal(signal)
    address = token["address"]
    reasons = []
    if not address:
        reasons.append("missing_token_address")
    if address in state["positions"]:
        reasons.append("already_holding")
    if address in state["blacklist"]:
        reasons.append("blacklisted")
    if int(state["cooldowns"].get(address, 0)) > 0:
        reasons.append("cooldown")
    if fnum(signal.get("triggerWalletCount")) < config["min_trigger_wallet_count"]:
        reasons.append("low_trigger_wallet_count")
    if token["holders"] < config["min_holders"]:
        reasons.append("low_holders")
    if token["top10_holder_pct"] > config["max_top10_holder_pct"]:
        reasons.append("top10_concentration_high")
    if fnum(signal.get("soldRatioPercent")) > config["max_sold_ratio_pct"]:
        reasons.append("sold_ratio_high")
    score = score_signal(signal)
    min_score = float(config.get("min_signal_score", 0))
    if min_score and score < min_score:
        reasons.append("low_signal_score")
    wallet_type = str(signal.get("walletType", ""))
    sm_min = float(config.get("min_smart_money_score", min_score))
    if wallet_type == "1" and sm_min and score < sm_min:
        reasons.append("low_smart_money_score")
    if token["market_cap_usd"] < config["min_market_cap_usd"]:
        reasons.append("market_cap_too_low")
    if token["market_cap_usd"] > config["max_market_cap_usd"]:
        reasons.append("market_cap_too_high")
    return reasons


def fetch_signals(config):
    data = run_onchainos([
        "signal", "list",
        "--chain", config["chain"],
        "--wallet-type", config["wallet_types"],
        "--min-address-count", str(config["min_trigger_wallet_count"]),
        "--limit", str(config["signal_limit"]),
    ])
    return data if isinstance(data, list) else []


def fetch_price(config, address):
    data = run_onchainos(["market", "price", "--chain", config["chain"], "--address", address])
    item = data[0] if isinstance(data, list) and data else data
    return fnum(item.get("price")) if isinstance(item, dict) else 0.0


def position_budget(state, config):
    equity = estimate_equity(state, config, price_refresh=False)["equity_usd"]
    reserve = float(config["initial_cash_usd"]) * float(config["min_cash_reserve_pct"])
    pct_budget = equity * float(config["position_cash_pct"])
    cap_budget = equity * float(config["max_position_cash_pct"])
    available = max(0.0, float(state["cash_usd"]) - reserve)
    return max(0.0, min(pct_budget, cap_budget, available))


def open_position(state, config, signal, price):
    token = token_from_signal(signal)
    address = token["address"]
    if address in state["positions"]:
        return None
    budget = position_budget(state, config)
    if budget <= 0 or price <= 0:
        return None
    snap = signal_snapshot(signal)
    cash_before = float(state["cash_usd"])
    equity_before = estimate_equity(state, config, price_refresh=False)["equity_usd"]
    units = budget / price
    trade_id = next_trade_id(state)
    pos = {
        "trade_id": trade_id,
        "status": "OPEN",
        "address": address,
        "symbol": token["symbol"],
        "name": token["name"],
        "opened_at": now_iso(),
        "entry_round": state["round"],
        "entry_price": price,
        "signal_price": snap["signal_price"],
        "last_price": price,
        "units": units,
        "cost_usd": budget,
        "score": snap["score"],
        "signal": signal,
        "signal_snapshot": snap,
        "cash_before_buy": round(cash_before, 4),
        "equity_at_entry": round(equity_before, 4),
        "max_pnl_pct": 0.0,
        "min_pnl_pct": 0.0,
    }
    state["positions"][address] = pos
    state["cash_usd"] = round(cash_before - budget, 8)
    pos["cash_after_buy"] = round(float(state["cash_usd"]), 4)
    enriched = enrich_position(pos, config, price)
    event = {
        "ts": now_iso(),
        "type": "BUY",
        "round": state["round"],
        "trade_id": trade_id,
        **{k: enriched[k] for k in enriched if k not in ("signal_snapshot",)},
    }
    append_jsonl(TRADE_LOG_PATH, event)
    return event


def close_position(state, config, address, price, reason):
    pos = state["positions"].pop(address)
    proceeds = pos["units"] * price
    pnl = proceeds - pos["cost_usd"]
    pnl_pct = (price / pos["entry_price"] - 1) * 100 if pos["entry_price"] else 0.0
    cash_before = float(state["cash_usd"])
    state["cash_usd"] = round(cash_before + proceeds, 8)
    state["realized_pnl_usd"] = round(float(state["realized_pnl_usd"]) + pnl, 8)
    state["cooldowns"][address] = int(config.get("cooldown_rounds", 2))
    if reason == "STOP_LOSS":
        state["stop_loss_counts"][address] = int(state["stop_loss_counts"].get(address, 0)) + 1
        if state["stop_loss_counts"][address] >= int(config.get("max_stop_losses_before_ban", 2)):
            state["blacklist"][address] = {
                "symbol": pos.get("symbol"),
                "reason": "too_many_stop_losses",
                "ts": now_iso(),
            }
    pos.update({
        "status": "CLOSED",
        "closed_at": now_iso(),
        "exit_round": state["round"],
        "last_price": price,
        "exit_reason": reason,
        "realized_pnl_usd": round(pnl, 4),
        "realized_pnl_pct": round(pnl_pct, 4),
        "held_rounds": state["round"] - int(pos.get("entry_round", state["round"])),
        "proceeds_usd": round(proceeds, 4),
        "cash_before_sell": round(cash_before, 4),
        "cash_after_sell": round(float(state["cash_usd"]), 4),
    })
    closed = enrich_position(pos, config, price)
    closed["status"] = "CLOSED"
    closed["market_value_usd"] = round(proceeds, 4)
    closed["unrealized_pnl_usd"] = 0.0
    state.setdefault("closed_positions", []).append(closed)
    event = {
        "ts": now_iso(),
        "type": "SELL",
        "round": state["round"],
        "exit_reason": reason,
        "trade_id": pos.get("trade_id"),
        **{k: closed[k] for k in closed if k != "signal_snapshot"},
    }
    append_jsonl(TRADE_LOG_PATH, event)
    return event


def decay_cooldowns(state):
    for address in list(state["cooldowns"].keys()):
        state["cooldowns"][address] = max(0, int(state["cooldowns"][address]) - 1)
        if state["cooldowns"][address] == 0:
            del state["cooldowns"][address]


def check_positions(state, config):
    events = []
    for address, pos in list(state["positions"].items()):
        time.sleep(float(config.get("price_poll_sleep_seconds", 0.2)))
        price = fetch_price(config, address)
        if price <= 0:
            append_jsonl(OBS_LOG_PATH, {"ts": now_iso(), "type": "price_error", "address": address})
            continue
        pnl_pct = (price / pos["entry_price"] - 1) * 100 if pos["entry_price"] else 0.0
        pos["last_price"] = price
        pos["max_pnl_pct"] = max(float(pos.get("max_pnl_pct", 0)), pnl_pct)
        pos["min_pnl_pct"] = min(float(pos.get("min_pnl_pct", 0)), pnl_pct)
        if pnl_pct >= float(config["take_profit_pct"]):
            events.append(close_position(state, config, address, price, "TAKE_PROFIT"))
        elif pnl_pct <= float(config["stop_loss_pct"]):
            events.append(close_position(state, config, address, price, "STOP_LOSS"))
    return events


def scan_and_trade(state, config):
    state["scan_count"] = int(state.get("scan_count", 0)) + 1
    signals = fetch_signals(config)
    observations = []
    candidates = []
    best_by_address = {}
    for signal in signals:
        token = token_from_signal(signal)
        reasons = reject_reasons(signal, state, config)
        obs = {
            "ts": now_iso(),
            "round": state["round"],
            "address": token["address"],
            "symbol": token["symbol"],
            "score": score_signal(signal),
            "rejected": bool(reasons),
            "reasons": reasons,
            "signal": signal,
        }
        observations.append(obs)
        append_jsonl(OBS_LOG_PATH, obs)
        if not reasons:
            current = best_by_address.get(token["address"])
            if current is None or obs["score"] > current[0]:
                best_by_address[token["address"]] = (obs["score"], signal)

    candidates = list(best_by_address.values())
    candidates.sort(key=lambda item: item[0], reverse=True)
    opened = []
    slots = max(0, int(config["max_positions"]) - len(state["positions"]))
    for _, signal in candidates[:slots]:
        address = token_from_signal(signal)["address"]
        time.sleep(float(config.get("price_poll_sleep_seconds", 0.2)))
        price = fetch_price(config, address)
        event = open_position(state, config, signal, price)
        if event:
            opened.append(event)

    append_jsonl(OBS_LOG_PATH, {
        "ts": now_iso(),
        "type": "round_summary",
        "round": state["round"],
        "signals": len(signals),
        "candidates": len(candidates),
        "opened": len(opened),
        "positions": len(state["positions"]),
    })
    return {"signals": len(signals), "candidates": len(candidates), "opened": len(opened)}


def run_scan_cycle(state, config, force_round=False, always_scan=False):
    advanced = advance_round_if_due(state, config, force=force_round)
    if advanced:
        decay_cooldowns(state)
    if not advanced and not always_scan:
        return {
            "skipped": True,
            "reason": "within_scan_interval",
            "round": state["round"],
            "scan_count": state.get("scan_count", 0),
            "next_round_in_seconds": round(seconds_until_next_round(state, config)),
        }
    result = scan_and_trade(state, config)
    result.update({
        "skipped": False,
        "round_advanced": advanced,
        "round": state["round"],
        "scan_count": state.get("scan_count", 0),
        "next_round_in_seconds": round(seconds_until_next_round(state, config)),
    })
    return result


def estimate_equity(state, config, price_refresh=True):
    positions_value = 0.0
    for address, pos in state["positions"].items():
        price = pos.get("last_price", pos.get("entry_price", 0.0))
        if price_refresh:
            try:
                price = fetch_price(config, address)
                pos["last_price"] = price
            except Exception:
                pass
        positions_value += float(pos["units"]) * float(price)
    equity = float(state["cash_usd"]) + positions_value
    return {
        "cash_usd": float(state["cash_usd"]),
        "positions_value_usd": positions_value,
        "equity_usd": equity,
        "realized_pnl_usd": float(state.get("realized_pnl_usd", 0.0)),
        "open_positions": len(state["positions"]),
    }


def write_report(state, config):
    summary = estimate_equity(state, config, price_refresh=True)
    state["last_equity_usd"] = summary["equity_usd"]
    open_positions = [enrich_position(p, config) for p in state["positions"].values()]
    append_position_snapshot(state, config, state["round"])
    report = {
        "ts": now_iso(),
        "round": state["round"],
        "summary": summary,
        "open_positions": open_positions,
        "closed_positions": state.get("closed_positions", []),
        "cooldowns": state["cooldowns"],
        "blacklist": state["blacklist"],
        "reconciliation": {
            "initial_cash_usd": float(config["initial_cash_usd"]),
            "cash_usd": summary["cash_usd"],
            "positions_value_usd": summary["positions_value_usd"],
            "equity_usd": summary["equity_usd"],
            "realized_pnl_usd": summary["realized_pnl_usd"],
            "unrealized_pnl_usd": round(
                sum(p["unrealized_pnl_usd"] for p in open_positions), 4
            ),
        },
    }
    out = ROOT / "reports" / f"report_round_{state['round']:04d}.json"
    report["strategy_analysis"] = save_analysis(state, config)
    save_json(out, report)
    export_positions_csv(state, config)
    export_dashboard_snapshot(state, config, report)
    return report


def cmd_init(args):
    config = load_json(CONFIG_PATH, {})
    if STATE_PATH.exists() and not args.force:
        print(f"state exists: {STATE_PATH}")
        return
    state = init_state(config)
    save_state(state, config)
    print(f"initialized {STATE_PATH}")


def cmd_reset(args):
    config = load_json(CONFIG_PATH, {})
    if STATE_PATH.exists() and not args.force:
        print(f"Refusing reset without --force (would wipe {STATE_PATH} and trade logs)")
        return
    state = reset_sim_data(config)
    export_dashboard_snapshot(state, config)
    print(json.dumps({
        "reset": True,
        "strategy_version": config.get("strategy_version"),
        "cash_usd": state["cash_usd"],
        "equity_usd": state["cash_usd"],
        "open_positions": 0,
        "runtime": build_runtime_status(state, config),
    }, indent=2, ensure_ascii=False))


def cmd_scan(args):
    config = load_json(CONFIG_PATH, {})
    state = load_state(config)
    result = run_scan_cycle(
        state,
        config,
        force_round=getattr(args, "force_round", False),
        always_scan=True,
    )
    save_state(state, config)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_check(_args):
    config = load_json(CONFIG_PATH, {})
    state = load_state(config)
    events = check_positions(state, config)
    save_state(state, config)
    print(json.dumps({"closed": len(events), "events": events}, indent=2, ensure_ascii=False))


def cmd_tick(args):
    config = load_json(CONFIG_PATH, {})
    state = load_state(config)
    if config.get("sim_enabled") is False:
        closed = check_positions(state, config)
        report = write_report(state, config)
        save_state(state, config)
        print(json.dumps({
            "paused": True,
            "message": "sim_enabled=false: no new scans; open positions still checked for TP/SL",
            "closed": len(closed),
            "round": state["round"],
            "summary": report["summary"],
            "runtime": build_runtime_status(state, config),
        }, indent=2, ensure_ascii=False))
        return
    closed = check_positions(state, config)
    result = run_scan_cycle(state, config, force_round=getattr(args, "force_round", False))
    record_tick(state, config)
    report = write_report(state, config)
    save_state(state, config)
    print(json.dumps({
        "closed": len(closed),
        "scan": result,
        "round": state["round"],
        "scan_count": state.get("scan_count", 0),
        "summary": report["summary"],
    }, indent=2, ensure_ascii=False))


def cmd_report(_args):
    config = load_json(CONFIG_PATH, {})
    state = load_state(config)
    report = write_report(state, config)
    save_state(state, config)
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print(f"positions csv: {POSITIONS_CSV_PATH}")


def cmd_memory(args):
    append_lesson(args.text)
    print(f"appended lesson to {LESSONS_PATH}")


def cmd_loop(_args):
    config = load_json(CONFIG_PATH, {})
    while True:
        start = time.time()
        try:
            cmd_tick(None)
        except Exception as exc:
            append_jsonl(OBS_LOG_PATH, {"ts": now_iso(), "type": "loop_error", "error": str(exc)})
            print(f"loop error: {exc}")
        elapsed = time.time() - start
        time.sleep(max(0, float(config["scan_interval_seconds"]) - elapsed))


def main():
    parser = argparse.ArgumentParser(description="Onchain meme paper trading explorer")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("init")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("reset")
    p.add_argument("--force", action="store_true", help="clear state, positions, and trade logs")
    p.set_defaults(func=cmd_reset)
    p = sub.add_parser("scan")
    p.add_argument("--force-round", action="store_true", help="start a new round even if scan interval has not elapsed")
    p.set_defaults(func=cmd_scan)
    sub.add_parser("check").set_defaults(func=cmd_check)
    p = sub.add_parser("tick")
    p.add_argument("--force-round", action="store_true", help="start a new round even if scan interval has not elapsed")
    p.set_defaults(func=cmd_tick)
    sub.add_parser("report").set_defaults(func=cmd_report)

    def cmd_export(_args):
        config = load_json(CONFIG_PATH, {})
        state = load_state(config)
        export_positions_csv(state, config)
        export_dashboard_snapshot(state, config)
        print(f"exported {POSITIONS_CSV_PATH}")
        print(f"dashboard snapshot: {DASHBOARD_SNAPSHOT_PATH}")

    def cmd_dashboard(_args):
        config = load_json(CONFIG_PATH, {})
        state = load_state(config)
        report = write_report(state, config)
        save_state(state, config)
        print(f"dashboard snapshot: {DASHBOARD_SNAPSHOT_PATH}")
        print(json.dumps(report["summary"], indent=2, ensure_ascii=False))

    def cmd_analyze(_args):
        config = load_json(CONFIG_PATH, {})
        state = load_state(config)
        analysis = save_analysis(state, config)
        print(json.dumps(analysis, indent=2, ensure_ascii=False))

    sub.add_parser("analyze").set_defaults(func=cmd_analyze)

    def cmd_optimize(args):
        if apply_recommendation is None:
            raise RuntimeError("strategy_optimizer module not found")
        if getattr(args, "apply", False):
            report = apply_recommendation()
            print("applied config:", CONFIG_PATH)
        else:
            report = optimize_analyze()
            out = ROOT / "config" / "strategy_recommendation.json"
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(f"recommendation: {out}")
        print(json.dumps({
            "insights": report.get("insights"),
            "win_rate_pct": report.get("win_rate_pct"),
            "recommended": report.get("recommended_config", {}).get("strategy_version"),
        }, indent=2, ensure_ascii=False))

    p = sub.add_parser("optimize")
    p.add_argument("--apply", action="store_true", help="write recommended config to config.json")
    p.set_defaults(func=cmd_optimize)

    sub.add_parser("export").set_defaults(func=cmd_export)
    sub.add_parser("dashboard").set_defaults(func=cmd_dashboard)
    p = sub.add_parser("memory")
    p.add_argument("text")
    p.set_defaults(func=cmd_memory)
    sub.add_parser("loop").set_defaults(func=cmd_loop)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
