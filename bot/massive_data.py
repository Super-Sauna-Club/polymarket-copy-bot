"""Massive.com market data integration for additional market data signals."""

import logging
import time
from datetime import datetime, timedelta

import requests

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"
_cache = {}
CACHE_TTL = 900  # 15 minutes


def _get(endpoint: str, params: dict = None) -> dict | None:
    """Make authenticated GET request to Massive API."""
    if not config.MASSIVE_API_KEY:
        return None

    cache_key = f"{endpoint}:{params}"
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    headers = {"Authorization": f"Bearer {config.MASSIVE_API_KEY}"}
    try:
        resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _cache[cache_key] = (data, time.time())
        return data
    except Exception as e:
        logger.debug("Massive API error (%s): %s", endpoint, e)
        return None


def get_index_trend(ticker: str = "SPY", days: int = 5) -> dict | None:
    """Get recent price trend for an index/ETF (e.g. SPY, QQQ)."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _get(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}", {"sort": "asc"})
    if not data or not data.get("results"):
        return None

    results = data["results"]
    first_close = results[0]["c"]
    last_close = results[-1]["c"]
    change_pct = round((last_close - first_close) / first_close * 100, 2)

    return {
        "ticker": ticker,
        "current_price": last_close,
        "change_pct_5d": change_pct,
        "trend": "bullish" if change_pct > 1 else "bearish" if change_pct < -1 else "neutral",
    }


def get_crypto_price(pair: str = "X:BTCUSD") -> dict | None:
    """Get latest crypto price data."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    data = _get(f"/v2/aggs/ticker/{pair}/range/1/day/{start}/{end}", {"sort": "desc", "limit": 1})
    if not data or not data.get("results"):
        return None

    r = data["results"][0]
    return {"pair": pair, "price": r["c"], "volume": r.get("v", 0)}


def get_market_context() -> str:
    """Build a market context string for the AI analyzer."""
    sections = []

    # S&P 500 trend
    spy = get_index_trend("SPY", 5)
    if spy:
        sections.append(
            f"S&P 500 (SPY): ${spy['current_price']:.2f}, "
            f"{spy['change_pct_5d']:+.1f}% (5 Tage), Trend: {spy['trend']}"
        )

    # Nasdaq trend
    qqq = get_index_trend("QQQ", 5)
    if qqq:
        sections.append(
            f"Nasdaq (QQQ): ${qqq['current_price']:.2f}, "
            f"{qqq['change_pct_5d']:+.1f}% (5 Tage), Trend: {qqq['trend']}"
        )

    # Bitcoin
    btc = get_crypto_price("X:BTCUSD")
    if btc:
        sections.append(f"Bitcoin: ${btc['price']:,.0f}")

    # Ethereum
    eth = get_crypto_price("X:ETHUSD")
    if eth:
        sections.append(f"Ethereum: ${eth['price']:,.0f}")

    if not sections:
        return ""

    return "MARKTDATEN (Massive.com):\n" + "\n".join(f"- {s}" for s in sections)
