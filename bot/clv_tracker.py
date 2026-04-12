"""
CLV Tracker — Closing Line Value.
Misst ob wir besser kaufen als der Schlusspreis.
Positiver CLV = echter Edge, negativer CLV = wir zahlen zu viel.
"""
import logging
import requests
from database import db

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


def update_clv_for_closed_trades():
    """Berechne CLV fuer geschlossene Trades und persistiere wins/losses."""
    with db.get_connection() as conn:
        trades = conn.execute(
            "SELECT id, condition_id, side, entry_price, actual_entry_price, "
            "pnl_realized, current_price, market_question "
            "FROM copy_trades WHERE status = 'closed' AND condition_id != ''"
        ).fetchall()

    total_clv = 0.0
    count = 0
    wins = 0
    losses = 0
    total_pnl = 0.0

    for t in trades:
        t = dict(t)
        entry = t["actual_entry_price"] or t["entry_price"] or 0
        pnl = t["pnl_realized"] or 0
        if entry <= 0:
            continue

        closing_price = t.get("current_price") if t.get("current_price") else (1.0 if pnl > 0 else 0.0)
        if closing_price is None or closing_price <= 0:
            continue

        side = (t.get("side") or "YES").upper()
        if side == "NO":
            clv = entry - closing_price
        else:
            clv = closing_price - entry
        total_clv += clv
        total_pnl += pnl
        count += 1
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    if count > 0:
        avg_clv = round(total_clv / count, 4)
        with db.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO signal_performance "
                "(signal_type, trades_count, total_pnl, wins, losses, updated_at) "
                "VALUES ('clv_tracking', ?, ?, ?, ?, datetime('now','localtime'))",
                (count, round(total_pnl, 2), wins, losses)
            )
        logger.info("[CLV] %d trades, %d wins, %d losses, avg CLV: %.2f%%",
                    count, wins, losses, avg_clv * 100)
    return {"avg_clv": round(total_clv / count * 100, 2) if count > 0 else 0,
            "trades": count, "wins": wins, "losses": losses}


def get_clv_by_trader():
    """CLV pro Trader berechnen."""
    with db.get_connection() as conn:
        trades = conn.execute(
            "SELECT wallet_username, side, entry_price, actual_entry_price, pnl_realized, current_price "
            "FROM copy_trades WHERE status = 'closed' AND pnl_realized IS NOT NULL"
        ).fetchall()

    by_trader = {}
    for t in trades:
        t = dict(t)
        trader = t["wallet_username"] or "?"
        entry = t["actual_entry_price"] or t["entry_price"] or 0
        pnl = t["pnl_realized"] or 0
        if entry <= 0:
            continue

        closing = t.get("current_price") if t.get("current_price") else (1.0 if pnl > 0 else 0.0)
        side = (t.get("side") or "YES").upper()
        clv = (entry - closing) if side == "NO" else (closing - entry)

        if trader not in by_trader:
            by_trader[trader] = {"total_clv": 0, "count": 0}
        by_trader[trader]["total_clv"] += clv
        by_trader[trader]["count"] += 1

    result = {}
    for trader, data in by_trader.items():
        if data["count"] > 0:
            result[trader] = round(data["total_clv"] / data["count"] * 100, 2)

    return result
