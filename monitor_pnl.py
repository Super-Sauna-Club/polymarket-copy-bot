#!/usr/bin/env python3
"""
P&L Accuracy Monitor — runs for 7 hours, logs everything every 5 minutes.
Compares DB values with API, tracks new fills, verifies actual_entry_price.
"""
import sqlite3
import time
import json
import os
import requests
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "scanner.db")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "pnl_monitor.log")
CLOB_URL = "https://clob.polymarket.com"
WALLET = "0x53fe4db3f74dd80f5263e0fc25ff22e347be0485"
DATA_API = "https://data-api.polymarket.com"

DURATION_HOURS = 0  # 0 = run forever
INTERVAL_SECS = 5  # same as bot scan interval
API_CHECK_EVERY = 60  # full API/wallet check every 60s (rate-limit friendly)

# Track state between checks
_last_trade_count = 0
_last_closed_count = 0
_seen_fills = set()
_seen_closes = set()  # track close IDs to detect new ones for accuracy check


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def check_wallet_balance():
    """Get actual USDC balance from Polymarket positions API."""
    try:
        r = requests.get(f"{DATA_API}/positions",
                         params={"user": WALLET, "sizeThreshold": "0.01",
                                 "limit": "500"},
                         timeout=10)
        if not r.ok:
            return None, None, None, []
        positions = r.json()
        total_value = sum(float(p.get("currentValue", 0)) for p in positions)
        total_invested = sum(float(p.get("initialValue", 0)) for p in positions)
        return total_value, total_invested, len(positions), positions
    except Exception as e:
        log(f"  [ERROR] Positions API: {e}")
        return None, None, None, []


def get_clob_price(condition_id, side):
    """Get live CLOB price for a market."""
    try:
        r = requests.get(f"{CLOB_URL}/price",
                         params={"token_id": condition_id, "side": side.upper()},
                         timeout=5)
        if r.ok:
            data = r.json()
            return float(data.get("price", 0))
    except Exception:
        pass
    return None


def get_usdc_balance():
    """Get wallet USDC balance from dashboard API."""
    try:
        r = requests.get("http://127.0.0.1:8090/api/live-data", timeout=10)
        if r.ok:
            data = r.json()
            return data.get("summary", {}).get("wallet_usdc", 0)
    except Exception:
        pass
    return None


def check_db_stats():
    """Get all stats from DB."""
    conn = get_db()
    try:
        # Overall stats
        total = conn.execute("SELECT COUNT(*) FROM copy_trades WHERE status != 'baseline'").fetchone()[0]
        open_ct = conn.execute("SELECT COUNT(*) FROM copy_trades WHERE status='open'").fetchone()[0]
        closed_ct = conn.execute("SELECT COUNT(*) FROM copy_trades WHERE status='closed'").fetchone()[0]

        # P&L from DB
        pnl_realized = conn.execute(
            "SELECT COALESCE(SUM(pnl_realized), 0) FROM copy_trades WHERE status='closed'"
        ).fetchone()[0]
        pnl_unrealized = conn.execute(
            "SELECT COALESCE(SUM(pnl_unrealized), 0) FROM copy_trades WHERE status='open'"
        ).fetchone()[0]
        total_invested = conn.execute(
            "SELECT COALESCE(SUM(size), 0) FROM copy_trades WHERE status='open'"
        ).fetchone()[0]

        # Trades with actual fill data
        has_actual = conn.execute(
            "SELECT COUNT(*) FROM copy_trades WHERE actual_entry_price IS NOT NULL"
        ).fetchone()[0]

        # Wins/losses
        wins = conn.execute(
            "SELECT COUNT(*) FROM copy_trades WHERE status='closed' AND pnl_realized > 0"
        ).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM copy_trades WHERE status='closed' AND pnl_realized <= 0"
        ).fetchone()[0]

        return {
            "total": total, "open": open_ct, "closed": closed_ct,
            "pnl_realized": round(pnl_realized, 2),
            "pnl_unrealized": round(pnl_unrealized, 2),
            "total_invested": round(total_invested, 2),
            "has_actual": has_actual,
            "wins": wins, "losses": losses,
        }
    finally:
        conn.close()


