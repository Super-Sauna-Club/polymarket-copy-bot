# Polybot Brain Fix-Everything — Design

**Date:** 2026-04-12
**Author:** Claude + wisdom
**Scope:** Fix all known defects in the brain/scorer/lifecycle subsystem found in the 2026-04-12 debug session. Three sequenced batches: Safety → Bugs → Design.

---

## Context

During systematic debugging on 2026-04-12, the bot was found to have a working trading loop but multiple broken feedback and safety mechanisms in its "brain" layer. The bot is live on `walter@10.0.0.20`, currently holds ~$100 (wallet $84.66 + positions $16.09), down from a $102 reset baseline. Real 7d closed P&L (by `pnl_realized`): ~-$149 on ~584 trades, WR ~45%. That is not catastrophic on its own, but the learning/adjustment loop is dead, meaning the bot cannot improve.

### Defects in scope

**A — Code bugs:**
1. `trade_scores.outcome_pnl` is never written → `brain._optimize_score_weights` reads 0 rows → scorer thresholds and weights never tune.
2. `auto_tuner.py` has `logger.warning("restart recommended")` instead of actually reloading — all tuner writes to `settings.env` are dead code until manual restart.
3. `scorer_weights.json` does not exist on the server → scorer always uses `DEFAULT_WEIGHTS`/`DEFAULT_THRESHOLDS`.
4. `brain._classify_losses` logs one `BLACKLIST_CATEGORY` `brain_decisions` row per loss, not per unique `(trader, category)` pair → 357 rows total, most duplicates within the same second. `TIGHTEN_FILTER` has the same pattern.
5. `trader_lifecycle` only contains traders that have been paused by brain. The primary followed traders (KING7777777, Jargs, aenews2) never get a lifecycle row, so paper/live stats cannot be tracked for them.
6. `brain._check_trader_health` reads `live_count` once before the loop; iterative pauses in the same cycle can drop live count below `MIN_LIVE_TRADERS=2`.
7. `signal_performance.losses` counter is stuck at 0 (389 `clv_tracking` trades, 1 win, 0 losses, +$21.22) — writer never increments the loss counter.
8. `ml_scorer.train_model` uses `train_test_split(random_state=42)` which gives a random split — time-series leakage. The 92.9% accuracy number is not trustworthy as-is.

**B — Config hardening (`settings.env`):**
9. `STOP_LOSS_PCT=0` — no stop loss.
10. `MAX_DAILY_LOSS=0`, `MAX_DAILY_TRADES=0` — no daily brake.

**C — Design cleanups:**
11. Two parallel trader-state systems (`trader_status` table + `trader_lifecycle` table) drift apart (e.g., sovereign2013 appears as `paused` in one and `active` in the other).
12. `BLACKLIST_CATEGORY` and `TIGHTEN_FILTER` brain decisions are permanent — there is no revert path when the condition that triggered them clears.

### Out of scope (deliberate YAGNI)

- ML model redesign beyond the time-split bug (no feature engineering, no CV, no drift monitoring). Sample size (~600) does not justify more.
- Autonomous trading / paper mode (disabled today, table empty).
- AI analyzer / AI news / AI report modules (disabled per memory).
- Backfilling `outcome_pnl` for the 426 existing `trade_scores` rows (nice-to-have, but a separate ticket).
- Dashboard / frontend changes.
- Changing ML's ±15 influence weight on scoring — first prove the time-split fix gives an honest accuracy number, then decide.

---

## Batch 1 — Safety Rails

**Goal:** Limit damage before touching learning logic.

### 1.1 — Harden `settings.env`

Change:
```
STOP_LOSS_PCT=0.40
MAX_DAILY_LOSS=10
MAX_DAILY_TRADES=30
```

