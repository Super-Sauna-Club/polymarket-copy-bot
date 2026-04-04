"""
Redeem resolved Polymarket positions via Builder Relayer.

Uses the Polymarket Relayer to execute redeemPositions through
the proxy wallet — no MATIC needed, Polymarket pays gas.

Requires Builder API credentials (get from polymarket.com/settings → Builder).

Usage:
    python redeem_positions.py          # dry run
    python redeem_positions.py --exec   # execute redemptions
"""
import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("redeem")


def main():
    parser = argparse.ArgumentParser(description="Redeem resolved Polymarket positions")
    parser.add_argument("--exec", action="store_true", help="Execute (default: dry run)")
    args = parser.parse_args()

    # Load config
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config

    if not config.POLYMARKET_PRIVATE_KEY:
        logger.error("POLYMARKET_PRIVATE_KEY not set!")
        return

    builder_key = os.getenv("BUILDER_KEY", "")
    builder_secret = os.getenv("BUILDER_SECRET", "")
    builder_passphrase = os.getenv("BUILDER_PASSPHRASE", "")

    if not all([builder_key, builder_secret, builder_passphrase]):
        logger.error("Builder API credentials not set!")
        logger.error("Go to polymarket.com/settings -> Builder -> Create New")
        logger.error("Then add to .env: BUILDER_KEY, BUILDER_SECRET, BUILDER_PASSPHRASE")
        return

    # Show what needs redeeming (dry run always)
    from bot.wallet_scanner import fetch_wallet_positions
    import requests

    funder = config.POLYMARKET_FUNDER
    positions = fetch_wallet_positions(funder)

    resolved = []
    for p in positions:
        cid = p.get("condition_id", "")
        if not cid:
            continue
        try:
            r = requests.get("https://gamma-api.polymarket.com/markets",
                             params={"conditionId": cid}, timeout=5)
            if r.ok and r.json():
                m = r.json()[0]
                if m.get("closed") or m.get("resolved"):
                    resolved.append(p)
        except Exception:
            continue

    if not resolved:
        logger.info("No resolved positions to redeem!")
        return

    total = sum(p.get("size", 0) for p in resolved)
    logger.info("Found %d resolved positions (total value: $%.2f):", len(resolved), total)
    for p in resolved:
        logger.info("  $%.2f | %s | %s", p.get("size", 0), p["side"],
                     (p.get("market_question") or "")[:50])

    if not args.exec:
        logger.info("DRY RUN — use --exec to redeem")
        return

    # Execute via poly-web3 Relayer
    logger.info("Connecting to Polymarket Relayer...")

    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON
    from py_builder_relayer_client.client import RelayClient
    from py_builder_signing_sdk.config import BuilderConfig
    from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
    from poly_web3 import RELAYER_URL, PolyWeb3Service

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=config.POLYMARKET_PRIVATE_KEY,
        chain_id=POLYGON,
        signature_type=1,
        funder=config.POLYMARKET_FUNDER,
    )
    client.set_api_creds(client.create_or_derive_api_creds())

    relayer_client = RelayClient(
        RELAYER_URL, POLYGON, config.POLYMARKET_PRIVATE_KEY,
        BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
            key=builder_key,
            secret=builder_secret,
            passphrase=builder_passphrase,
        )),
    )

    service = PolyWeb3Service(
        clob_client=client,
        relayer_client=relayer_client,
        rpc_url="https://polygon-bor-rpc.publicnode.com",
    )

    # Balance before
    from bot.order_executor import get_wallet_balance
    bal_before = get_wallet_balance()

    logger.info("Redeeming all resolved positions...")
    try:
        result = service.redeem_all(batch_size=10)
        logger.info("Redeem result: %s", result)
    except Exception as e:
        logger.error("Redeem failed: %s", e)
        logger.info("Trying individual redemptions...")

        condition_ids = [p.get("condition_id") for p in resolved if p.get("condition_id")]
        for cid in condition_ids:
            try:
                r = service.redeem([cid], batch_size=1)
                logger.info("Redeemed %s: %s", cid[:16], r)
            except Exception as ex:
                logger.error("Failed %s: %s", cid[:16], ex)

    # Check new balance + remaining positions
    from bot.wallet_scanner import fetch_wallet_positions
    from database.db import log_activity

    new_bal = get_wallet_balance()
    remaining = fetch_wallet_positions(config.POLYMARKET_FUNDER)
    remaining_value = sum(p.get("size", 0) for p in remaining)

    redeemed_amount = new_bal - bal_before
    if redeemed_amount > 0.10:
        log_activity("redeem", "CASH", "Shares redeemed — $%.2f returned to wallet" % redeemed_amount,
                     "Balance: $%.2f → $%.2f (+$%.2f)" % (bal_before, new_bal, redeemed_amount), redeemed_amount)
    logger.info("=== AFTER REDEEM ===")
    logger.info("Wallet USDC:    $%.2f", new_bal)
    logger.info("Remaining shares: $%.2f (%d positions)", remaining_value, len(remaining))
    logger.info("Total value:    $%.2f", new_bal + remaining_value)

    # Log to a status file for monitoring
    import datetime
    status_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "redeem_status.txt")
    with open(status_file, "a") as f:
        f.write("%s | USDC=$%.2f | Shares=$%.2f | Positions=%d\n" % (
            datetime.datetime.now().isoformat()[:19], new_bal, remaining_value, len(remaining)))


if __name__ == "__main__":
    main()
