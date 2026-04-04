"""
Polymarket Wallet Scanner & Analyzer
Scannt Top-Wallets, analysiert sie mit AI, generiert HTML-Reports.

Nutzung:
    python scan_wallets.py                  # Standard: 500 Wallets scannen
    python scan_wallets.py --limit 100      # Nur 100 Wallets scannen
    python scan_wallets.py --analyze 30     # Top 30 analysieren (statt 50)
"""
import argparse
import logging
import os
import sys
import webbrowser

import config
from database.db import init_db, upsert_wallet, save_scan
from bot.wallet_scanner import fetch_leaderboard_wallets, filter_wallets
from bot.wallet_analyzer import analyze_wallets_batch
from bot.report_generator import generate_report

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
logger = logging.getLogger("wallet-scanner")


def run_scan(limit=500, max_analyze=50, top_n=10, open_report=True):
    """Run a full wallet scan cycle."""
    logger.info("=" * 60)
    logger.info("Polymarket Wallet Scanner starting...")
    logger.info("Scanning %d wallets, analyzing top %d, reporting top %d",
                limit, max_analyze, top_n)
    logger.info("=" * 60)

    # 1. Fetch wallets from leaderboard
    wallets = fetch_leaderboard_wallets(limit=limit)
    if not wallets:
        logger.error("No wallets found. Exiting.")
        return None

    # 2. Filter wallets
    filtered = filter_wallets(wallets)
    if not filtered:
        logger.error("No wallets passed filters. Exiting.")
        return None

    logger.info("%d wallets passed filters out of %d scanned.", len(filtered), len(wallets))

    # 3. Analyze with AI
    logger.info("Starting AI analysis of top %d wallets...", max_analyze)
    analyzed = analyze_wallets_batch(filtered, max_analyze=max_analyze)

    if not analyzed:
        logger.error("No wallets were successfully analyzed. Exiting.")
        return None

    # 4. Save to database
    for w in analyzed:
        upsert_wallet(w)

    # 5. Generate report
    report_path = generate_report(analyzed, source="leaderboard", top_n=top_n)

    # 6. Save scan history
    save_scan({
        "wallets_scanned": len(wallets),
        "wallets_filtered": len(filtered),
        "wallets_analyzed": len(analyzed),
        "top_score": analyzed[0]["score"] if analyzed else 0,
        "report_path": report_path,
    })

    logger.info("=" * 60)
    logger.info("SCAN COMPLETE!")
    logger.info("Scanned: %d | Filtered: %d | Analyzed: %d", len(wallets), len(filtered), len(analyzed))
    logger.info("Report: %s", report_path)
    logger.info("=" * 60)

    # Print top 3 to console
    print("\n" + "=" * 60)
    print("TOP 3 WALLETS:")
    print("=" * 60)
    for i, w in enumerate(analyzed[:3], 1):
        name = w["username"] or w["address"][:12]
        print(f"\n#{i} | {name} | Score: {w['score']}/10 | {w['recommendation']}")
        print(f"   PnL: ${w['pnl']:,.2f} | Win Rate: {w['win_rate']}% | Strategy: {w['strategy_type']}")
        print(f"   Address: {w['address']}")
        print(f"   {w['reasoning']}")
    print("\n" + "=" * 60)

    # Open report in browser
    if open_report:
        webbrowser.open(f"file:///{os.path.abspath(report_path)}")
        print(f"\nReport opened in browser: {report_path}")

    return report_path


def main():
    parser = argparse.ArgumentParser(description="Polymarket Wallet Scanner & Analyzer")
    parser.add_argument("--limit", type=int, default=config.SCAN_WALLET_LIMIT,
                        help=f"Wallets to scan from leaderboard (default: {config.SCAN_WALLET_LIMIT})")
    parser.add_argument("--analyze", type=int, default=config.MAX_AI_ANALYSES,
                        help=f"Max wallets to analyze with AI (default: {config.MAX_AI_ANALYSES})")
    parser.add_argument("--top", type=int, default=config.TOP_N_REPORT,
                        help=f"Top N wallets in report (default: {config.TOP_N_REPORT})")
    parser.add_argument("--no-open", action="store_true", help="Don't open report in browser")
    args = parser.parse_args()

    init_db()
    run_scan(
        limit=args.limit,
        max_analyze=args.analyze,
        top_n=args.top,
        open_report=not args.no_open,
    )


if __name__ == "__main__":
    main()