Pre-flight: grep `bot/` for each of these keys and verify the enforcement code exists and runs. Memory notes `STOP_LOSS_PCT` may have been "deactivated" earlier — if so, re-enable the check in whichever smart_sell / price-watch path consumes it. If the check still exists but is gated by `if STOP_LOSS_PCT > 0:`, simply setting the value is enough. If a whole branch was deleted, we restore it (minimal restore — not a redesign).

Reason for values: $10/day = ~10% of current equity. 30 trades/day ≈ current non-blocked rate. 40% stop loss is conservative enough to absorb normal volatility on a binary market but triggers on actual losers.

### 1.2 — Initialize `scorer_weights.json` on server

Write a one-shot script (or just scp) that creates `scorer_weights.json` with:
```json
{"weights": {"trader_edge":0.30,"category_wr":0.20,"price_signal":0.15,"conviction":0.15,"market_quality":0.10,"correlation":0.10},
 "thresholds": {"block":40,"queue":60,"boost":80}}
```
No code change — this is just a missing file. Commit the defaults into `scorer_weights.example.json` in the repo so future fresh deploys are seeded.

### 1.3 — Deploy Batch 1

- SCP `settings.env` + `scorer_weights.json` to server.
- `sudo systemctl restart polybot`.
- Tail logs 5 min, verify `[SCORER] Weights loaded` (or equivalent), no new WARN/ERR beyond baseline.
- Commit the `settings.example.env` update (server + local) and `scorer_weights.example.json`.

---

## Batch 2 — Code Bugs

**Goal:** Brain can actually learn. No more spam. No more dead-code writes.

### 2.1 — Trade-Score Feedback Loop (the killer)

**Problem:** `trade_scores` gets one row per scoring call. When a copy_trade is closed and `pnl_realized` is set, nothing writes that outcome back to the score row.

**Fix:**

1. Add `db.update_trade_score_outcome(condition_id: str, trader_name: str, pnl: float, since_minutes: int = 120)`:
   ```sql
   UPDATE trade_scores
   SET outcome_pnl = ?
   WHERE condition_id = ? AND trader_name = ?
     AND outcome_pnl IS NULL
     AND created_at >= datetime('now', '-' || ? || ' minutes')
   ```
   Match by `(condition_id, trader_name)` within a recent window (2h default = matches `NO_REBUY_MINUTES`). If multiple scores match, update the newest by ordering before UPDATE via CTE (or do a subquery picking MAX(id)).

2. Call site 1: `bot/smart_sell.py`, immediately after a successful `close_copy_trade(...)`. Pass `trade["condition_id"]`, `trade["wallet_username"]`, computed `pnl_realized`.

3. Call site 2: `bot/copy_trader.py`, in the auto-close path (resolved-at-0.99 / resolved-at-0.01). Same parameters.

4. Call site 3: Add a catch-all sweep `db.backfill_trade_score_outcomes()` that runs at the top of `outcome_tracker.track_outcomes()` (already a periodic scheduler job). The sweep joins `trade_scores s` with `copy_trades t` on `condition_id`, picks rows where `s.outcome_pnl IS NULL AND t.status='closed' AND t.pnl_realized IS NOT NULL`, and updates `s.outcome_pnl = t.pnl_realized`. One UPDATE ... FROM (SELECT ...) SQL statement, bounded to last 30 days. Backfills any miss from paths 1+2 and covers legacy gaps without a separate migration script.

5. Logging: when Brain's `_optimize_score_weights` runs the next cycle, it will log real blocked-wr numbers for the first time. Verify in logs that `blocked_total >= 1` appears within a few cycles.

**Invariant:** `trade_scores.outcome_pnl IS NULL` must mean "trade not yet resolved", not "forgot to write".

### 2.2 — Auto-Restart / Settings Reload

**Problem:** `auto_tuner.py` writes `settings.env` then logs a "restart recommended" warning. The running process never re-reads the file, so BET_SIZE_MAP, MIN_ENTRY_PRICE_MAP, etc. remain stale until manual restart. Memory says auto-restart was disabled for safety (it was killing in-flight orders and DB writes).

