-- scripts/remove_followed_trader.sql
--
-- Scenario D Phase A1: idempotent removal of a wallet from the live-follow set.
--
-- Usage (Python):
--     with open("scripts/remove_followed_trader.sql") as f:
--         conn.execute(f.read(), {"addr": "0x..."})
--
-- Companion manual step (not SQL): remove the same address from per-trader
-- maps in settings.env: MIN_ENTRY_PRICE_MAP, MAX_ENTRY_PRICE_MAP, BET_SIZE_MAP,
-- MIN_TRADER_USD_MAP, TRADER_EXPOSURE_MAP, MAX_COPIES_PER_MARKET_MAP,
-- STOP_LOSS_MAP, TAKE_PROFIT_MAP, AVG_TRADER_SIZE_MAP, HEDGE_WAIT_TRADERS,
-- and FOLLOWED_TRADERS.

UPDATE wallets SET followed = 0 WHERE address = :addr;
