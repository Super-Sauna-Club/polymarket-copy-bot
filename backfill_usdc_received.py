#!/usr/bin/env python3
"""
Backfill usdc_received for historical copy_trades where the close flow left
it NULL. Pulls our wallet's real trade activity from Polymarket's data-api
/activity endpoint, matches each NULL row to the closing SELL event by
(condition_id, side) + closed_at proximity, and writes capital-verified
pnl_realized / usdc_received back to the DB.

Why this exists:
  87% of recent closes have usdc_received=NULL. Brain, ML, and the Trade
  Scorer all read pnl_realized as ground truth, so every downstream decision
  is trained on formula-computed garbage labels. Backfilling from real fills
  gives us clean data without touching any production code path.

Run modes:
  --dry-run (default): preview updates, touch nothing
  --apply           : write corrections to the DB
  --limit N         : process at most N NULL rows (for quick sanity checks)
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from database import db  # noqa: E402

logger = logging.getLogger("backfill")

DATA_API = "https://data-api.polymarket.com"
PAGE_LIMIT = 500
RATE_SLEEP = 0.25  # seconds between pages

# Match window: sells within +/- this many seconds of closed_at are preferred
# over anything further away. 6 hours is wide enough to absorb the auto-close
# detection lag without being so wide it matches unrelated sells.
MATCH_WINDOW_SECS = 6 * 3600


def fetch_all_activity(wallet: str, event_type: str) -> list:
    """Paginate through /activity?user=X&type=Y until an empty page is returned.

    The data-api accepts `offset` in multiples of `limit`; we walk until a page
    comes back shorter than PAGE_LIMIT, which is the natural end-of-stream
    signal. Rate-limited with a short sleep between pages.
    """
    out = []
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{DATA_API}/activity",
                params={
                    "user": wallet,
                    "type": event_type,
                    "limit": PAGE_LIMIT,
                    "offset": offset,
                },
                timeout=25,
            )
            r.raise_for_status()
            page = r.json() or []
        except Exception as e:
            logger.warning("activity fetch failed (type=%s offset=%d): %s", event_type, offset, e)
            break
        if not page:
            break
        out.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(RATE_SLEEP)
    logger.info("fetched %d %s events for %s", len(out), event_type, wallet[:10])
    return out


def _norm_side(outcome: str) -> str:
    s = (outcome or "").strip().upper()
    if s.startswith("Y"):
        return "YES"
    if s.startswith("N"):
        return "NO"
    return s


def build_sell_index(trade_events: list) -> dict:
    """Map (condition_id, YES|NO) -> sorted-by-timestamp list of SELL fills."""
    idx = {}
    for e in trade_events:
        if (e.get("side") or "").upper() != "SELL":
            continue
        cid = e.get("conditionId") or ""
        if not cid:
            continue
        tok = _norm_side(e.get("outcome") or "")
        key = (cid, tok)
        idx.setdefault(key, []).append(e)
    for key in idx:
        idx[key].sort(key=lambda ev: int(ev.get("timestamp") or 0))
    return idx


def build_redemption_index(redemption_events: list) -> dict:
    """Map condition_id -> list of redemption events (payout on market resolve)."""
    idx = {}
    for e in redemption_events:
        cid = e.get("conditionId") or ""
        if not cid:
            continue
        idx.setdefault(cid, []).append(e)
    return idx


def closest_sell(sells: list, closed_ts: int):
    """Pick the sell event closest to closed_ts. Ties go to the one after closed_ts
    (closed_at is written AFTER the sell lands, so sell.ts ≤ closed_at is normal)."""
    if not sells:
        return None
    best = None
    best_delta = None
    for ev in sells:
        ts = int(ev.get("timestamp") or 0)
        delta = abs(ts - closed_ts)
        if best_delta is None or delta < best_delta:
            best = ev
            best_delta = delta
    return best, best_delta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write updates to DB (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="process at most N NULL rows")
    ap.add_argument("--wallet", default=None, help="override wallet address (default: POLYMARKET_FUNDER)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    wallet = (args.wallet or config.POLYMARKET_FUNDER or "").strip().lower()
    if not wallet:
        logger.error("POLYMARKET_FUNDER not set and no --wallet provided")
        sys.exit(1)
    logger.info("wallet=%s apply=%s", wallet, args.apply)

    trades = fetch_all_activity(wallet, "TRADE")
    redemptions = fetch_all_activity(wallet, "REDEMPTION")
    sell_idx = build_sell_index(trades)
    redeem_idx = build_redemption_index(redemptions)
    logger.info("indexed %d sell buckets, %d redemption markets", len(sell_idx), len(redeem_idx))

    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT id, condition_id, side, actual_size, size, pnl_realized,
                   closed_at, current_price, wallet_username, market_question
            FROM copy_trades
            WHERE status='closed' AND usdc_received IS NULL AND condition_id != ''
            ORDER BY closed_at ASC
        """).fetchall()
    logger.info("found %d NULL rows to process", len(rows))

    if args.limit > 0:
        rows = rows[:args.limit]
        logger.info("limited to first %d", len(rows))

    # Group NULL rows by (cid, side). When multiple NULL rows share a bucket
    # we MUST assign 1:1 to distinct sell events — otherwise the closest-ts
    # heuristic attributes the same fill to every row, massively overcounting.
    # Strategy: sort rows and sells by time, then greedy-pair by nearest next
    # available sell. Rows without a remaining sell fall through to redemption
    # lookup.
    null_by_key = {}
    row_closed_ts = {}
    for r in rows:
        cid = r["condition_id"]
        side = _norm_side(r["side"])
        cost = float(r["actual_size"] or r["size"] or 0)
        try:
            closed_ts = int(datetime.strptime(r["closed_at"][:19], "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception:
            closed_ts = 0
        row_closed_ts[r["id"]] = closed_ts
        if cost <= 0:
            continue
        null_by_key.setdefault((cid, side), []).append(r)

    stats = {
        "matched_sell_in_window": 0,
        "matched_sell_loose": 0,
        "matched_redemption": 0,
        "no_cid_match": 0,
        "no_cost_basis": 0,
        "bucket_overflow": 0,
    }
    updates = []
    row_match = {}  # row_id -> (pnl, usdc, via, tx, delta_s) or None
    for r in rows:
        cost = float(r["actual_size"] or r["size"] or 0)
        if cost <= 0:
            stats["no_cost_basis"] += 1

    # First pass: 1:1 greedy matching within each (cid, side) bucket, oldest
    # rows paired with oldest sells. For each row assign the CLOSEST remaining
    # sell event — this preserves locality while guaranteeing no double-use.
    for key, bucket_rows in null_by_key.items():
        sells = list(sell_idx.get(key, []))  # already sorted ASC by ts
        if not sells:
            continue
        available = sells[:]  # shallow copy so we can pop
        # Sort rows by closed_at asc (matches sell ts order)
        bucket_rows.sort(key=lambda rr: row_closed_ts.get(rr["id"], 0))
        for r in bucket_rows:
            if not available:
                stats["bucket_overflow"] += 1
                break
            closed_ts = row_closed_ts.get(r["id"], 0)
            # Pick nearest remaining sell by timestamp
            idx_best = 0
            best_delta = abs(int(available[0].get("timestamp") or 0) - closed_ts)
            for i in range(1, len(available)):
                d = abs(int(available[i].get("timestamp") or 0) - closed_ts)
                if d < best_delta:
                    best_delta = d
                    idx_best = i
            ev = available.pop(idx_best)
            fill = float(ev.get("usdcSize") or 0)
            cost = float(r["actual_size"] or r["size"] or 0)
            pnl = round(fill - cost, 4)
            row_match[r["id"]] = {
                "id": r["id"],
                "pnl": pnl,
                "usdc": round(fill, 4),
                "via": "sell" + ("_window" if best_delta <= MATCH_WINDOW_SECS else "_loose"),
                "tx": (ev.get("transactionHash") or "")[:12],
                "delta_s": best_delta,
                "trader": r["wallet_username"] or "",
                "market": (r["market_question"] or "")[:40],
            }
            if best_delta <= MATCH_WINDOW_SECS:
                stats["matched_sell_in_window"] += 1
            else:
                stats["matched_sell_loose"] += 1

    # Second pass: rows still unmatched try redemption (then give up)
    for r in rows:
        rid = r["id"]
        if rid in row_match:
            updates.append(row_match[rid])
            continue
        cost = float(r["actual_size"] or r["size"] or 0)
        if cost <= 0:
            continue
        cid = r["condition_id"]
        reds = redeem_idx.get(cid, [])
        if reds:
            # Try multiple payout field names — Polymarket's activity schema
            # has evolved and the field isn't always "payout".
            red = reds[0]
            payout = 0.0
            for k in ("payout", "usdcSize", "amount", "value"):
                v = red.get(k)
                if v:
                    try:
                        payout = float(v)
                        break
                    except Exception:
                        pass
            if payout > 0:
                updates.append({
                    "id": r["id"],
                    "pnl": round(payout - cost, 4),
                    "usdc": round(payout, 4),
                    "via": "redeem",
                    "tx": (red.get("transactionHash") or "")[:12],
                    "delta_s": 0,
                    "trader": r["wallet_username"] or "",
                    "market": (r["market_question"] or "")[:40],
                })
                stats["matched_redemption"] += 1
                continue

        stats["no_cid_match"] += 1

    logger.info("match stats: %s", stats)
    logger.info("total updates to apply: %d", len(updates))

    # Preview: show the first 15 and a summary by trader.
    for u in updates[:15]:
        logger.info("  row %d  %s  pnl=%+.2f  usdc=%.2f  via=%s  dt=%ds  %s %s",
                    u["id"], u["trader"][:12], u["pnl"], u["usdc"],
                    u["via"], u["delta_s"], u["market"], u["tx"])

    by_trader = {}
    for u in updates:
        t = u["trader"] or "unknown"
        b = by_trader.setdefault(t, {"n": 0, "pnl_before": 0.0, "pnl_after": 0.0})
        b["n"] += 1
        b["pnl_after"] += u["pnl"]
    logger.info("── per-trader summary (post-backfill) ──")
    for t, b in sorted(by_trader.items(), key=lambda kv: -kv[1]["n"])[:20]:
        logger.info("  %-20s n=%-4d  new_pnl=%+.2f", t[:20], b["n"], b["pnl_after"])

    if not args.apply:
        logger.info("DRY-RUN complete. Pass --apply to write %d updates.", len(updates))
        return

    with db.get_connection() as conn:
        n = 0
        for u in updates:
            conn.execute(
                "UPDATE copy_trades SET pnl_realized=?, usdc_received=? WHERE id=?",
                (u["pnl"], u["usdc"], u["id"]),
            )
            n += 1
    logger.info("WROTE %d updates to DB", n)


if __name__ == "__main__":
    main()
