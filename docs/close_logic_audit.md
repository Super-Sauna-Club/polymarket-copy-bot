# Close-Logic Audit — 2026-04-13

**Goal**: Identify why 89% of closed `copy_trades` rows have `usdc_received=NULL`. Catalog every close path, pinpoint the root cause, and sequence a per-path fix plan.

**Why this matters**: Brain, ML Scorer, and Trade Scorer all read `pnl_realized` from `copy_trades` as their ground truth. With 89% of rows holding formula-computed (not capital-verified) PnL, every feedback loop is training on garbage. The -71% portfolio drop is partially driven by tracking drift and decisions made on corrupt data. This audit is the blocker for any meaningful Brain/ML improvement.

## DB-level forensics (Server `database/scanner.db`, 2026-04-13 evening)

**Total closed ghost trades** (status=closed, usdc_received IS NULL):

| Pattern | Count | Invested | DB pnl_realized | Interpretation |
|---|---|---|---|---|
| `current_price = 0` | 180 | $226.11 | -$760.12 | AUTO-CLOSE-lost (resolved to 0) |
| `current_price >= 0.95` | 184 | $140.28 | **+$750.29** | AUTO-CLOSE-won (resolved to 1) |
| `0 < current_price < 0.95` | 156 | $36.14 | +$36.62 | Gamma-fallback or race close |
| `current_price IS NULL` | 32 | $112.59 | -$124.79 | Early pre-column state |
| **Partial-fill** (usdc_received > 0 but < 50% of size) | 14 | $50.01 | — | Medium path silent partial |

**Key observation**: The `+$750.29` in the AUTO-CLOSE-won bucket is the primary source of the **fake DB profit** that makes Brain think KING is losing when verified data says he's winning. $750 "DB profit" on $140 invested = 535% return — obviously fake. Real money flow: shares are still on chain, need manual `redeem_positions.py` to realize. The DB never updates `usdc_received` after redemption because the redeem script doesn't touch `copy_trades`.

**Ghost counts by day (7d)**: 2026-04-11 was the peak with 27 ghost closes ($95 invested); activity dropped after roster shrink on 2026-04-13 (only 3 ghosts yesterday, likely Gamma-fallback).

## Path Catalog

### HIGH Severity (bypass sell_shares entirely)

#### 1. AUTO-CLOSE-lost — `main.py:341`
- **Trigger**: `current_price <= 0.005` detected in reconcile loop, position is deemed unrecoverable loss
- **Bug**: Direct DB UPDATE setting `status='closed'`, `usdc_received=0`, `pnl_realized=-size`. Never calls `sell_shares()`.
- **Real-world impact**: **Low financial bleed** — if price really is 0, there's nothing to sell anyway. The bug is architectural (inconsistent code pattern), not money-losing.
- **Count in DB**: 180 trades, $226 invested, -$760 DB pnl (which is correct — these are real losses)
- **Fix priority**: LOW — architectural cleanup only

#### 2. AUTO-CLOSE-won — `main.py:372`
- **Trigger**: `current_price >= 0.95` detected in reconcile loop, position is deemed a resolved winner
- **Bug**: Direct DB UPDATE setting `status='closed'`, `pnl_realized=shares*final_price - cost`, **`usdc_received` NULL**. Never calls `sell_shares()` and never triggers redemption.
- **Real-world impact**: **HIGH financial tracking bleed**. $140 invested → DB claims +$750 profit → but the shares may or may not have been redeemed. Brain reads this as realized profit and makes boost/tighten decisions on $750 of phantom money.
- **Count in DB**: 184 trades, $140 invested, **+$750 fake DB pnl**
- **Fix priority**: **CRITICAL** — this single path is the main corruption source for Brain's view