def check_new_fills():
    """Check for trades with actual_entry_price filled (new fills since deploy)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, wallet_username, market_question, side,
                   entry_price, actual_entry_price, size, actual_size,
                   shares_held, status, created_at
            FROM copy_trades
            WHERE actual_entry_price IS NOT NULL
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_recent_closes():
    """Check recently closed trades for P&L accuracy."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, wallet_username, market_question, side,
                   entry_price, actual_entry_price, size, actual_size,
                   pnl_realized, usdc_received, current_price, closed_at
            FROM copy_trades
            WHERE status='closed' AND closed_at >= datetime('now', '-6 hours', 'localtime')
            ORDER BY closed_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_close_accuracy():
    """ALARM: compare DB pnl_realized vs real USDC delta for NEW closes.
    Flags any close where DB P&L deviates >$0.50 from real USDC-based P&L.
    """
    global _seen_closes
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, wallet_username, market_question, side,
                   entry_price, actual_entry_price, size, actual_size,
                   pnl_realized, usdc_received, current_price, closed_at
            FROM copy_trades
            WHERE status='closed' AND closed_at >= datetime('now', '-1 hour', 'localtime')
            ORDER BY closed_at DESC
        """).fetchall()
        for r in rows:
            r = dict(r)
            if r['id'] in _seen_closes:
                continue
            _seen_closes.add(r['id'])
            # Only check trades that have actual fill data (= new trades with fixes)
            cost = r.get('actual_size') or r.get('size') or 0
            usdc_recv = r.get('usdc_received')
            db_pnl = r.get('pnl_realized') or 0
            if usdc_recv is not None and cost > 0:
                real_pnl = round(usdc_recv - cost, 2)
                diff = abs(db_pnl - real_pnl)
                if diff > 0.50:
                    log(f"  [PNL ALARM] #{r['id']} {r['wallet_username']} | DB_pnl=${db_pnl:.2f} vs real=${real_pnl:.2f} DIFF=${diff:.2f}!")
                    log(f"    cost=${cost:.2f} usdc_received=${usdc_recv:.2f} | {r['market_question'][:45]}")
                elif diff > 0.05:
                    log(f"  [PNL DRIFT] #{r['id']} {r['wallet_username']} | DB=${db_pnl:.2f} real=${real_pnl:.2f} diff=${diff:.2f}")
                else:
                    log(f"  [PNL OK] #{r['id']} {r['wallet_username']} | DB=${db_pnl:.2f} real=${real_pnl:.2f} | {r['market_question'][:35]}")
            elif r.get('actual_entry_price') is not None and usdc_recv is None:
                log(f"  [PNL WARN] #{r['id']} has actual_entry but NO usdc_received — sell may have failed")
    finally:
        conn.close()


def check_open_positions():
    """Get all open positions with their actual vs planned prices."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, wallet_username, market_question, side,
                   entry_price, actual_entry_price, size, actual_size,
                   shares_held, current_price, pnl_unrealized, condition_id
            FROM copy_trades
            WHERE status='open'
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_activity_log():
    """Get recent activity log entries."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT event_type, icon, title, detail, pnl, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 10
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def check_scanner_errors():
    """Check scanner.log for recent errors."""
    scanner_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "scanner.log")
    errors = []
    try:
        with open(scanner_log, "r") as f:
            lines = f.readlines()
        # Last 500 lines, look for errors
        for line in lines[-500:]:
            if any(x in line for x in ["ERROR", "FEHLER", "Traceback"]):
                errors.append(line.strip())
    except Exception:
        pass
    return errors[-5:] if errors else []


def check_fill_details_log():
    """Check scanner.log for FILL DETAILS and PNL-FIX entries."""
    scanner_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "scanner.log")
    fills = []
    try:
        with open(scanner_log, "r") as f:
            lines = f.readlines()
        for line in lines[-1000:]:
            if "FILL DETAILS" in line or "PNL-FIX" in line or "BUY FILLED" in line or "SELL FILL" in line:
                fills.append(line.strip())
    except Exception:
        pass
    return fills


def run_check(check_num, start_time):
    global _last_trade_count, _last_closed_count

    elapsed = (datetime.now() - start_time).total_seconds() / 3600
    full_check = (check_num == 1) or (check_num % (API_CHECK_EVERY // INTERVAL_SECS) == 0)

    # --- FAST CHECK (every 5s): DB changes, new fills, errors ---
    stats = check_db_stats()
    new_trades = stats['total'] - _last_trade_count if _last_trade_count > 0 else 0
    new_closes = stats['closed'] - _last_closed_count if _last_closed_count > 0 else 0

    # Only log if something changed or it's a full check
    if new_trades or new_closes or full_check:
        log(f"{'='*80}")
        log(f"CHECK #{check_num} | {elapsed:.1f}h/{DURATION_HOURS}h | {'FULL' if full_check else 'CHANGE DETECTED'}")
        log(f"{'='*80}")
        log(f"DB: {stats['total']} trades | {stats['open']} open | {stats['closed']} closed | "
            f"W:{stats['wins']} L:{stats['losses']} | actual_data:{stats['has_actual']}/{stats['total']}")
        log(f"  P&L R:${stats['pnl_realized']:.2f} U:${stats['pnl_unrealized']:.2f} | Invested:${stats['total_invested']:.2f}")

    if new_trades > 0:
        log(f"  >>> {new_trades} NEW TRADE(S)!")
    if new_closes > 0:
        log(f"  >>> {new_closes} NEW CLOSE(S)!")
        # Check P&L accuracy for new closes
        check_close_accuracy()

    _last_trade_count = stats['total']
    _last_closed_count = stats['closed']

    # Check for new fills (every tick — these are the important ones)
    fills = check_new_fills()
    for f in fills:
        if f['id'] not in _seen_fills:
            ep = f['entry_price']
            aep = f['actual_entry_price']
            sz = f['size']
            asz = f['actual_size']
            diff_price = ((aep - ep) / ep * 100) if ep > 0 and aep else 0
            diff_size = ((asz - sz) / sz * 100) if sz > 0 and asz else 0
            log(f"  [NEW FILL] #{f['id']} {f['wallet_username']} | {f['market_question'][:45]}")
            log(f"    Entry: planned={ep:.4f} actual={aep:.4f} ({diff_price:+.1f}%)")
            log(f"    Size:  planned=${sz:.2f} actual=${asz:.2f} ({diff_size:+.1f}%)")
            log(f"    Shares: {f['shares_held']}")
            _seen_fills.add(f['id'])

    # Check fill/pnl log lines from scanner (every tick)
    fill_logs = check_fill_details_log()
    if fill_logs:
        # Only show new ones (compare with last seen)
        for fl in fill_logs[-5:]:
            ts = fl[:19] if len(fl) > 19 else ""
            if ts > getattr(run_check, '_last_fill_ts', ''):
                log(f"  [SCANNER] {fl}")
        run_check._last_fill_ts = fill_logs[-1][:19] if fill_logs else ""

    # Check errors (every tick)
    errors = check_scanner_errors()
    if errors:
        for e in errors[-3:]:
            ts = e[:19] if len(e) > 19 else ""
            if ts > getattr(run_check, '_last_err_ts', ''):
                log(f"  [ERROR] {e}")
        run_check._last_err_ts = errors[-1][:19] if errors else ""

    # --- FULL CHECK (every 60s): API comparison, prices, discrepancy ---
    if not full_check:
        return

    # API Wallet Check + Live Prices
    api_value, api_invested, api_positions, api_raw = check_wallet_balance()
    usdc_cash = get_usdc_balance()
    if api_value is not None:
        _cash = usdc_cash or 0
        total_portfolio = _cash + api_value
        log(f"API WALLET: Cash=${_cash:.2f} | Positions=${api_value:.2f} | Total=${total_portfolio:.2f}")
        log(f"  API P&L: ${total_portfolio - 320:.2f} (total - $320 start)")

    # Recent closes with usdc_received check
    closes = check_recent_closes()
    if closes:
        # Only show trades with actual usdc_received data
        with_usdc = [c for c in closes if c['usdc_received'] is not None]
        if with_usdc:
            log(f"CLOSES WITH REAL USDC DATA ({len(with_usdc)}):")
            for c in with_usdc[:10]:
                ep = c.get('actual_entry_price') or c['entry_price']
                sz = c.get('actual_size') or c['size']
                formula_pnl = round((c['current_price'] - ep) * (sz / ep) if ep > 0 else 0, 2)
                real_pnl = round(c['usdc_received'] - sz, 2)
                log(f"  #{c['id']} {c['wallet_username']} | formula_pnl=${formula_pnl:.2f} real_pnl=${real_pnl:.2f} "
                    f"usdc_received=${c['usdc_received']:.2f} | DB_pnl=${c['pnl_realized']:.2f}")

    # Open positions — compare DB vs API live prices
    open_pos = check_open_positions()
    if open_pos:
        total_unrealized = sum(p['pnl_unrealized'] or 0 for p in open_pos)
        has_actual_open = sum(1 for p in open_pos if p.get('actual_entry_price'))
        log(f"OPEN: {len(open_pos)} | uP&L:${total_unrealized:.2f} | actual_data:{has_actual_open}/{len(open_pos)}")

        # Build API price lookup
        api_prices = {}
        if api_raw:
            for p in api_raw:
                cid = p.get("conditionId", "")
                if cid:
                    api_prices[cid] = float(p.get("curPrice", 0))

        # Flag big price mismatches
        mismatches = []
        for pos in open_pos:
            cid = pos.get("condition_id", "")
            db_cur = pos.get("current_price", 0) or 0
            api_p = api_prices.get(cid, 0)
            if api_p > 0 and db_cur > 0 and abs(api_p - db_cur) > 0.03:
                mismatches.append(f"#{pos['id']} {pos['wallet_username']} DB={db_cur:.2f} API={api_p:.2f} "
                                  f"Δ={abs(api_p-db_cur):.2f} | {pos['market_question'][:35]}")
        if mismatches:
            log(f"  PRICE GAPS (>3c):")
            for m in mismatches[:8]:
                log(f"    {m}")

    # Last activity
    activity = check_activity_log()
    if activity:
        log(f"LAST 3 EVENTS:")
        for a in activity[:3]:
            log(f"  {a['created_at']} {a['icon']} {a['detail'][:65]} P&L:${a['pnl']:.2f}")

    # Discrepancy
    if api_value is not None:
        real_total = (usdc_cash or 0) + api_value
        real_pnl = real_total - 320.0
        db_pnl = stats['pnl_realized'] + stats['pnl_unrealized']
        discrepancy = db_pnl - real_pnl
        log(f"DISCREPANCY: DB=${db_pnl:.2f} vs Real=${real_pnl:.2f} → gap=${discrepancy:+.2f}")

    log("")


def main():
    run_forever = DURATION_HOURS <= 0
    label = "forever" if run_forever else f"{DURATION_HOURS} hours"
    log(f"{'#'*80}")
    log(f"P&L MONITOR STARTED — Running {label}, checking every {INTERVAL_SECS}s (full every {API_CHECK_EVERY}s)")
    log(f"{'#'*80}")

    start_time = datetime.now()
    end_time = None if run_forever else start_time + timedelta(hours=DURATION_HOURS)
    check_num = 0

    while run_forever or datetime.now() < end_time:
        check_num += 1
        try:
            run_check(check_num, start_time)
        except Exception as e:
            log(f"CHECK #{check_num} FAILED: {e}")
            import traceback
            log(traceback.format_exc())

        time.sleep(INTERVAL_SECS)

    log(f"{'#'*80}")
    log(f"P&L MONITOR FINISHED after {DURATION_HOURS} hours, {check_num} checks")
    log(f"{'#'*80}")


if __name__ == "__main__":
    main()