**Fix (Option B — dirty flag, no process restart):**

1. In `config.py`, extract the settings parsing into a function `_load_settings_from_env()` that can run idempotently. On-first-import it runs once; after that, any module can call `config.reload()` to re-run it and update the module-level globals.

2. In `bot/settings_lock.py`, after `write_settings()`, set a module-level flag `_settings_dirty = True`.

3. In `bot/copy_trader.py`, at the top of each `copy_scan()` iteration, check `settings_lock.poll_dirty()` — if true, call `config.reload()` and log `[CONFIG] Reloaded settings`. poll_dirty() also resets the flag atomically.

4. Reload-safe keys (whitelist — only these get updated on reload):
   - All `*_MAP` settings (BET_SIZE_MAP, TRADER_EXPOSURE_MAP, MIN_ENTRY_PRICE_MAP, MAX_ENTRY_PRICE_MAP, MIN_TRADER_USD_MAP, TAKE_PROFIT_MAP, STOP_LOSS_MAP, MAX_COPIES_PER_MARKET_MAP, TIER_*, CATEGORY_BLACKLIST_MAP, MIN_CONVICTION_RATIO_MAP, HEDGE_WAIT_TRADERS, AVG_TRADER_SIZE_MAP)
   - Scalar runtime params: STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DAILY_LOSS, MAX_DAILY_TRADES, MAX_SPREAD, MAX_PER_EVENT, MAX_PER_MATCH, NO_REBUY_MINUTES, MAX_HOURS_BEFORE_EVENT, BUY_SLIPPAGE_LEVELS, SELL_SLIPPAGE_LEVELS, SELL_VERIFY_THRESHOLD
   - FOLLOWED_TRADERS (so adding/removing a trader takes effect without restart)
   
   Dangerous keys — NOT in whitelist (require process restart):
   - LIVE_MODE, DASHBOARD_HOST, DASHBOARD_PORT, COPY_SCAN_INTERVAL, any DB path, STARTING_BALANCE
   
   Implementation: keep two sets `_RELOAD_SAFE_KEYS` and `_REQUIRES_RESTART_KEYS` in `config.py`. `reload()` only touches keys in the safe set. Any unknown key logs a warning (forces us to classify new settings as they are added).

5. Re-enable the auto_tuner's "restart" behavior: replace the `logger.warning("restart recommended")` with a direct call to `settings_lock.mark_dirty()` (or have `write_settings()` do it automatically — cleaner).

**Why not SIGHUP:** works too, but requires signal handler plumbing in main.py and one extra process boundary. The flag is simpler and testable.

### 2.3 — Brain Log Deduplication

**Problem:** `_classify_losses` iterates `BAD_CATEGORY` losses and calls `_add_category_blacklist(trader, category, reason)` per loss. Each call writes one brain_decisions row even though the setting update is idempotent. Result: 357 rows, most duplicates within the same second.

**Fix:**

1. In `_execute_loss_actions`, collect `BAD_CATEGORY` losses into a `set((trader, category))` first.
2. Call `_add_category_blacklist` once per unique pair.
3. Inside `_add_category_blacklist`, before logging, check whether `(trader, category)` is already in the current `CATEGORY_BLACKLIST_MAP`. If yes, return early (no settings write, no brain_decisions log).
4. Same pattern for `_tighten_price_range`: track already-tightened (trader, day) in memory for the current brain cycle; skip repeats.

### 2.4 — Trader-Lifecycle Bootstrap

**Problem:** `trader_lifecycle` is only populated by `brain.pause_trader` which calls `db.upsert_lifecycle_trader(address, trader_name, "LIVE_FOLLOW", "manual")` only as a fallback before pausing. So KING7777777, Jargs, aenews2 have never been entered. Paper stats cannot be tracked for them.

**Fix:**