#### 3. Gamma-fallback — `bot/copy_trader.py:2562` (in `update_copy_positions`)
- **Trigger**: Market resolved via Polymarket Gamma API, but our CLOB data is stale
- **Bug**: `db.close_copy_trade(trade["id"], pnl)` is called FIRST. Then `db.update_closed_trade_pnl(trade["id"], ...)` is called second. Race window: if anything between throws, DB is closed but `usdc_received` stays NULL. Also computes `usdc_received = shares * final_price` — a formula, not a capital-verified fill.
- **Real-world impact**: **Medium bleed** — 156 trades, $36 invested. Small $, but contaminates data quality.
- **Count in DB**: 156 trades, $36 invested, +$37 DB pnl
- **Fix priority**: MEDIUM

### MEDIUM Severity (correct ordering, but error-path leaves NULL)

All five paths below follow the same flow:
1. Call `sell_shares()` — returns dict or None
2. Call `db.close_copy_trade(trade_id, pnl_realized)` — marks `status='closed'`
3. Call `db.update_closed_trade_pnl(trade_id, pnl, usdc_received)` — sets `usdc_received`

**Structural bug**: `close_copy_trade()` signature does NOT accept `usdc_received`:
```python
# database/db.py:346
def close_copy_trade(trade_id: int, pnl_realized: float, close_price: float = None) -> bool:
```
So step 2 always leaves `usdc_received=NULL`. Step 3 is a separate function that must be called explicitly. Any error or early-return between steps 2 and 3 leaves the row permanently with NULL.

#### 4. TRAILING-STOP — `bot/copy_trader.py:2431`
- **Trigger**: Price dropped N% from trailing peak after a ≥20% gain
- **Sell flow**: Correct order (sell first, then close)
- **Partial fill**: Accepted silently at 80% threshold via `sell_shares()` retry levels
- **Bug**: If `_correct_sell_pnl()` helper (line 2438) throws, `usdc_received` stays NULL. Partial fills are recorded as full closes — orphaning remaining shares on chain.

#### 5. TAKE-PROFIT — `bot/copy_trader.py:2464`
- **Trigger**: Price rose N% from entry (default 45%)
- Same pattern as TRAILING-STOP

#### 6. FAST-SELL — `bot/copy_trader.py:1592`
- **Trigger**: Followed trader closed his position (mirror immediately)
- Same pattern
- This one is the most frequent MEDIUM path

#### 7. trader-closed-it — `bot/copy_trader.py:2513`
- **Trigger**: Position detected closed in trader wallet via activity scan
- Same pattern

#### 8. miss-close — `bot/copy_trader.py:2612`
- **Trigger**: Position vanished from wallet for 20+ consecutive misses
- Same pattern, no explicit partial-fill handling

## Root Cause

**Single structural defect**: `db.close_copy_trade()` (database/db.py:346) does not accept `usdc_received` as a parameter. This forces callers into a 2-step process:
1. `close_copy_trade()` — marks status='closed' and sets `pnl_realized` (often formula-computed)
2. `update_closed_trade_pnl()` — separately updates `pnl_realized` + `usdc_received` with capital-verified values

Any path that forgets step 2, crashes between steps, or opts out entirely (main.py AUTO-CLOSE paths) leaves `usdc_received=NULL`. There is no constraint enforcing this invariant.

## Redemption gap

`redeem_positions.py` exists but:
- Is a **manual** script, not a scheduled job
- Calls `PolyWeb3Service.redeem_all()` on chain
- **Never touches `copy_trades` DB** — doesn't update `usdc_received` even after successful redemption
- So: positions marked AUTO-CLOSE-won → redeemed manually on chain → actual USDC lands in wallet → DB still shows `usdc_received=NULL`

This explains why the real wallet drops less than the DB suggests (DB thinks positions are lost/won but the actual $-delta never syncs back).

## Proposed fix sequence

Not a to-do list — a **dependency ordering**. Each step unblocks the next.

### Step 1 (structural, single commit): Fix `close_copy_trade()` signature

Add `usdc_received: float = None` parameter. Require it for all non-reconcile paths. Deprecate standalone `update_closed_trade_pnl()` for new code (keep for backfill).

**Why first**: Every subsequent per-path fix becomes a 1-line change instead of a refactor.

**Files**: `database/db.py`, plus a handful of callers.

