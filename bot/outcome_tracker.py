"""Outcome Tracker — checks what would have happened with blocked trades.

Periodically queries Polymarket API for final/current prices of markets
where we blocked a trade, and records whether it would have been a winner.
"""
import logging
import requests

import config
from database import db

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _get_market_price(condition_id: str) -> tuple:
    """Get current price and resolution status for a market.

    Returns (price, is_resolved) where price is 0-1 float.
    is_resolved is True if the market has settled.
    """
    try:
        # Try CLOB book first (most accurate for live markets)
        r = requests.get(f"{CLOB_API}/book", params={"token_id": condition_id},
                         timeout=config.API_TIMEOUT)
        if r.ok:
            book = r.json()
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if bids and asks:
                best_bid = float(bids[0].get("price", 0))
                best_ask = float(asks[0].get("price", 0))
                mid = (best_bid + best_ask) / 2
                return mid, False
    except Exception:
        pass

    # Fallback: check if resolved via positions API
    try:
        r = requests.get(f"{DATA_API}/positions", params={
            "user": config.POLYMARKET_FUNDER,
            "limit": 500,
            "sizeThreshold": 0,
        }, timeout=config.DATA_API_TIMEOUT)
        if r.ok:
            for p in r.json():
                if p.get("conditionId") == condition_id:
                    cp = float(p.get("curPrice", 0) or 0)
                    is_resolved = cp >= 0.99 or cp <= 0.01
                    return cp, is_resolved
    except Exception:
        pass

    return None, False


def _would_trade_have_won(side: str, trader_price: float, outcome_price: float) -> bool:
    """Determine if a blocked trade would have been profitable.

    A YES bet wins if price goes to 1.0, loses if goes to 0.
    A NO bet wins if price goes to 0.0, loses if goes to 1.0.
    For unresolved markets: check if current price moved favorably.
    """
    if outcome_price is None:
        return False

    if side.upper() in ("YES", "Y"):
        # YES bet: profit if price went up significantly from entry
        return outcome_price > trader_price + 0.05
    elif side.upper() in ("NO", "N"):
        # NO bet: profit if price went down significantly from entry
        return outcome_price < trader_price - 0.05

    # Unknown side — check if resolved favorably
    return outcome_price >= 0.95


def track_outcomes():
    """Check outcomes for blocked trades that haven't been checked yet.

    Only checks trades older than 2 hours (give markets time to develop).
    Marks resolved markets definitively, live markets tentatively.
    """
    unchecked = db.get_blocked_trades_unchecked(limit=100)
    if not unchecked:
        return 0

    checked = 0
    for bt in unchecked:
        cid = bt["condition_id"]
        if not cid:
            continue

        price, is_resolved = _get_market_price(cid)
        if price is None:
            continue

        # For resolved markets: definitive outcome
        if is_resolved:
            won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price) else 0
            db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
            checked += 1
        elif price >= 0.99 or price <= 0.01:
            # Clearly resolved even if API doesn't say so
            won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price) else 0
            db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
            checked += 1
        else:
            # Live market — only update if trade is old enough (>4h)
            import time
            from datetime import datetime
            try:
                created = datetime.strptime(bt["created_at"], "%Y-%m-%d %H:%M:%S")
                age_hours = (datetime.now() - created).total_seconds() / 3600
                if age_hours > 4:
                    # Mark tentatively based on price movement
                    won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price) else 0
                    db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
                    checked += 1
            except Exception:
                pass

    if checked > 0:
        logger.info("[OUTCOME] Checked %d/%d blocked trade outcomes", checked, len(unchecked))
    return checked
