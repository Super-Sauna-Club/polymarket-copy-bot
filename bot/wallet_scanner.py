import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

POLYMARKET_PROFILE_URL = "https://polymarket.com/profile"
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Zero-Drawdown-Schwelle: 100% WR + min. N Trades → verdächtig (Manipulation/Insider)
ZERO_DRAWDOWN_MIN_TRADES = 20

# Domain-Keywords für Trader-Spezialisierung
_DOMAIN_KEYWORDS = {
    "Sports":   ["nba", "nfl", "nhl", "mlb", "soccer", "football", "tennis", "basketball",
                 "baseball", "hockey", "match", "championship", "playoff", "super bowl",
                 "world cup", "tournament", "league", "season", "game", "score", "player",
                 "team", "coach", "transfer", "draft", "mvp"],
    "Crypto":   ["bitcoin", "btc", "eth", "ethereum", "crypto", "token", "blockchain",
                 "defi", "nft", "altcoin", "stablecoin", "exchange", "mining", "solana",
                 "price", "ath", "bear", "bull", "market cap", "doge", "xrp", "binance"],
    "Politics": ["president", "election", "vote", "senate", "congress", "trump", "biden",
                 "harris", "republican", "democrat", "government", "policy", "minister",
                 "parliament", "party", "candidate", "poll", "tariff", "war", "nato",
                 "supreme court", "impeach", "inauguration", "nominee"],
    "Finance":  ["stock", "fed", "interest rate", "gdp", "inflation", "earnings", "ipo",
                 "recession", "s&p", "nasdaq", "oil", "gold", "unemployment", "cpi",
                 "nasdaq", "dow jones", "treasury", "bond", "yield", "central bank"],
}


def _detect_domain(questions: list[str]) -> str:
    """Erkennt die Haupt-Kategorie eines Traders anhand seiner Trade-Fragen."""
    scores = {d: 0 for d in _DOMAIN_KEYWORDS}
    for q in questions:
        q_lower = q.lower()
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in q_lower:
                    scores[domain] += 1
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if total == 0:
        return "General"
    if scores[best] / total >= 0.40:
        return best
    return "Mixed"