**Test coverage**: TDD — write a test that asserts `usdc_received` is always non-NULL after a close, run against the current code (RED because main.py bypasses), then fix per path.

### Step 2 (critical money): Fix AUTO-CLOSE-won `main.py:372`

This is the single biggest corruption source (+$750 fake DB profit). Two options:

**Option 2a** — mark `status='pending_redemption'` instead of `closed`. Brain aggregation queries need to exclude `pending_redemption`. A new scheduled job `reconcile_redemptions` walks the `pending_redemption` rows, reads wallet balance, matches to specific positions, and transitions to `closed` with real `usdc_received`.

**Option 2b** — call the redeemer synchronously at close time. Risk: redemption is slow (on-chain TX), blocks the reconcile loop, costs POL. Requires POL balance monitoring.

**Recommendation**: Option 2a. Cleaner separation of concerns, no sync-on-chain calls in hot paths.

### Step 3: Fix AUTO-CLOSE-lost `main.py:341` to call sell_shares OR acknowledge no-op

Even though price=0 positions have no real money at stake, calling sell_shares (which will no-op correctly) keeps the code pattern uniform with other paths. Alternatively, document the bypass explicitly with a comment referencing this audit.

### Step 4: Fix the 5 MEDIUM paths (TRAILING-STOP, TAKE-PROFIT, FAST-SELL, trader-closed-it, miss-close)

After Step 1, these become trivial: pass `usdc_received` through `close_copy_trade` in one shot. Add partial-fill detection: if `sell_shares()` reports partial fill (e.g., 7/10 shares sold), either retry the remainder or mark the row with the partial amount + a new `partial_close` flag so Brain knows the residual.

### Step 5: Reconcile backfill

One-off DB operation: for existing 552 NULL rows, try to reconstruct `usdc_received` from on-chain wallet history via `data-api.polymarket.com/activity`. Partial fills and already-redeemed positions can be back-filled. Unrecoverable rows (old baseline, cleaned data) should be explicitly flagged, not left as NULL.

### Step 6: Fix Gamma-fallback race

Last priority because money impact is small. After Steps 1-4, the pattern is established; Step 6 is applying it to one more path.

## Verification queries (run after each step)

```sql
-- Verified rate (target ≥85% after Steps 1-5):
SELECT 
  ROUND(100.0 * SUM(CASE WHEN usdc_received IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS verified_pct,
  COUNT(*) AS total_closed
FROM copy_trades 
WHERE status='closed' 
  AND datetime(closed_at) >= datetime('now','-30 days');

-- Brain's view vs reality (should converge after Step 2):
SELECT 
  wallet_username,
  SUM(pnl_realized) AS db_pnl,
  SUM(CASE WHEN usdc_received IS NOT NULL THEN usdc_received - actual_size ELSE 0 END) AS verified_pnl
FROM copy_trades 
WHERE status='closed' 
  AND datetime(closed_at) >= datetime('now','-7 days')
GROUP BY wallet_username;

-- AUTO-CLOSE-won fake profit (must fall to 0 after Step 2):
SELECT COUNT(*), SUM(pnl_realized) 
FROM copy_trades 
WHERE status='closed' 
  AND usdc_received IS NULL 
  AND current_price >= 0.95;
```

## Scope explicitly NOT covered here

- **Brain/ML/Scorer changes** — those depend on Step 1-5 being live. Don't touch them until verified data is flowing.
- **Roster scouting / trader discovery** — separate research problem.
- **Drag reduction** (slippage, fees) — structural Polymarket constraint, not a close-logic bug.
- **Ghost positions on chain** (the $22 separate finding) — related but different: those are positions in a nebulous state, not just mis-tracked closes.

## Next Session Entry Point

**Start at Step 1**. Write failing test first (assert verified_pct ≥85% on a fresh DB with mock sells). Then change `close_copy_trade()` signature. Then fix main.py:372 (Step 2). Then the 5 MEDIUM paths (Step 4). Then backfill (Step 5). Gamma-fallback (Step 6) last.
