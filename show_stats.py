"""
View Current Position Statistics
Shows: Open Trades, Closed Trades, Latest Trades, P&L, etc.

Usage:
    python show_stats.py
"""
import sys
import os
import logging
from datetime import datetime, timedelta

# Fix Windows encoding issues with emoji
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

import config
from database.db import init_db, get_copy_trade_stats, get_open_copy_trades, get_all_copy_trades, get_followed_wallets
from bot.copy_trader import get_copy_portfolio_summary

# Logging
os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def format_currency(amount):
    """Format amount as currency."""
    return f"${amount:.2f}"


def format_percent(value, total):
    """Format as percentage."""
    if total == 0:
        return "0.0%"
    return f"{(value/total)*100:.1f}%"


def show_portfolio_summary():
    """Show portfolio overview."""
    print("\n" + "=" * 80)
    print("[*] POSITION PORTFOLIO SUMMARY")
    print("=" * 80)
    
    summary = get_copy_portfolio_summary()
    
    print(f"\n[+] BALANCE & VALUE:")
    print(f"  Starting Balance:       {format_currency(summary['starting_balance'])}")
    print(f"  Current Cash:           {format_currency(summary['cash_balance'])}")
    print(f"  Total Invested:         {format_currency(summary['total_invested'])}")
    print(f"  Total Portfolio Value:  {format_currency(summary['total_value'])}")
    print(f"\n[+] PROFIT & LOSS:")
    print(f"  Realized P&L:           {format_currency(summary['realized_pnl'])}")
    print(f"  Unrealized P&L:         {format_currency(summary['unrealized_pnl'])}")
    print(f"  Total P&L:              {format_currency(summary['total_pnl'])}")
    print(f"  Daily P&L:              {format_currency(summary['daily_pnl'])}")
    print(f"\n[+] POSITIONS:")
    print(f"  Open Trades:            {summary['open_trades']}")
    print(f"  Closed Trades:          {summary['closed_trades']}")
    print(f"  Total Trades:           {summary['total_trades']}")
    print(f"  Wins:                   {summary['wins']} ({summary['win_rate']:.1f}%)")
    if summary['max_profit_if_win'] > 0:
        print(f"  Max Profit If All Win:  {format_currency(summary['max_profit_if_win'])}")
        print(f"  Max Total If All Win:   {format_currency(summary['max_total_if_win'])}")


def show_open_trades():
    """Show all open trades."""
    open_trades = get_open_copy_trades()
    
    if not open_trades:
        print("\n[-] No open trades")
        return
    
    print("\n" + "=" * 80)
    print(f"[>] OPEN TRADES ({len(open_trades)})")
    print("=" * 80)
    
    if not HAS_TABULATE:
        for t in open_trades:
            pnl_pct = ((t["current_price"] or t["entry_price"]) - t["entry_price"]) / t["entry_price"] * 100 if t["entry_price"] > 0 else 0
            print(f"  #{t['id']} {t['wallet_username'][:15]} | {t['market_question'][:40]}")
            print(f"    {t['side']} @ {t['entry_price']*100:.0f}c -> {(t['current_price'] or t['entry_price'])*100:.0f}c | Size: {format_currency(t['size'])} | P&L: {format_currency(t['pnl_unrealized'] or 0)} ({pnl_pct:+.1f}%)")
        return
    
    table_data = []
    for t in open_trades:
        pnl_pct = ((t["current_price"] or t["entry_price"]) - t["entry_price"]) / t["entry_price"] * 100 if t["entry_price"] > 0 else 0
        table_data.append([
            t["id"],
            t["wallet_username"][:15],
            t["market_question"][:40],
            t["side"],
            f"{t['entry_price']*100:.0f}c",
            f"{(t['current_price'] or t['entry_price'])*100:.0f}c",
            format_currency(t["size"]),
            format_currency(t["pnl_unrealized"] or 0),
            f"{pnl_pct:+.1f}%",
        ])
    
    headers = ["ID", "Trader", "Market", "Side", "Entry", "Current", "Size", "P&L", "Ret%"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))


def show_recent_closed():
    """Show recently closed trades."""
    all_trades = get_all_copy_trades(limit=100)
    closed = [t for t in all_trades if t["status"] == "closed"][:20]
    
    if not closed:
        print("\n[-] No closed trades")
        return
    
    print("\n" + "=" * 80)
    print(f"[X] RECENTLY CLOSED TRADES (Last {len(closed)})")
    print("=" * 80)
    
    if not HAS_TABULATE:
        for t in closed:
            pnl_pct = (t["pnl_realized"] / t["size"] * 100) if t["size"] > 0 else 0
            print(f"  #{t['id']} {t['wallet_username'][:15]} | {t['market_question'][:40]}")
            print(f"    {t['side']} @ {t['entry_price']*100:.0f}c | Size: {format_currency(t['size'])} | P&L: {format_currency(t['pnl_realized'] or 0)} ({pnl_pct:+.1f}%) | {t['closed_at'][:10] if t['closed_at'] else 'N/A'}")
        return
    
    table_data = []
    for t in closed:
        pnl_pct = (t["pnl_realized"] / t["size"] * 100) if t["size"] > 0 else 0
        table_data.append([
            t["id"],
            t["wallet_username"][:15],
            t["market_question"][:40],
            t["side"],
            f"{t['entry_price']*100:.0f}c",
            format_currency(t["size"]),
            format_currency(t["pnl_realized"] or 0),
            f"{pnl_pct:+.1f}%",
            t["closed_at"][:10] if t["closed_at"] else "N/A",
        ])
    
    headers = ["ID", "Trader", "Market", "Side", "Entry", "Size", "P&L", "Ret%", "Closed"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))


def show_followed_wallets():
    """Show followed wallets."""
    followed = list(get_followed_wallets())
    
    if not followed:
        print("\n[-] No followed wallets")
        return
    
    print("\n" + "=" * 80)
    print(f"[*] FOLLOWED WALLETS ({len(followed)})")
    print("=" * 80)
    
    if not HAS_TABULATE:
        for w in followed:
            print(f"  {w['username'][:20]} ({w['address'][:12]}...)")
            print(f"    PnL: {format_currency(w['pnl'])} | ROI: {w['roi']*100:.1f}% | Markets: {w['markets_traded']} | Win%: {w['win_rate']:.0f}%")
        return
    
    table_data = []
    for w in followed:
        table_data.append([
            w["username"][:20],
            w["address"][:12] + "...",
            format_currency(w["pnl"]),
            f"{w['roi']*100:.1f}%",
            w["markets_traded"],
            f"{w['win_rate']:.0f}%",
        ])
    
    headers = ["Username", "Address", "PnL", "ROI", "Markets", "Win%"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))


def main():
    """Show all statistics."""
    init_db()
    
    print(f"\n[TIME] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not HAS_TABULATE:
        print("\n[NOTE] Install 'tabulate' for better formatting: pip install tabulate")
    
    show_portfolio_summary()
    show_followed_wallets()
    show_open_trades()
    show_recent_closed()
    
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
