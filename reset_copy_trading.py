"""
Reset Copy Trading System
Vollständiger Neustart: Löscht alle offenen Trades, geschlossenen Trades,
Snapshots und Baselines. Portfolio wird auf $100 zurückgesetzt.

Usage:
    python reset_copy_trading.py
"""
import logging
import sys
import os
from datetime import datetime

import config
from database.db import init_db, reset_copy_trading, get_copy_trade_stats, get_followed_wallets

# Logging
os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("reset-copy-trading")


def reset_system():
    """Full reset of copy trading system."""
    logger.info("=" * 70)
    logger.info("🔄 COPY TRADING SYSTEM RESET")
    logger.info("=" * 70)
    
    # Ask for confirmation
    print("\n⚠️  Diese Aktion wird ALLES löschen:")
    print("   ✓ Alle offenen Trades")
    print("   ✓ Alle geschlossenen Trades und P&L History")
    print("   ✓ Alle Position-Snapshots")
    print("   ✓ Alle Baselines (müssen neu gescannt werden)")
    print("\n   BEHALTEN:")
    print("   ✓ Gefollte Wallets (Follow-Status bleibt)")
    print("   ✓ Portfolio startet bei $200 neu")
    print()
    
    response = input("Bestätige mit 'RESET' zum Fortfahren: ").strip().upper()
    if response != "RESET":
        logger.info("❌ Reset abgebrochen.")
        return
    
    # Initialize DB first
    init_db()
    
    # Get stats before reset
    before_stats = get_copy_trade_stats()
    followed = list(get_followed_wallets())
    
    logger.info("\n📊 BEFORE RESET:")
    logger.info("   Open Trades:   %d", before_stats["open_trades"])
    logger.info("   Closed Trades: %d", before_stats["closed_trades"])
    logger.info("   Total P&L:     $%.2f", before_stats["total_pnl"])
    logger.info("   Followed:      %d wallets", len(followed))
    
    # Reset
    logger.info("\n🔄 Resetting...")
    reset_copy_trading()
    logger.info("✅ Reset complete!")
    
    # Get stats after reset
    after_stats = get_copy_trade_stats()
    
    logger.info("\n📊 AFTER RESET:")
    logger.info("   Open Trades:   %d", after_stats["open_trades"])
    logger.info("   Closed Trades: %d", after_stats["closed_trades"])
    logger.info("   Total P&L:     $%.2f", after_stats["total_pnl"])
    logger.info("   Followed:      %d wallets", len(followed))
    
    logger.info("\n" + "=" * 70)
    logger.info("✨ System ready for fresh copy trading!")
    logger.info("   Next: Run the scheduler or scan manually")
    logger.info("=" * 70)


if __name__ == "__main__":
    reset_system()
