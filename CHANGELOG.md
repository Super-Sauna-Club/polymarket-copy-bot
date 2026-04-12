# Changelog — piff-custom Branch

All changes made on the piff-custom branch (fork of Super-Sauna-Club/polymarket-copy-bot).

## 2026-04-12

### Bug Fixes

- **PATCH-001**: Fix missing `import os` in `bot/trader_performance.py` — caused NameError crash when scheduler runs `update_adaptive_stop_loss()`
- **PATCH-002**: Fix `OrderBookSummary` dataclass access in `bot/liquidity_check.py` — was treated as dict, causing AttributeError and bypassing all liquidity checks silently
- **PATCH-003**: Add missing `X-Dashboard-Key` auth header to report fallback fetch in dashboard — `/api/report/latest` was always returning 403
- **PATCH-004**: Remove unused API call in `bot/wallet_scanner.py` — `act_resp` from `/activity` endpoint was fetched but never used, wasting requests
- **PATCH-006**: Use developer helper `_get_attr_or_key()` for orderbook level access in `bot/liquidity_check.py` — supports both dataclass and dict format
- **PATCH-009**: Fix hidden `-$10` auto-pause threshold in `bot/brain.py` — was pausing traders independently from lifecycle
- **PATCH-011**: Fix third hidden `-$10` throttle in `bot/trader_performance.py` — `THROTTLE_PNL_7D` was auto-throttling traders at `-$10`

### Infrastructure

- **PATCH-005**: Improved `auto-update.sh` with syntax checks before restart, 30s health check after restart, automatic rollback on service crash
- **GitLab migration**: Repo moved from GitHub to `gitlab.com/piff.patrick/polymarket-copy-bot`, auto-update cron every 15 min fetches from upstream (GitHub), merges with `-X ours`, pushes to GitLab

### Settings Management

- **PATCH-008**: Raised lifecycle pause/kick thresholds (`-$20`/`-$50` instead of `-$10`/`-$30`)
- **PATCH-010**: Full settings reset — all 6 traders equal baseline (3% bet, 10% exposure, 0.3 conviction, 30% SL, 150% TP, no category blacklists)
- **PATCH-013**: Disabled auto-pause/remove in `trader_lifecycle.py`, `brain.py`, and `trader_performance.py` — settings now managed manually, functions still log but do not modify `settings.env`
- **PATCH-016**: Disabled `auto_tuner.py` hardcoded tier table — was overwriting all settings every 2h with rigid star/solid/neutral/weak/terrible tiers

### Discovery Scanner

- **PATCH-012**: Enhanced leaderboard scan — now scans 4 time periods (ALL/30d/7d/1d) to find both established and rising traders. Increased `MAX_CANDIDATES` from 50 to 100, lowered whale scanner thresholds

### Dashboard

- **PATCH-007**: ML Model update
- **PATCH-014**: ML Model update + settings stabilization
- **PATCH-015**: Trader Power Levels now shows traders with 0 trades (removed `trades_count > 0` filter)
- **PATCH-017**: Added copied trades count next to trader name, added 1d P&L/WR/trades row to trader cards

### Notes for t0mii

- All auto-pause/throttle/kick functions are **disabled** (log-only). We manage settings manually based on performance data. If you re-enable them, they will override our settings.
- The `auto_tuner.py` hardcoded `TIERS` dict is disabled. Consider making tiers configurable via `settings.env` instead of hardcoded.
- `_remove_followed_trader()` in `trader_lifecycle.py` is disabled because it rewrites `settings.env` and destroys other map settings when removing a trader.
- Upstream merges use `-X ours` strategy — our changes take priority on conflicts.
