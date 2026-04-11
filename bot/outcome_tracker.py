"""Outcome Tracker — checks what would have happened with blocked trades.

Periodically queries Polymarket API for final/current prices of markets
where we blocked a trade, and records whether it would have been a winner.

Uses the Gamma Markets API (condition_id based) for price lookups,
falling back to CLOB book (token_id/asset based) for live markets.
"""
import logging
import time
import requests

import config
from database import db

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _get_market_price(condition_id: str, asset: str = "") -> tuple:
    """Get current price and resolution status for a market.

    Uses multiple strategies:
    1. CLOB book with asset/token_id (most accurate for live markets)
    2. Gamma events API with condition_id (works for resolved + live)

    Returns (price, is_resolved) where price is 0-1 float.
    """
    # Strategy 1: CLOB book with asset (ERC-1155 token ID)
    if asset:
        try:
            r = requests.get(f"{CLOB_API}/book", params={"token_id": asset},
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
                # Empty book = likely resolved
                if not bids and not asks:
                    pass  # fall through to Gamma check
        except Exception:
            pass

    # Strategy 2: Gamma markets API with condition_id
    if condition_id:
        try:
            r = requests.get(f"{GAMMA_API}/markets",
                             params={"condition_id": condition_id, "limit": 1},
                             timeout=config.API_TIMEOUT)
            if r.ok:
                markets = r.json()
                if markets and isinstance(markets, list) and len(markets) > 0:
                    m = markets[0]
                    resolved = m.get("resolved", False) or m.get("closed", False)
                    # outcomePrices is a JSON string like "[0.95, 0.05]"
                    price_str = m.get("outcomePrices", "")
                    if price_str:
                        import json
                        try:
                            prices = json.loads(price_str) if isinstance(price_str, str) else price_str
                            if prices and len(prices) > 0:
                                price = float(prices[0])
                                return price, resolved
                        except (json.JSONDecodeError, ValueError):
                            pass
                    # Fallback: use bestAsk/bestBid
                    best_ask = float(m.get("bestAsk", 0) or 0)
                    best_bid = float(m.get("bestBid", 0) or 0)
                    if best_ask > 0 and best_bid > 0:
                        return (best_bid + best_ask) / 2, resolved
                    elif best_ask > 0:
                        return best_ask, resolved
        except Exception:
            pass

    return None, False


def _would_trade_have_won(side: str, trader_price: float, outcome_price: float,
                          is_resolved: bool = False) -> bool:
    """Determine if a blocked trade would have been profitable.

    Handles all side formats:
    - "YES"/"NO" — standard binary
    - Team names, "Over"/"Under" — treated as YES-equivalent (bought that outcome)

    For resolved markets: price near 1.0 = this outcome won.
    For live markets: check if price moved favorably from entry.
    """
    if outcome_price is None:
        return False

    if is_resolved:
        # Resolved: price >= 0.95 means this outcome won
        if side.upper() in ("NO", "N"):
            return outcome_price <= 0.05  # NO wins when price → 0
        else:
            return outcome_price >= 0.95  # YES/team/Over wins when price → 1

    # Live market: check if price moved favorably
    if side.upper() in ("NO", "N"):
        return outcome_price < trader_price - 0.05
    else:
        # YES, team name, Over, Under — all are "bought this outcome"
        return outcome_price > trader_price + 0.05


def track_outcomes():
    """Check outcomes for blocked trades that haven't been checked yet.

    Only checks trades older than 2 hours (give markets time to develop).
    Marks resolved markets definitively, live markets tentatively (if >4h old).
    """
    unchecked = db.get_blocked_trades_unchecked(limit=100)
    if not unchecked:
        return 0

    checked = 0
    errors = 0
    for bt in unchecked:
        cid = bt["condition_id"]
        if not cid:
            continue

        asset = bt.get("asset", "") or ""
        price, is_resolved = _get_market_price(cid, asset)
        if price is None:
            errors += 1
            continue

        if is_resolved:
            # Resolved: definitive outcome
            won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price, True) else 0
            db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
            checked += 1
        elif price >= 0.99 or price <= 0.01:
            # Clearly resolved even if API doesn't flag it
            won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price, True) else 0
            db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
            checked += 1
        else:
            # Live market — only update if trade is old enough (>4h)
            try:
                from datetime import datetime
                created = datetime.strptime(bt["created_at"], "%Y-%m-%d %H:%M:%S")
                age_hours = (datetime.now() - created).total_seconds() / 3600
                if age_hours > 4:
                    won = 1 if _would_trade_have_won(bt["side"], bt["trader_price"], price, False) else 0
                    db.update_blocked_trade_outcome(bt["id"], round(price, 4), won)
                    checked += 1
            except Exception:
                pass

        # Rate limit: don't hammer the API
        time.sleep(0.2)

    if checked > 0 or errors > 0:
        logger.info("[OUTCOME] Checked %d/%d blocked trade outcomes (%d API errors)",
                    checked, len(unchecked), errors)
    return checked