1. New function `trader_lifecycle.ensure_followed_traders_seeded()`:
   - Parse `FOLLOWED_TRADERS` from settings.
   - For each `username:address` entry, `db.upsert_lifecycle_trader(address, username, "LIVE_FOLLOW", "manual")` if not already present.
   - Called once from `main.py` after DB init, before scheduler starts.
   - Also called from `brain._check_trader_health` at the start of each cycle, to catch traders added between restarts via settings reload.

### 2.5 — `MIN_LIVE_TRADERS` Race

**Problem:** `_check_trader_health` parses `FOLLOWED_TRADERS` once into `live_count`, then iterates traders. If it pauses trader A, `live_count` in memory stays the same, so it can also pause B and C and drop actual live count below 2.

**Fix:**

1. Refactor the pause-check into a helper `_current_live_count()` that re-reads settings each call.
2. Call it at the top of each iteration of the for-loop inside `_check_trader_health`.
3. Guard: `if should_pause and _current_live_count() > MIN_LIVE_TRADERS`.

### 2.6 — `signal_performance.losses` Bookkeeping

**Problem:** Row `{signal_type: clv_tracking, trades=389, wins=1, losses=0, pnl=+$21.22}` is wrong. `losses` counter is never incremented. `trades_count` grows but `wins + losses` does not keep up.

**Fix (discover-then-patch):**

1. Investigation step: grep for `INSERT INTO signal_performance` and `UPDATE signal_performance` in `bot/clv_tracker.py`, `bot/autonomous_signals.py`, `database/db.py`. Likely outcome: one or more sites increment `wins` but not `losses`, or use a WHERE clause that silently skips losing trades.
2. Patch: wherever a wins++ branch exists, mirror with a losses++ branch covering the `else`. If the schema uses SET wins = wins + ... pattern, add the symmetric losses update.
3. Add a defensive sanity log in `brain._check_autonomous_performance`: if `wins + losses != trades_count`, emit a `logger.warning("[BRAIN] signal_performance %s: wins+losses=%d != trades=%d", ...)`. Do not crash — just warn.
4. Do NOT backfill historical rows; that data is lost.

### 2.7 — ML Time-Series Split

**Problem:** `ml_scorer.train_model` uses `train_test_split(X, y, test_size=0.2, random_state=42)` — random split leaks future information into training.

**Fix:**

1. Sort the training data by `created_at` before building X, y.
2. Replace `train_test_split(...)` with explicit slice: last 20% by time → test set; first 80% → train set.
3. Add class-balance logging: `logger.info("[ML] Class balance: %d wins / %d losses (%.0f%%)", ...)` before reporting accuracy. This lets future-us see if 92% is "real" (class balance ~50/50) or baseline illusion (class imbalance).
4. Log majority-class baseline accuracy side-by-side with test accuracy: `[ML] Baseline acc (always predict majority): 65.2% | Model: 70.1%`. Anyone can now see if the model beats the baseline or not.

---

## Batch 3 — Design Cleanups

**Goal:** One source of truth for trader state. Auto-revert for brain decisions.

### 3.1 — Trader-State Unification

**Problem:** `trader_status` (3 rows, legacy) and `trader_lifecycle` (6 rows, new) drift apart. Example: sovereign2013 is `active` in `trader_status` (restored 14:29) and `PAUSED` in `trader_lifecycle` (since 07:49). Different code paths consult different tables → different decisions.

**Fix:**

1. `trader_lifecycle` has the richer schema (status, paper stats, pause_count, rehab) → this is the Source of Truth going forward.

2. One-shot migration function `db.migrate_trader_status_to_lifecycle()` added to `database/db.py` and called from `init_db()`. Idempotent (re-runnable). For each `trader_status` row:
   - Look up the matching `trader_lifecycle` row by `username = trader_status.trader_name`.
   - If found: if `trader_status.status` is newer than `trader_lifecycle.status_changed_at`, update the lifecycle row's status (map `paused` → `PAUSED`, `active` → `LIVE_FOLLOW`).
   - If not found: insert a new lifecycle row with the mapped status and `source='migration'`.
   - Log once per migrated row.