def fetch_leaderboard_wallets(limit=500, time_period="MONTH", order_by="PNL") -> list[dict]:
    """Fetch top wallets from Polymarket leaderboard via data-api."""
    logger.info("Fetching top %d wallets from Polymarket leaderboard (%s by %s)...", limit, time_period, order_by)

    wallets = []
    page_size = 50  # API max is 50
    offset = 0

    while len(wallets) < limit and offset <= 1000:
        try:
            response = requests.get(
                f"{DATA_API}/v1/leaderboard",
                params={
                    "limit": min(page_size, limit - len(wallets)),
                    "offset": offset,
                    "timePeriod": time_period,
                    "orderBy": order_by,
                    "category": "OVERALL",
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            for entry in data:
                address = entry.get("proxyWallet") or entry.get("userAddress") or entry.get("address", "")
                wallets.append({
                    "address": address,
                    "username": entry.get("userName") or entry.get("displayName", ""),
                    "volume": float(entry.get("vol") or entry.get("volume") or 0),
                    "pnl": float(entry.get("pnl") or entry.get("profit") or 0),
                    "markets_traded": int(entry.get("marketsTraded") or entry.get("numMarkets") or 0),
                    "rank": int(entry.get("rank") or (offset + len(wallets) + 1)),
                    "profile_url": f"{POLYMARKET_PROFILE_URL}/{address}",
                    "source": "leaderboard",
                })

            offset += page_size
            time.sleep(0.3)

        except requests.RequestException as e:
            logger.error("Failed to fetch leaderboard page (offset=%d): %s", offset, e)
            break

    # Calculate ROI = PNL / Volume and sort by efficiency
    for w in wallets:
        vol = w["volume"]
        w["roi"] = round((w["pnl"] / vol) if vol > 0 else 0, 4)
    wallets.sort(key=lambda w: w["roi"], reverse=True)

    logger.info("Fetched %d wallets from leaderboard (sorted by ROI).", len(wallets))
    return wallets


def fetch_wallet_positions(address: str) -> list[dict]:
    """Fetch ALL positions for a wallet via data-api (with pagination)."""
    try:
        all_positions = []
        offset = 0
        page_size = 500
        while True:
            response = requests.get(
                f"{DATA_API}/positions",
                params={
                    "user": address,
                    "limit": page_size,
                    "offset": offset,
                    "sizeThreshold": 0.1,
                    "sortBy": "CURRENT",
                    "sortDirection": "DESC",
                },
                timeout=15,
            )
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            all_positions.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        positions = all_positions

        results = []
        for p in positions:
            outcome = p.get("outcome", "")
            # Side: YES/NO for binary markets, otherwise the actual outcome name
            if outcome.lower() in ("yes", "y"):
                side = "YES"
            elif outcome.lower() in ("no", "n"):
                side = "NO"
            else:
                side = outcome or "YES"
            # Outcome-Label: Bei Multi-Outcome-Märkten ist der Titel der Option-Name
            # z.B. "Lakers", "Pistons (-3.5)" statt "Will Lakers win?"
            title = p.get("title") or p.get("question", "")
            if outcome.lower() not in ("yes", "no", "y", "n", ""):
                # Outcome ist direkt der Name (z.B. "Lakers")
                outcome_label = outcome
            elif len(title) < 50 and "?" not in title:
                # Kurzer Titel ohne Fragezeichen = Option-Name (z.B. "Lakers")
                outcome_label = title
            else:
                outcome_label = ""
            results.append({
                "market_question": p.get("title") or p.get("question", "Unknown"),
                "market_slug": p.get("slug") or p.get("eventSlug", ""),
                "event_slug": p.get("eventSlug") or "",
                "side": side,
                "outcome_label": outcome_label,
                "size": float(p.get("currentValue") or p.get("size") or 0),
                "avg_price": float(p.get("avgPrice") or p.get("averagePrice") or 0),
                "current_price": float(p.get("curPrice") or p.get("currentPrice") or 0),
                "pnl": float(p.get("cashPnl") or p.get("pnl") or 0),
                "end_date": p.get("endDate") or "",
                "redeemable": bool(p.get("redeemable", False)),
                "condition_id": p.get("conditionId", ""),
                "asset": p.get("asset", ""),
            })

        return results

    except requests.RequestException as e:
        logger.debug("Failed to fetch positions for %s: %s", address[:10], e)
        return []


def fetch_wallet_trades(address: str) -> dict:
    """Fetch closed positions + activity count for win rate and trade stats."""
    try:
        # Paginate closed positions to get accurate count (up to 500)
        all_closed = []
        offset = 0
        page_size = 50  # API max is 50
        while len(all_closed) < 500:
            response = requests.get(
                f"{DATA_API}/closed-positions",
                params={"user": address, "limit": page_size, "offset": offset},
                timeout=15,
            )
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            all_closed.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

        # Also count total activity (BUY+SELL) for trade count
        act_resp = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "type": "TRADE", "limit": 1},
            timeout=10,
        )
        # Use closed positions count as base
        closed = all_closed
        if not closed:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_trade_size": 0}

        wins = sum(1 for t in closed if float(t.get("realizedPnl") or 0) > 0)
        losses = sum(1 for t in closed if float(t.get("realizedPnl") or 0) < 0)
        total = len(closed)
        sizes = [abs(float(t.get("totalBought") or 0)) for t in closed]

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_trade_size": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        }

    except requests.RequestException as e:
        logger.debug("Failed to fetch closed positions for %s: %s", address[:10], e)
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_trade_size": 0}