3. Discovery step (to run before implementation): `grep -rn "trader_status" bot/ dashboard/ database/` to enumerate writers and readers. Expected: a small number of files (likely copy_trader.py, auto_tuner.py or similar). Plan will list the exact file/line refs once discovered.

4. Replace all writers of `trader_status` with writers of `trader_lifecycle`:
   - `pause_trader(name, reason)` already exists in `bot/trader_lifecycle.py` — reuse.
   - `resume_trader(name, reason)` — new helper, flips PAUSED → LIVE_FOLLOW.
   - Delete the direct `INSERT/UPDATE trader_status` statements.

5. Replace all readers:
   - New helper `db.is_trader_paused(username: str) -> bool`: queries `trader_lifecycle` for the most recent status of the username, returns True if status == 'PAUSED' and (pause_until IS NULL OR pause_until > now).
   - Grep-and-replace every `SELECT status FROM trader_status` pattern.

6. Retention: keep `trader_status` table in the schema but stop writing to it. Do not drop in this batch — follow-up commit in a later session once we confirm no regression. The table being stale and unread is fine; dropping it is a separate concern.

### 3.2 — Brain Decision Auto-Revert

**Problem:** Once brain blacklists `KING7777777:dota`, that setting sticks forever. Even if KING later has a 60% WR in dota, the blacklist is never removed.

**Fix:**

1. New function `brain._revert_obsolete_blacklists()`:
   - Parse current `CATEGORY_BLACKLIST_MAP`.
   - For each `(trader, category)` entry:
     - Query `copy_trades` for the trader+category in the last 7d.
     - If `cnt >= 3` AND `wr >= 50%` AND `total_pnl >= 0`: remove entry, log `REVERT_BLACKLIST` decision.
   - Write back the updated map.

2. New function `brain._revert_obsolete_tightens()`:
   - Compare each trader's current `MIN_ENTRY_PRICE_MAP` / `MAX_ENTRY_PRICE_MAP` against the tier defaults (from auto_tuner).
   - If trader's 7d PnL is back in positive territory (> 0) AND current range is tighter than tier default:
     - Relax by 0.05 toward tier default per cycle (not in one jump).
     - Log `RELAX_FILTER` decision.

3. Call both at the end of `run_brain()`, after `check_transitions()`. This closes the loop: auto_tuner sets tier-based ranges, brain tightens on losses, brain relaxes on recovery.

4. Safety: both functions skip if a revert would bring a map to invalid state (e.g., min >= max). Log and skip.

---

## Testing

**Unit tests (where DB is mockable):**

- `test_feedback_loop.py`: create a trade_score fixture, call `db.update_trade_score_outcome(...)`, assert `outcome_pnl` is set; assert only the newest matching row is updated when multiple exist.
- `test_brain_dedup.py`: mock a set of 5 identical losses → call `_execute_loss_actions` → assert exactly 1 `brain_decisions` row and 1 settings write.
- `test_lifecycle_seed.py`: empty lifecycle table + settings with 3 followed traders → call `ensure_followed_traders_seeded` → assert 3 `LIVE_FOLLOW` rows exist.
- `test_live_count_race.py`: 3 followed traders, 3 losers → only 1 gets paused (the other 2 saved by MIN_LIVE_TRADERS guard).
- `test_ml_time_split.py`: build a fake dataset with a monotonic trend → random split would "pass"; time-series split should reflect drift. Verify baseline accuracy is logged.
- `test_revert_blacklist.py`: blacklist a category, insert recent winning trades, run revert, assert blacklist entry is gone and `REVERT_BLACKLIST` decision is logged.

**Manual verification (on server after each batch deploy):**

- Batch 1: restart, verify no STOP_LOSS=0 warning, watch one scan cycle, confirm settings loaded with new values.
- Batch 2: watch `brain_decisions` table for next Brain cycle (every 2h, so may need to trigger manually via `python3 -c "from bot.brain import run_brain; run_brain()"`). Confirm: no duplicate rows for same trader/category pair; `trade_scores.outcome_pnl` is being populated as trades close.
- Batch 3: confirm `trader_lifecycle` has one row per followed trader, `trader_status` is empty after migration, a manual brain trigger reverts a blacklist for any category that no longer qualifies.

**Deliberately NOT tested:**
- Live Polymarket API calls (flaky, costs tokens).
- Full end-to-end copy_scan → buy → sell cycle.
- Performance under load (not a performance change).

---

## Deployment

- Server has no GitHub access — SCP files individually after each batch:
  - Batch 1: `settings.env`, `scorer_weights.json`.
  - Batch 2: `bot/brain.py`, `bot/trade_scorer.py` (if touched), `bot/ml_scorer.py`, `bot/copy_trader.py`, `bot/smart_sell.py`, `bot/settings_lock.py`, `bot/auto_tuner.py`, `database/db.py`, `config.py`, `bot/trader_lifecycle.py`, `main.py`.
  - Batch 3: `database/db.py` (migration), `bot/brain.py`, plus whatever writers of `trader_status` get rewritten.
- After each SCP: `sudo systemctl restart polybot`, tail logs 5 minutes, count WARN/ERR deltas.
- Rollback: `scp settings.env.bak.<ts> walter@10.0.0.20:.../settings.env` and/or `git reset --hard before-batchN` local + re-SCP. Never `git push --force`.
- Git: commit each batch to `main` as its own commit (3 total). Never touch `piff-*` branches.
- Memory update: after deploy, append a "Round 4 Bugfixes 2026-04-12 Abend" section to `project_polybot.md`.

### Risk matrix

| Risk | Severity | Mitigation |
|---|---|---|
| Settings reload races with active buy path | Medium | Reload only at top of `copy_scan()` iteration, never mid-trade; reload-safe key whitelist in config.py |
| Trade-score update on wrong row (multiple matches) | Low | Match by `(condition_id, trader)` within 120min window + newest-by-id tiebreak |
| Lifecycle migration loses data | Medium | Back up DB file before migration; migration is idempotent (UPSERT semantics) |
| Auto-revert flaps blacklists on small samples | Medium | Require `cnt >= 3` in last 7d + `WR >= 50%` + `PnL >= 0` — all three conditions |
| STOP_LOSS=0.40 triggers on normal volatility | Low | 40% is conservative; adjust if false positives appear |

---

## Success Criteria

**After Batch 1:**
- `settings.env` has non-zero STOP_LOSS, MAX_DAILY_LOSS, MAX_DAILY_TRADES.
- `scorer_weights.json` exists on server and is loaded by scorer.
- Bot running `active`, no new WARN/ERR patterns.

**After Batch 2:**
- `trade_scores.outcome_pnl` is populated for new closing trades (spot-check 10 rows within 2h of deploy).
- `brain_decisions` rows per cycle drops to ≤ 1 row per unique (action, target) pair.
- `trader_lifecycle` contains a row for every name in `FOLLOWED_TRADERS`.
- ML training log shows class balance + baseline accuracy alongside test accuracy.
- A `settings.env` change (e.g., manually edit `BET_SIZE_MAP`) is picked up within one scan cycle (~5s) without restart.
- `signal_performance.losses` starts incrementing for any closed losing signal.

**After Batch 3:**
- `trader_status` writes are gone; `is_trader_paused()` works via lifecycle.
- A stale blacklist can be auto-reverted by the brain within one cycle when the condition clears.
- sovereign2013/nhl in the current CATEGORY_BLACKLIST_MAP either gets reverted (if data supports it) or stays with justification logged.

**Overall:**
- Bot's total equity does not drop more than $5 during the deploy window.
- All three batches merged to main within the session.
- Memory file `project_polybot.md` updated with the Round 4 bugfix section.