def fetch_wallet_recent_trades(address: str, limit: int = 50) -> list[dict]:
    """Fetch recent trade activities for a wallet (newest first).

    Uses /activity?type=TRADE endpoint (same as CryptoVictormt/polymarket-copy-trading-bot).
    Key advantage: usdcSize field = exact dollar amount spent (no calculation needed).
    """
    try:
        response = requests.get(
            f"{DATA_API}/activity",
            params={"user": address, "type": "TRADE", "limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        trades = response.json()
        if not trades:
            return []

        result = []
        for t in trades:
            outcome = t.get("outcome", "")
            if outcome.lower() in ("yes", "y"):
                side = "YES"
            elif outcome.lower() in ("no", "n"):
                side = "NO"
            else:
                side = outcome or "YES"

            outcome_label = outcome if side not in ("YES", "NO") else ""

            result.append({
                "transaction_hash": t.get("transactionHash", ""),
                "condition_id": t.get("conditionId", ""),
                "side": side,
                "outcome_label": outcome_label,
                "price": float(t.get("price") or 0),
                "usdc_size": float(t.get("usdcSize") or 0),   # exact dollar amount
                "timestamp": int(t.get("timestamp") or 0),
                "market_question": t.get("title") or "",
                "market_slug": t.get("slug") or "",
                "event_slug": t.get("eventSlug") or "",
                "trade_type": t.get("side", ""),  # "BUY" or "SELL"
                "end_date": t.get("endDate") or t.get("end_date") or "",
            })
        return result
    except requests.RequestException as e:
        logger.debug("Failed to fetch recent trades for %s: %s", address[:10], e)
        return []


def fetch_wallet_closed_positions(address: str, limit: int = 500) -> list[dict]:
    """Fetch ALL closed positions with condition_id for smart trade matching.
    
    Returns list of closed positions that we can match against our copy trades.
    """
    try:
        all_closed = []
        offset = 0
        page_size = 50  # API max is 50

        while len(all_closed) < limit and offset <= 5000:
            response = requests.get(
                f"{DATA_API}/closed-positions",
                params={
                    "user": address,
                    "limit": page_size,
                    "offset": offset,
                },
                timeout=15,
            )
            response.raise_for_status()
            page = response.json()
            
            if not page:
                break
            
            # Parse closed positions with condition_id if available
            for pos in page:
                closed_item = {
                    "market_question": pos.get("title") or pos.get("question", ""),
                    "condition_id": pos.get("conditionId", ""),
                    "asset": pos.get("asset", ""),
                    "side": pos.get("outcome", ""),
                    "closed_price": float(pos.get("closePrice") or pos.get("settlementPrice") or 0),
                    "realized_pnl": float(pos.get("realizedPnl") or pos.get("pnl") or 0),
                    "closed_at": pos.get("closedAt") or pos.get("updatedAt", ""),
                }
                all_closed.append(closed_item)
            
            if len(page) < page_size:
                break
            
            offset += page_size
            import time
            time.sleep(0.2)
        
        logger.debug("Fetched %d closed positions for %s", len(all_closed), address[:10])
        return all_closed[:limit]
    
    except requests.RequestException as e:
        logger.debug("Failed to fetch closed positions for %s: %s", address[:10], e)
        return []


def fetch_wallet_profile(address: str) -> dict:
    """Fetch public profile for a wallet."""
    try:
        response = requests.get(
            f"{GAMMA_API}/public-profile",
            params={"address": address},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return {}


def filter_wallets(wallets: list[dict]) -> list[dict]:
    """Filter wallets by minimum criteria."""
    filtered = []
    for w in wallets:
        if not w.get("address"):
            continue
        if w.get("volume", 0) < config.MIN_VOLUME:
            continue
        if w.get("pnl", 0) < config.MIN_PNL:
            continue
        filtered.append(w)

    logger.info("Filtered to %d wallets from %d total.", len(filtered), len(wallets))
    return filtered


def auto_follow_top_traders(count: int = 5, exclude: set = None, require_recent: bool = False) -> list[dict]:
    """Fetch leaderboard, rank by ROI, auto-follow top N traders.

    Kriterien:
    - Win Rate >= 85%
    - Positiver PNL gesamt (ALL TIME)
    - Positiver PNL diesen Monat
    - Mindestens 1 Trade heute
    - Min 10 Trades gesamt
    """
    from database import db

    # Vier Leaderboards: ALL + MONTH + WEEK + DAY
    logger.info("Auto-Follow: Lade Leaderboard (ALL + MONTH + WEEK + DAY)...")
    wallets_all   = fetch_leaderboard_wallets(limit=200, time_period="ALL",   order_by="PNL")
    wallets_month = fetch_leaderboard_wallets(limit=200, time_period="MONTH", order_by="PNL")
    wallets_week  = fetch_leaderboard_wallets(limit=200, time_period="WEEK",  order_by="PNL")
    wallets_day   = fetch_leaderboard_wallets(limit=200, time_period="DAY",   order_by="PNL")

    # Positiver PNL in ALLEN vier Zeiträumen — nur die echten Besten
    profitable_month = {w["address"] for w in wallets_month if w["pnl"] > 0}
    profitable_week  = {w["address"] for w in wallets_week  if w["pnl"] > 0}
    profitable_day   = {w["address"] for w in wallets_day   if w["pnl"] > 0}

    wallets = [w for w in wallets_all
               if w["pnl"] > 0
               and w["address"] in profitable_month
               and w["address"] in profitable_week
               and w["address"] in profitable_day]
    wallets = filter_wallets(wallets)

    logger.info("Auto-Follow: %d Kandidaten (ALL+MONTH positiv)...", len(wallets))

    # Inaktive Trader ausschließen (werden ersetzt)
    if exclude:
        wallets = [w for w in wallets if w["address"] not in exclude]

    candidates = []
    for w in wallets[:80]:
        stats = fetch_wallet_trades(w["address"])
        w["win_rate"] = stats["win_rate"]
        w["total_trades"] = stats["total_trades"]

        if stats["total_trades"] < 10:
            continue

        # Min 500 Trades insgesamt (Activity-Endpoint: zuverlässiger als closed-positions)
        try:
            r1 = requests.get(f"{DATA_API}/activity",
                params={"user": w["address"], "type": "TRADE", "limit": 500, "offset": 0}, timeout=15)
            r2 = requests.get(f"{DATA_API}/activity",
                params={"user": w["address"], "type": "TRADE", "limit": 500, "offset": 500}, timeout=15)
            act_count = (len(r1.json()) if r1.ok else 0) + (len(r2.json()) if r2.ok else 0)
        except Exception:
            act_count = 0
        if act_count < 500:
            logger.info("  [SKIP] %s — nur %d Trades insgesamt (< 500)",
                        w.get("username", w["address"][:12]), act_count)
            time.sleep(0.3)
            continue

        # Aktiv in den letzten 20 Min — Pflicht
        now_ts = int(time.time())
        recent = fetch_wallet_recent_trades(w["address"], limit=20)
        twenty_min_ago = now_ts - 20 * 60
        four_hours_ago = now_ts - 4 * 3600
        trades_20min = sum(1 for t in recent if t["timestamp"] > twenty_min_ago)
        trades_4h    = sum(1 for t in recent if t["timestamp"] > four_hours_ago)

        if trades_20min < 1:
            if require_recent:
                # Idle-Replace: NUR Trader die in letzten 20 Min aktiv waren
                logger.info("  [SKIP] %s — kein Trade in letzten 20 Min (require_recent)",
                            w.get("username", w["address"][:12]))
                time.sleep(0.3)
                continue
            # Fallback: letzte 4 Stunden akzeptieren wenn niemand in 20 Min aktiv ist
            if trades_4h < 1:
                logger.info("  [SKIP] %s — kein Trade in letzten 4h",
                            w.get("username", w["address"][:12]))
                time.sleep(0.3)
                continue
            logger.info("  [WARN] %s — kein Trade in 20 Min, aber aktiv in 4h",
                        w.get("username", w["address"][:12]))

        # Recency-Score: wie lange ist der letzte Trade her?
        if recent:
            latest_ts = max(t["timestamp"] for t in recent)
            hours_ago = (now_ts - latest_ts) / 3600
            recency_score = max(0.0, 1.0 - hours_ago / 2)  # 1.0 = gerade eben, 0 = > 2h
        else:
            recency_score = 0.0
        w["recency_score"] = recency_score

        # Single-Trade-Dominanz-Filter: wenn 1 Trade > 80% des Gesamt-PnL → Glueck, kein Edge
        try:
            r_closed = requests.get(f"{DATA_API}/positions",
                params={"user": w["address"], "sizeThreshold": "0", "limit": 500,
                        "offset": 0, "sortBy": "CLOSED_TIME", "endDateMin": "2020-01-01"},
                timeout=15)
            if r_closed.ok:
                raw_closed = r_closed.json()
                pnls = [float(p.get("realizedPnl") or 0) for p in raw_closed]
                total_pnl = sum(p for p in pnls if p > 0)
                max_pnl = max(pnls) if pnls else 0
                if total_pnl > 0 and max_pnl / total_pnl > 0.80:
                    logger.warning("  [SKIP] %s — Single-Trade-Dominanz: ein Trade = %.0f%% des Gesamt-PnL",
                                   w.get("username", w["address"][:12]),
                                   (max_pnl / total_pnl) * 100)
                    time.sleep(0.3)
                    continue
        except Exception:
            pass

        # Bot-Detection: verdächtig gleichmäßige Trade-Größen → automatisierter Bot
        sizes = [t.get("usdc_size", 0) for t in recent if t.get("usdc_size", 0) > 0]
        if len(sizes) >= 10:
            mean_size = sum(sizes) / len(sizes)
            variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes)
            std_dev = variance ** 0.5
            cv = std_dev / mean_size if mean_size > 0 else 1.0  # Variationskoeffizient
            if cv < 0.05:  # < 5% Abweichung → alle Trades fast identisch → Bot
                logger.warning("  [SKIP] %s — Bot-Verdacht: Trade-Groessen CV=%.1f%% (< 5%%) = automatisiert",
                               w.get("username", w["address"][:12]), cv * 100)
                time.sleep(0.3)
                continue

        # Domain-Erkennung: In welcher Kategorie ist dieser Trader am stärksten?
        questions = [t["market_question"] for t in recent if t.get("market_question")]
        w["domain"] = _detect_domain(questions)

        candidates.append(w)
        logger.info("  Kandidat: %s | ROI=%.2f%% | PnL=$%s | WR=%.0f%% | Domain=%s | zuletzt=%.1fh",
                    w.get("username", w["address"][:12]),
                    w["roi"] * 100, f'{w["pnl"]:,.0f}',
                    w["win_rate"], w["domain"], hours_ago if recent else 99)
        time.sleep(0.3)

    # Sortierung: ROI × (1 + Recency-Bonus) — aktive Trader bekommen Vorrang
    candidates.sort(key=lambda x: x["roi"] * (1 + x.get("recency_score", 0) * 0.3), reverse=True)

    top = candidates[:count]

    if not top:
        logger.warning("Auto-Follow: Keine qualifizierten Trader gefunden!")
        return []

    # Unfollow all, then follow new top traders
    # Merken welche Wallets bereits gefolgt wurden (haben schon Baseline + Timestamp)
    already_followed = {w["address"] for w in db.get_followed_wallets()}
    db.unfollow_all()
    for w in top:
        wallet_data = {
            "address": w["address"],
            "username": w.get("username", ""),
            "rank": w.get("rank", 0),
            "volume": w.get("volume", 0),
            "pnl": w.get("pnl", 0),
            "markets_traded": w.get("markets_traded", 0),
            "score": 0,
            "strategy_type": w.get("domain", "General"),
            "strengths": f"ROI: {w['roi']*100:.1f}%, WR: {w['win_rate']:.0f}%, Domain: {w.get('domain','?')}",
            "weaknesses": "",
            "recommendation": "COPY",
            "reasoning": f"Auto-Follow: Top ROI Trader (ROI={w['roi']*100:.1f}%)",
            "win_rate": w.get("win_rate", 0),
            "total_trades": w.get("total_trades", 0),
            "profile_url": w.get("profile_url", ""),
        }
        db.upsert_wallet(wallet_data)
        db.toggle_follow(w["address"], 1)
        # Baseline nur fuer NEUE Wallets zuruecksetzen — bekannte behalten ihren Timestamp
        if w["address"] not in already_followed:
            db.set_wallet_unbaselined(w["address"])
            logger.info("  [NEU] %s — wird frisch ge-baselined", w.get("username", w["address"][:12]))

    logger.info("Auto-Follow: Jetzt folge ich %d Top-Tradern:", len(top))
    for i, w in enumerate(top, 1):
        logger.info("  #%d %s | ROI=%.2f%% | PnL=$%s",
                    i, w.get("username", w["address"][:12]),
                    w["roi"] * 100, f'{w["pnl"]:,.0f}')

    return top
