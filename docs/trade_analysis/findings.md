# Trade Analysis Findings — Ralph Loop

Session-level findings appended here. Newest at top. Keep last 10 iterations visible, archive older sections below the `## Archive` marker.

Loop prompt: see `docs/trade_analysis/ralph-prompt.md`.

---

## Iteration 35 — 2026-04-13 15:41 UTC (Δt ≈ 8 min) — 🚨 #3150 closed ZERO -$2.11 (5th total-loss). Scheduler alive — iter 34 was wrong.

### Snapshot
- Portfolio: **$90.39** (Wallet $67.47 + Positions $22.92), Δ **-$0.60** since iter 34
- Wallet unchanged, positions -$0.60 (from #3150 finally hitting the DB as closed + ghost MTM noise)
- Today PnL: **-$9.86** (Δ -$2.11 — exactly #3150's realized loss)
- Today closes: **12** (+1 KING #3150), 1 win still
- Bot errors last 10min: **0**
- Settings hash: **`3a5adaaa...`** (was `ffca70f7...` for 5+ hours — new write!)

### 🚨 #3150 closed at ZERO — 5th total-loss of session
```
id=3150 trader=KING7777777 category=cs
entry=0.617  current=0.0  size=$2.11  pnl_realized=-$2.11
closed_at=2026-04-13 13:27:19  close_type=ZERO
market="Counter-Strike: ex-RUBY vs Metizport (BO3) - European"
```

Total loss of the entire $2.11 stake. The BO3 resolved against ex-RUBY. This is the **5th zero-close of the session**:
1. #3035 NBA Spurs spread → 0
2. #3036 NBA Jazz/Lakers O/U → 0
3. #3128 CS HEROIC Academy Map 1 → 0
4. #3129 CS HEROIC Academy Map 2 → 0
5. **#3150 CS ex-RUBY Metizport BO3 → 0**

**Cumulative zero-close loss**: -$9.87 across these 5 trades. All KING except the two NBA ones. CS is a recurring failure mode for KING in this session.

**Note on iter 34 timestamp confusion**: #3150's `closed_at` is 13:27:19, yet iter 34 (15:33 UTC) showed it as `status=open` with `current_price=0.55`. That means the DB status update lagged ~2h behind the actual close. Either:
- The close happened in-memory / on-chain earlier but the DB write only landed at iter 35's gather time
- OR `closed_at` is backfilled from the market resolution time, not the DB update time

Doesn't matter for the P&L math — the loss is real and realized now.

### 🚨 Correction to iter 34: SCHEDULER IS ALIVE

Iter 34 claimed "systemic APScheduler failure" based on not seeing reconcile or brain runs in the grep window. That diagnosis was **wrong**. This iter's expanded health check for all scheduled jobs:

| Job | Last run | Lines in last hour | Status |
|---|---|---|---|
| BRAIN | 13:11:55 (decisions #489-492) | 15 | ✅ ALIVE |
| RECONCILE | 13:13:54 (latest ghost line) | 8 | ✅ ALIVE |
| OUTCOME | 13:12:33 ("[OUTCOME] Tracked 100 blocked trade outcomes") | 5 | ✅ ALIVE |
| AUTO_TUNE | 13:11:55 ("[TUNER] Settings written — copy_trader will reload on next scan") | 22 | ✅ ALIVE |
| ML_TRAIN | — | 0 | ⚠️ No recent entries (expected — ML retrains are infrequent) |

**Iter 34's grep windows were too tight or pattern-specific**. The runs at 12:43:54 that iter 34 treated as "last one" were not the latest — reconcile ran again at 13:13:54, 13:43:54, etc. All were in subsequent grep windows that I fetched this iter. Corrected.

### Brain cycle at 13:11:55 fired 4 decisions
- **#489 TIGHTEN_FILTER KING7777777** "Brain: 11 BAD_PRICE losses for KING7777777"
- **#490 PAUSE_TRADER sovereign2013** "5 consecutive losses" (logged-only per piff)
- **#491 PAUSE_TRADER xsaghav** "7d PnL $-57.90 < -$20" (logged-only)
- **#492 PAUSE_TRADER fsavhlc** "7d PnL $-21.05 < -$20" (logged-only)

**No RELAX_FILTER this cycle** — the mutex would have skipped it anyway (TIGHTEN fired first), so we can't empirically verify the mutex this specific cycle. But iter 31 already verified via the "Skipping RELAX" log line at 11:11:55. The mutex fix is production-verified.

**Brain cross-cycle dedup check**: `#489 TIGHTEN_FILTER KING7777777` fired. Previous TIGHTEN would have been ~2h ago. The 3-hour dedup window means this one is the FIRST new row that escaped the dedup. Last visible TIGHTEN in the brain_decisions table was `#481 TIGHTEN_FILTER KING7777777` at 09:28:57. 09:28 + 3h = 12:28. #489 at 13:11:55 is 13:11 > 12:28, so the dedup window had expired and the new TIGHTEN wrote through. **Cross-cycle dedup working as designed.**

### auto_tuner wrote settings.env
`[TUNER] Settings written — copy_trader will reload on next scan` at 13:11:55 (same timestamp as brain cycle, auto_tune runs after brain in the scheduled job). This is **the answer to the iter-28 mystery writer question**:

**The settings.env writer is the brain→auto_tuner sequence** running every 2h. Every brain cycle:
1. Brain classifies losses, blacklists categories, tightens filters → may write settings via `_update_setting`
2. Auto_tuner runs after → rewrites TIER-based `MIN/MAX_ENTRY_PRICE_MAP`, `MAX_COPIES_PER_MARKET_MAP`, etc.

Settings hash changed `ffca70f7...` → `3a5adaaa...` at 13:11:55. **The iter-28 roster revert was likely not the lifecycle bypass** (that was also true and fixed in `60158e2`) **but auto_tuner rewriting the MAP entries** including all historical traders from its tier lookup. The lifecycle bypass was one cause of `FOLLOWED_TRADERS` re-adding retired traders; auto_tuner is a separate issue that writes TIER-based MAP entries for every known trader regardless of followed status.

### Block EXPLOSION again: 636 blocks in ~8 min*
*Δt between iters is nominally 8 min but blocks accumulated since iter 34's 15:33 gather = ~28 min wall time. Per-minute: **~22/min** (iter 34 was 1.74/min, 12.6× jump back up).

- xsaghav: **310** (49%)
- sovereign2013: **288** (45%)
- KING: 37 (6%)
- fsavhlc: 1

Reasons: price_range 312, category_blacklist 112, event_timing 105, exposure_limit 34, no_rebuy 28, conviction_ratio 26, min_trader_usd 19.

**95% of blocks from retired traders**. Iter 34's "lull" was transient. Retired-roster thrash is **oscillating** between bursts (10-22/min) and lulls (<2/min), not steadily calming down.

### Trader 7d rolling — significant shifts
| Trader | n | Wins | PnL | Δ vs iter 34 |
|---|---|---|---|---|
| KING7777777 | 128 | **51** (was 52) | **-$16.62** (was -$12.77) | **-$3.85** (#3150 -$2.11 + a win aged out of 7d window -$1.74-ish) |
| Jargs | 17 | 8 | -$10.67 | 0 |
| xsaghav | **179** (was 181) | **77** (was 79) | -$61.11 (was -$57.90) | **-$3.21** (2 trades rotated out, 2 of them winners) |
| sovereign2013 | **170** (was 173) | **78** (was 79) | -$43.75 (was -$43.62) | -$0.13 (3 trades out, 1 win out) |
| fsavhlc | 20 | 8 | -$21.05 | 0 |

Combined 7d: **-$153.20 across 514 trades** — marginally improved from iter 33's -$156 due to rotation, but all 5 traders are still deep negative.

### 0 new scores still
Filter-before-scorer rejection continues. `trade_scores` max_id still 908. **Feedback coverage: 75/124 = 60.5%** (+1 outcome from #3150 close).

### Flags
- [x] **🚨 ZERO_CLOSE_5TH**: #3150 KING CS ex-RUBY BO3 closed -$2.11 ZERO. 5th total-loss of session (cumulative -$9.87).
- [x] **ITER_34_WAS_WRONG**: scheduler is alive, brain/reconcile/outcome/auto_tune all firing. Corrected.
- [x] **BRAIN_CYCLE_FIRED**: 4 decisions at 13:11:55. TIGHTEN KING + 3 logged-only PAUSEs. Cross-cycle dedup worked (3h window expired since last TIGHTEN at 09:28:57).
- [x] **AUTO_TUNER_SETTINGS_WRITER_IDENTIFIED**: `[TUNER] Settings written` at 13:11:55 matches settings mtime exactly. This is the likely iter-28 revert mystery writer (in addition to lifecycle bypass).
- [x] **BLOCK_OSCILLATION**: 13.0 → 1.74 → 22.7/min. Not trending down, just oscillating with match slate density.
- [x] **KING_LOST_7D_WIN**: WR count 52→51, PnL -$3.85. Window + #3150 close.
- [ ] BOT_CRASHING (0 errors)
- [ ] BRAIN_SILENCE (corrected: alive)
- [ ] RECONCILE_SILENCE (corrected: alive, last 13:13:54)
- [ ] PHANTOM_DRIFT: wallet delta 0, db_pnl delta -$2.11, total delta -$0.60. |-$0.60 - (-$2.11)| = $1.51 < $5 ✓ (delta difference is unrealized MTM drift on open positions)

### One-line summary
Iter 35: 🚨 #3150 KING CS ex-RUBY closed -$2.11 ZERO (5th total-loss of session, cumulative -$9.87). Today -$9.86 / 12 closes / 1 win. **Correction**: scheduler is alive — brain cycle fired 4 decisions at 13:11:55 (TIGHTEN KING + 3 logged PAUSEs), reconcile/outcome/auto_tuner all active. Iter 34's "APScheduler failure" diagnosis was a grep-window artifact. **Settings writer identified**: auto_tuner runs after brain and writes the TIER maps → explains iter-28 revert partially (alongside lifecycle bypass). 636 blocks this iter (95% retired-roster). Portfolio $90.39 (Δ -$0.60). KING lost a 7d win, now -$16.62.

---

## Iteration 34 — 2026-04-13 15:33 UTC (Δt ≈ 28 min) — #3150 recovered half the drop. Activity collapse. Reconcile now also silent.

### Snapshot
- Portfolio: **$90.99** (Wallet $67.47 + Positions $23.52), Δ **-$0.36** since iter 33
- Today PnL: -$7.75 unchanged. 11 closes / 1 win. **No new close for 4h 40min** (since #3146 at 10:53:35)
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` unchanged (5+ hours stable)

### #3150 recovered: 0.32 → 0.55 (+$0.79 MTM)
```
id=3150 trader=KING7777777 category=cs status=open
entry=0.617  current=0.55 (was 0.32 in iter 33)
unrealized_pnl_mtm ≈ -$0.23 (was -$1.02)
```

CS ex-RUBY vs Metizport BO3 swung +23pp on chain in the 27-min gap. MTM recovery of +$0.79 on $2.11 size. Still underwater (-$0.23 / −11%) but no longer the -48% disaster from iter 33. Position stays open.

**Portfolio math check**: wallet flat ($67.47), positions -$0.36. #3150 recovered +$0.79, so the rest of positions (which includes the 27 ghost positions) dropped ~$1.15 MTM. Normal noise — ghost positions are on chain and re-valued each read.

### Activity COLLAPSE: 47 blocks in 28 min = 1.74/min
**7.5× drop** from iter 33's 13.0/min (352 blocks in 27 min). Breakdown:
- sovereign2013: 23 (49%)
- xsaghav: 19 (40%)
- KING: 5 (11%)
- Jargs: 0

Reasons: price_range 24, category_blacklist 10, event_timing 7, conviction_ratio 2, min_trader_usd 2, no_rebuy 2. **Zero exposure_limit hits this iter** (iter 33 had 13, iter 32 had 20) → sov/xsag exposure is now saturated, they've stopped trying to add to positions. 

### NEW trades / scores / brain decisions — all zero
- copy_trades: 0
- trade_scores: 0 (coverage static at 74/124 = 59.7%)
- brain_decisions: 0

Second iter in a row with 0 new scores. Second iter with no brain activity.

### 🚨 Reconcile also silent now (scheduler problem widening)
```
Latest reconcile visible: 12:43:54 (same as iter 33)
Expected runs since: 13:13, 13:43, 14:13, 14:43, 15:13 — ALL missing
Elapsed since last run: ~2h 50min
Expected interval: 30 min
```

Up to iter 32, reconcile was firing every 30 min. Iter 33 saw one run at 12:43:54. Iter 34 sees the SAME run — no newer one. **Reconcile has also stopped firing.** Combined with brain silence (last cycle 11:11:55, now 4h 21min ago), this strongly suggests:

**Scheduler-level failure**, not individual job drops. APScheduler lost multiple jobs or the scheduler itself stopped processing them. The bot is still running (WebSocket, blocks, copy paths alive per block counts) — but the scheduled background jobs (brain, reconcile, possibly others) are not firing.

Key things to check next session:
1. `scheduler.get_jobs()` state (was initially 5+ jobs in main.py)
2. APScheduler logs for "Job execution" / "Maximum number of running instances"
3. Whether `brain_engine`, `reconcile_db_wallet`, `outcome_tracker`, `ml_trainer` are all silent or just some
4. systemd watchdog timing / did the last restart at 11:06:43 coincide with a job drop?

### Trader 7d rolling (all unchanged)
| Trader | n | Wins | PnL |
|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 |
| Jargs | 17 | 8 | -$10.67 |
| xsaghav | 181 | 79 | -$57.90 |
| sovereign2013 | 173 | 79 | -$43.62 |
| fsavhlc | 20 | 8 | -$21.05 |

### Feedback coverage: 74/124 = 59.7% (stable, no new rows)

### Flags
- [x] **ACTIVITY_COLLAPSE**: block rate 13.0 → 1.74/min (7.5× drop). Retired traders hit exposure saturation or match slate emptied.
- [x] **#3150_RECOVERED**: KING CS ex-RUBY BO3 swung back from 0.32 → 0.55. Unrealized now -$0.23 vs iter 33's -$1.02.
- [x] **🚨 RECONCILE_NOW_SILENT_TOO**: no reconcile run since 12:43:54 (expected every 30 min). Combined with brain silence, points at systemic APScheduler issue.
- [x] **BRAIN_SILENCE_4H_21M**: still no brain cycle. Now definitively crossed 2 missed cycles (13:11 + 15:11).
- [x] **LONG_DRY_SPELL**: 4h 40min since last close. Only 1 win all day. Portfolio drifting -$0.36 this iter on ghost MTM noise.
- [ ] BOT_CRASHING (0 errors)
- [ ] NEW_TRADES (0)
- [ ] PHANTOM_DRIFT (-$0.36 within noise, no realized movement)

### One-line summary
Iter 34: Quiet iter. Block rate collapsed 13→1.74/min (retired-roster saturation). #3150 recovered half the drop (0.32→0.55, unrealized -48%→-11%). **🚨 Reconcile now also silent** since 12:43:54 (~2h 50min gap vs 30-min expected) — combined with brain silence, strongly suggests APScheduler-level failure affecting multiple jobs. 0 new trades/closes/scores/brain decisions. Portfolio $90.99 (Δ -$0.36 ghost MTM noise).

---

## Iteration 33 — 2026-04-13 15:05 UTC (Δt ≈ 27 min) — #3150 KING bleeding unrealized -48%. Block rate escalating. Brain silence 4h.

### Snapshot
- Portfolio: **$91.35** (Wallet $67.47 + Positions $23.88), Δ **-$0.64** since iter 32
  - Wallet +$0.06 (minor)
  - Positions **-$0.70** (almost all from #3150 mark-to-market drop)
- Today PnL: **-$7.75** unchanged (0 new closes, 11/1 win still)
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` unchanged (4+ hours stable)

### 🚨 #3150 KING CS unrealized -48% (MTM)
```
id=3150 trader=KING7777777 category=cs status=open
entry=0.617  current=0.32  size=$2.11 → MTM≈$1.09
unrealized_pnl = −$1.02 (≈48% of size)
```

"Counter-Strike: ex-RUBY vs Metizport (BO3) - European ..." — ex-RUBY (KING's side at 0.62) has collapsed to 0.32 on chain. If/when this closes, KING takes ~-$1.02 realized. If the BO3 resolves to 0, -$2.11 total loss (another zero-close). This is why the portfolio drifted -$0.64 today despite no realized closes.

**Note**: #3150 is a BO3 (best-of-three) series market, not a map. BO3s resolve on the series winner, not per-map. Zero-risk filter (cs/lol/valorant/dota < 0.40) would NOT have caught this because entry was 0.617, well above threshold. The filter is working as designed — just targets a different failure mode (underdog map total-loss, not BO3 price collapse).

### NEW trades
**None this iter.** max_id still 3175.

### 🚨 Block rate escalating further: 352 in 27min = **13.0/min** (iter 32 was 10.5)
- sovereign2013: **176** (50%)
- xsaghav: **125** (36%)
- KING: 51 (14%)
- Jargs: 0

Same breakdown: retired traders dominate. 301/352 = 85% from retired.

Reasons:
- price_range: 164 (47%)
- category_blacklist: 92 (26%) — KING/lol + xsaghav/valorant + sov/nhl|soccer blacklists all biting
- event_timing: 52 (15%)
- no_rebuy: 27
- exposure_limit: 13
- conviction_ratio: 2, min_trader_usd: 2

**Zero-risk hits still 0 all-time.** The filter is armed but isn't seeing matching candidates (traders' entries are above 40¢ on the esports categories they trade).

### ⚠️ 0 new scores — filters reject before scorer runs
**0 rows added to trade_scores** in 27 min despite 352 block attempts. This confirms the code path: filters (price_range, category_blacklist, etc.) run **before** the scoring step in the buy pipeline. All 352 candidates were rejected pre-scoring.

This is architecturally expected but worth noting — it means **zero trade_scores growth when all candidates fail early filters**. The scorer's feedback dataset can only grow from trades that pass filters. With the reverted retired roster thrashing against tightened filters, the scorer is starved.

### 🎉 Feedback coverage RECOVERED: 51.6% → **59.7%** (+8.1pp)
- `SCORER_FEEDBACK: {"total": 124, "with_outcome": 74}` — 10 previously-NULL outcome rows got populated despite 0 new scores.

**Root cause**: `outcome_tracker` backfill is working. Markets that had scored candidates resolved during the iter-32→33 window, and `update_trade_score_outcome` (or the `backfill_trade_score_outcomes` batch helper from Round 4) stamped 10 rows with their realized PnL.

This is the FIRST recovery in the coverage trajectory (98.4 → 92.6 → 75.0 → 54.3 → 51.6 → **59.7**). Coverage trajectory going forward depends on whether the SCORE_DEDUP_TTL_EDGE fires again; with 0 new scores this iter, nothing was added to dilute it.

### Brain silence — now 3h 53min
- Last brain activity: **2026-04-13 11:11:55** (decision #488)
- Current time: ~15:05
- Elapsed: **3h 53min**
- Expected cycles: 13:11, 15:11 — both either missing (13:11) or not yet due but overdue by the interval math (15:11 is 4min away at time of query)
- `journalctl -g BRAIN --since 60m` → **empty**. No log lines whatsoever.
- No errors in the last 10 min

**Diagnosis**: scheduler job is almost certainly dropped. No brain activity for 4 hours across multiple iters with a clean error log points at silent job removal (APScheduler behavior when a job errors during a run can deregister the job). **Needs scheduler inspection next session** — `scheduler.get_jobs()` from a Python shell, or check `main.py` for how brain is scheduled.

### Trader 7d rolling — xsaghav window rotation continues
| Trader | n | Wins | PnL | Δ vs iter 32 |
|---|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 | 0 |
| Jargs | 17 | 8 | -$10.67 | 0 |
| xsaghav | 181 | 79 | **-$57.90** | **+$7.99** (n 182→181, one more old trade aged out) |
| sovereign2013 | 173 | 79 | -$43.62 | 0 |
| fsavhlc | 20 | 8 | -$21.05 | 0 |

Combined 7d: **-$156.01** across 519 trades (improved from -$172 due to the xsaghav window shifts, but still all 5 negative).

### Reconcile: +1 ghost, +$0.40 value
- Latest: **12:43:54 → 28 ghosts / $19.01** (iter 32 was 27 / $18.61)
- One new ghost added. Most likely a position that closed in the DB during iter 32/33 but wasn't actually sold on-chain. Same bug as the $22 baseline but incremental. Not alarming alone but worth tracking.

### Flags
- [x] **KING_3150_UNREALIZED_MINUS_48**: MTM drop 0.617 → 0.32 on CS ex-RUBY BO3. If it closes at 0, another -$2 realized loss.
- [x] **BLOCK_RATE_ESCALATING**: 0.85/min → 10.5/min → 13.0/min across iters 31→33. Retired traders driving 85% of the load.
- [x] **🚨 BRAIN_SILENCE_3H53M**: no brain activity in 3h 53min. Scheduler likely dropped the job. High-confidence anomaly.
- [x] **FEEDBACK_COVERAGE_RECOVERED**: 51.6% → 59.7% — first recovery in the trajectory. `outcome_tracker` backfill is working.
- [x] **NO_NEW_SCORES**: 0 scores written despite 352 blocks — confirms filter-before-score path; retired-roster candidates are rejected pre-scoring.
- [x] **RECONCILE_GHOST_PLUS_1**: 27→28 ghosts, $18.61→$19.01. Small incremental DB↔chain gap growth.
- [ ] BOT_CRASHING (0 errors)
- [ ] PHANTOM_DRIFT: wallet +$0.06, positions -$0.70 → net -$0.64. db_pnl_delta = 0 (no new closes). |-$0.64 − 0| = $0.64 < $5 but **this is unrealized, not reportable loss** ✓
- [ ] NEW_CLOSES (0 in 4h 12min — since #3146 at 10:53:35)

### One-line summary
Iter 33: Portfolio $91.35 (Δ -$0.64, all from #3150 KING CS ex-RUBY unrealized bleed 0.617→0.32 MTM = −$1.02 unrealized). 0 new trades/closes. **Block rate 13.0/min** (retired roster 85% share). **Brain dead silent 3h 53min — scheduler job almost certainly dropped**. ⚠️ 0 new scores (filter-before-scorer). 🎉 Feedback coverage recovered 52→60% via outcome_tracker backfill. Reconcile ghosts 27→28 / $18.61→$19.01 (slight drift).

---

## Iteration 32 — 2026-04-13 14:38 UTC (Δt ≈ 3 min⁎) — 🚨 #3175 closed -$0.71, blocks exploded 12×, brain silence now 4h+

⁎ Wakeup fired earlier than expected (wakeup was 14:38 based on last ScheduleWakeup). The data below captures accumulated activity since iter 31 at 14:35 — ~3 min of wall time but the DB data reflects changes that happened continuously since iter 30's snapshot at 14:08.

### Snapshot
- Portfolio: **$91.99** (Wallet $67.41 + Positions $24.58), Δ **-$1.06** since iter 31
  - Wallet: +$0.28 (from #3175 sell proceeds)
  - Positions: **-$1.34** (#3175 removed from positions + #3150 mark-to-market drop)
- Today PnL: **-$7.75** (Δ -$0.71 — matches #3175 realized loss exactly)
- Today closes: **11** (+1), 1 win still
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` unchanged for 3+ hours — no writes
- Reconcile: ✅ new run at **12:13:54** visible in log (reconcile alive, answering iter 30-31 uncertainty)

### 🚨 #3175 closed — retired-trader capital deployment realized
```
id=3175 trader=sovereign2013 category="" entry=0.567 size=$1.00
bought 11:59:05 → closed 12:14:38 (15-min hold)
pnl_realized = -$0.71 (71% of size lost)
```

**Cost of the revert so far** = -$0.71 realized. Fast close, deep loss. The Rouen Open Kasatkina market resolved or swung hard against sov within 15 min. This is the first realized loss attributable to the reverted roster — memory's "89% ghost-close rate" warning made concrete: sov's tennis strategy is in the loss-heavy bucket, the revert just cost $0.71 on $1 deployed.

### 🚨 Block EXPLOSION: 12× jump vs iter 31
- **315 new blocks in ~30min = 10.5/min** (iter 31 was 0.85/min, 12× increase)
- sovereign2013: **138** (44%)
- xsaghav: **108** (34%)
- KING: **69** (22%)
- Jargs: 0

**Activity burst** — iter 31's lull ended decisively. All 3 retired-but-reverted traders are trading aggressively plus KING is scan-active too.

### New block reasons appearing
First time in this ralph series:
- **no_rebuy: 22** — traders attempting to rebuy a market within the 120-min NO_REBUY_MINUTES window (indicates repeated attempts on the same market)
- **exposure_limit: 20** — traders hitting `MAX_EXPOSURE_PER_TRADER` ceiling (indicates aggressive concentration attempts)

The other reasons:
- price_range: 153 (49%)
- category_blacklist: 66 (21%) — KING/lol and other blacklists biting
- event_timing: 50 (16%)
- conviction_ratio: 3
- min_trader_usd: 1

**Interpretation**: with 5 active traders and a busy match slate, the filter matrix is working hard. Most blocks (249/315 = 79%) are from retired traders. If roster were cleaned, iter 32 block volume would be ~69 (KING only) instead of 315.

### Scores: only 2 (and dedup is working well now)
2 rows / ~30 min / 2 unique (trader, cid) pairs. **Score dedup is holding** — no repeat rows for the same triple. Iter 30's TTL edge was a specific long-running QUEUE edge case; when scoring is intermittent (gaps > 60s), dedup collapses normally.

### Feedback coverage
**64/124 = 51.6%** — unchanged ratio vs iter 31 (+1 outcome from #3175, +2 NULL from new QUEUE). Bleed stopped.

### 🚨 Brain silence — 4h+ and counting
- Last brain activity: **2026-04-13 11:11:55** (decision #488)
- Current time: **~14:38** (iter 32)
- **Elapsed: 3h 26min**
- Expected interval: 2h → should have fired at ~13:11, ~15:11
- **13:11 cycle is definitively missing**
- No `[BRAIN]` log lines in the last 40 min grep window

`journalctl ... -g 'brain_engine|Brain Engine'` returned **empty** for the 40-min window. This confirms iter 31's suspicion: **brain is not firing**. Either:
1. Scheduler job dropped (APScheduler job removed/replaced on restart)
2. Brain exception silently swallowed (but no ERROR in logs)
3. Brain lock file or flag preventing execution

No ERROR lines in recent logs. Needs next-session investigation — possibly check the APScheduler state via `jobs = scheduler.get_jobs()` call.

### Trader 7d rolling — xsaghav window rotation jumps +$21.82
| Trader | n | Wins | PnL | Δ vs iter 31 |
|---|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 | 0 |
| Jargs | 17 | 8 | -$10.67 | 0 |
| **xsaghav** | 182 | 79 | **-$65.89** | **+$21.82** (large older loser aged out of 7d window) |
| sovereign2013 | 173 | 79 | -$43.62 | **-$3.62** (from #3175 close -$0.71 + window shifts) |
| fsavhlc | 20 | 8 | -$21.05 | 0 |

xsaghav's jump is pure 7d-window rotation (one trade `n` dropped 183→182, suggesting an older loser aged out). Not real improvement.

### Reconcile ✅ alive
New log line confirmed at **12:13:54**: samples still include Iran/Qatar ($2.45) and Lopez Aliaga Peru ($2.00). 27 ghosts. No change to the 27/$18.61 ballpark. **Dismisses iter 30's brief scare that reconcile might be broken** — just was outside my grep window last time.

### Flags
- [x] **🚨 RETIRED_TRADER_REAL_LOSS**: #3175 sov2013 closed -$0.71 (71% of $1 size). First realized cost of the roster revert.
- [x] **BLOCK_EXPLOSION**: 315 blocks in 30min (12× jump from iter 31). Lull broke, activity burst with new `no_rebuy` + `exposure_limit` reasons appearing.
- [x] **🚨 BRAIN_SILENCE_CONFIRMED**: 3h 26min since last brain activity. 13:11 expected cycle missing. `journalctl -g brain_engine` returns empty. Scheduler issue likely.
- [x] **WINDOW_ROTATION**: xsaghav 7d PnL jumped +$21.82 not from new wins but from old loser rotating out
- [x] **RECONCILE_ALIVE** (dismisses iter 31 concern): new run at 12:13:54
- [ ] BOT_CRASHING (0 errors)
- [ ] BRAIN_MUTEX still VERIFIED (from iter 31)
- [ ] FEEDBACK_COVERAGE_STABLE at 51.6% (bleed stopped)
- [ ] ZERO_RISK_HITS (still 0 all-time)
- [ ] PHANTOM_DRIFT: wallet_delta +$0.28 + positions -$1.34 = -$1.06, db_pnl_delta -$0.71. |−$1.06 − (−$0.71)| = $0.35 < $5 ✓

### One-line summary
Iter 32: 🚨 #3175 sov2013 tennis closed **-$0.71** (first realized loss from reverted roster, 15-min hold, 71% of size). Block explosion 12× to 315 new blocks (249 from retired traders). Brain silence hit 4h+ (13:11 expected cycle missing, grep returns empty). Reconcile confirmed alive with new 12:13:54 run. Portfolio $91.99 (Δ -$1.06). xsaghav 7d PnL jumped +$21.82 from pure window rotation (no real improvement). Brain mutex still verified from iter 31.

---

## Iteration 31 — 2026-04-13 14:35 UTC (Δt ≈ 27 min) — 🎉 Brain mutex VERIFIED in prod log

### Snapshot
- Portfolio: $93.05 (Wallet $67.13 + Positions $25.92), Δ **+$0.11** since iter 30 — drift from #3175 position revaluation
- Today: 10 closes, 1 win, -$7.04 — **no new closes in 3h 41min** (#3146 at 10:53:35 still the latest)
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` **unchanged** since 11:11:55 — no further writes
- Reconcile: last visible run still 11:43:54 (no newer run in 45-min grep window — possibly stale log or scheduler skip, not confirmed broken)

### 🎉 BRAIN_OSCILLATION_MUTEX — VERIFIED WORKING IN PROD

Pulled brain log lines from the 11:11:55 cycle (the one that produced decision #488). The full sequence:

```
[BRAIN] Would pause sovereign2013: 5 consecutive losses (DISABLED — settings managed manually)
[BRAIN] Would pause xsaghav: 7d PnL $-87.71 < -$20 (DISABLED — settings managed manually)
[BRAIN] Would pause fsavhlc: 7d PnL $-21.05 < -$20 (DISABLED — settings managed manually)
[BRAIN] Score range performance:
[BRAIN]   60-79: 1 trades, 0 wins, 0.0% WR, $-2.35 PnL
[BRAIN] Autonomous: 0 trades, 0 wins (0.0%), PnL=$0.00
[BRAIN] Skipping RELAX for KING7777777 — was TIGHTENED this cycle   ← 🎯 MUTEX FIRED
[BRAIN] === Brain Engine complete ===
```

**This is the exact log line my `test_revert_skips_trader_in_mutex` regression test asserts.** Commit `c003e0a` `_tightened_this_cycle` mutex is firing in prod as designed. KING was TIGHTENED earlier in the cycle (in `_classify_losses()`) and the mutex short-circuited the RELAX path in `_revert_obsolete_tightens()`.

**Missing detail**: the TIGHTEN_FILTER decision row is NOT in `brain_decisions` table (#487 is a gap, #488 is BLACKLIST_CATEGORY). Either:
- The TIGHTEN write was deduped by the 3h window from a prior cycle's decision (the cross-cycle dedup from `ba70dbf`)
- The TIGHTEN attempt silently failed (e.g., `new_min >= new_max` guard at `_tighten_price_range:324`)

Either way, the `_tightened_this_cycle.add(trader)` happens in `_classify_losses` BEFORE the log_brain_decision call — so the mutex gets populated even if the decision write gets suppressed. That's why RELAX was still skipped even though TIGHTEN didn't land as a new row. The mutex **uses in-memory state**, not the brain_decisions table.

**This is the 5th iter the mutex has been waiting to fire** (iters 27-30 had no TIGHTEN or RELAX calls). First definitive empirical proof. Closing the verification loop on all 3 morning-session fixes:
- ✅ `log_blocked_trade` dedup (verified iter 25/26 — 19× reduction)
- ✅ `log_trade_score` dedup (verified iter 25 — 86 → N rows/min, but see SCORE_DEDUP_TTL_EDGE below)
- ✅ **`brain_oscillation_mutex`** (verified iter 31 — **this log line**)

### Brain silence anomaly (carry-over from iter 30)
- Last brain decision/activity: 11:11:55
- Current time: ~14:35
- Elapsed since last cycle: **3h 23min**
- Expected cycle interval: 2h
- **Next cycle is now overdue by ~1h 23min**

Possible causes: scheduler reset on restart, brain exception swallowed silently, or the `brain_engine` scheduler job got disabled. No ERROR lines in recent logs. Cannot diagnose from ralph — need code/log deeper dive next session.

### New trades
**None.** #3150 KING cs ex-RUBY still open, #3175 sov tennis Kasatkina still open. No new buys, no new closes.

### NEW blocked trades — activity slowed significantly
**23 new blocks in 27 min = 0.85/min** — vs iter 30's 5.5/min. 6.4× drop.
- sovereign2013: 10 (43%)
- KING7777777: 7 (30%)
- xsaghav: 6 (26%)

Reasons: price_range 12, category_blacklist 5, event_timing 5, conviction_ratio 1

Interpretation: either (a) natural lull between match batches, (b) many duplicate keys are caching at the dedup layer, or (c) traders themselves are just not trading. The block-per-trader ratios look normal so it's most likely (a).

### NEW scores (6)
6 rows / 27 min / 2 unique (trader, cid) pairs = avg 3 rows per triple. Down from iter 30's 16 rows per triple. **Dedup pressure working as designed at this lower volume** — most duplicates within 60s are caught, the edge case only triggers when scoring fires faster than once per 60s for 16+ minutes on the same cid.

### Feedback coverage
**63/122 = 51.6%** — down from 54.3% but **slower bleed rate** (−2.7pp this iter vs −21pp last iter). Recovery trajectory depends on whether the TTL edge continues to trigger on sustained QUEUE markets.

### Trader rolling 7d (all unchanged)
| Trader | n | Wins | PnL |
|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 |
| Jargs | 17 | 8 | -$10.67 |
| xsaghav | 183 | 79 | -$87.71 |
| sovereign2013 | 173 | 80 | -$40.00 |
| fsavhlc | 20 | 8 | -$21.05 |

### Flags
- [x] **🎉 BRAIN_MUTEX_VERIFIED**: "Skipping RELAX for KING7777777 — was TIGHTENED this cycle" found in production log. First empirical proof of fix `c003e0a`.
- [x] **BRAIN_SILENCE_ANOMALY**: 3h 23min since last brain activity, 1h 23min overdue. No errors in log. Root cause unknown.
- [x] **FEEDBACK_COVERAGE_STABILIZING**: 54.3% → 51.6% (−2.7pp, was −21pp). TTL edge bleed slowing as activity drops.
- [x] **ACTIVITY_LULL**: 23 blocks + 0 trades + 6 scores in 27min vs 158/1/32 in the 29-min iter 30 window. 7× drop across the board.
- [x] **RETIRED_ROSTER_STILL_ACTIVE**: xsaghav, sov2013, fsavhlc all still `followed=1` in wallets table. No new buy this iter but still generating blocks.
- [ ] BOT_CRASHING (0 errors)
- [ ] NEW_CLOSES (0 in ~4 hours)
- [ ] PHANTOM_DRIFT (+$0.11 within noise)
- [ ] ZERO_CLOSE_CLUSTER
- [ ] MAX_DAILY_LOSS_TRIGGER

### One-line summary
Iter 31: 🎉 Brain intra-cycle mutex VERIFIED in prod log ("Skipping RELAX for KING7777777 — was TIGHTENED this cycle" fired at 11:11:55, matches my regression test assertion exactly). Activity lull — 0 new trades, 23 blocks, 6 scores in 27min. No new brain cycle since 11:11:55 (now 1h 23min overdue — brain silence anomaly, no root cause yet). Feedback bleed slowing 54→52%. Portfolio $93.05 flat.

---

## Iteration 30 — 2026-04-13 14:08 UTC (Δt ≈ 29 min) — 🚨 RETIRED ROSTER ESCALATION: sov2013 actually bought

Iter 29 showed the reverted roster burning scan cycles. Iter 30 shows it actually **spending money**. This is the escalation.

### Snapshot
- Portfolio: $92.94 (Wallet $67.13 + Positions $25.81), Δ **+$0.02** since iter 29 — flat
- Wallet delta: **-$1.00** (from $68.13 → $67.13) — matches the size of #3175 exactly
- Positions delta: **+$1.01** — #3175 buy absorbed into on-chain positions
- Today PnL: -$7.04 unchanged, 1 win (still #3146 only), no new closes in 3+ hours
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` **unchanged** since iter 29 — no further mystery writes
- Reconcile: 27 ghosts / $18.61 stable

### 🚨 NEW buy from retired trader — #3175 sovereign2013

```
id=3175 trader=sovereign2013 category=tennis entry=0.567 size=$1.00 status=open
market="Open Capfinances Rouen Metropole: Daria Kasatkina ..." @ 11:59:05
```

**Escalation**: the reverted roster has moved from "causing blocks" (iter 29) to **actively deploying capital** (iter 30). sov2013 was retired in `e2c6129` but silently re-added via the lifecycle bypass (fix `60158e2` closed the bypass but didn't retire the re-added entries). Filter matrix for sov currently on server:
- `MIN_ENTRY_PRICE_MAP: sovereign2013:0.42` — 0.567 ✓
- `MAX_ENTRY_PRICE_MAP: sovereign2013:0.70` — 0.567 ✓
- `CATEGORY_BLACKLIST_MAP: sovereign2013:nhl|soccer` — tennis not blocked ✓
- `MIN_CONVICTION_RATIO_MAP: sovereign2013:0.5` — not evaluable here
- Not hit by `zero_risk` because tennis isn't in that category list

The buy passed every filter. That's expected — the filters are tuned for sov's regular behavior. The issue is that **sov shouldn't be followed at all** (7d PnL -$40, retired in this session). Each non-zero buy from a retired trader is $1-3 of capital at risk with the worst historical EV of the 5 traders.

**Accumulating cost of the revert** if unaddressed: given the block rate (89 sov2013 blocks → 1 actual buy) plus similar rates for xsaghav and fsavhlc, and assuming linearly ≥$1 per buy, the revert is costing roughly **1-3 new open positions per hour** from retired traders. Over a trading day this could deploy $10-30 of fresh capital into the losing-est historical traders.

### Every other new trade/transition
Just #3175 above. #3150 still open. No new closes.

### NEW blocked trades (158 in 29 min = 5.5/min)
- **sovereign2013: 89** (56% of blocks — bulk of filter pressure)
- **xsaghav: 40** (25%)
- KING: 29 (18%)
- Jargs: 0

Block reasons:
- price_range: 81 (51%)
- category_blacklist: 45 (28%) — the KING/lol blacklist from brain decision #488 is firing
- event_timing: 26 (16%)
- conviction_ratio: 3
- min_trader_usd: 3

**Zero-risk hits: 0 all-time still.** Nothing has tried to buy an esports underdog under 40¢ — filter is still a silent guard. Note: since KING's `lol` is now blacklisted entirely by brain, the zero-risk filter for LoL is effectively redundant for KING. It would still catch cs/valorant/dota for KING, or lol for Jargs.

### NEW trade_scores (32)
All 32 rows are `QUEUE` action, but only **2 unique (trader, cid, action) triples**. Average 16 rows per triple in 29 min = 1 row per ~1.8 min. **TTL edge still bleeding** but slightly less aggressively than iter 29's exact 1/min — the scorer is firing less often within the TTL window, so occasional 2-min gaps let the cache stay valid.

Feedback coverage: **63/116 = 54.3%** — down from 75.0% in iter 29. **Coverage loss rate: ~20pp per iter.** At this rate, the metric will cross back below the 20% FEEDBACK_DYING threshold within ~2-3 more iters unless the dedup TTL fix lands.

### NEW brain decisions (0)
No new decisions since #488 at 11:11:55. Expected next cycle around 13:11 (2h after #488) — haven't reached that yet (current time ~14:08 UTC, so next cycle should have fired around 13:11, but didn't). Either:
1. Brain scheduler interval is longer than 2h now
2. Bot restart reset the clock
3. Brain is silently failing

No errors in the log suggest 1 or 2. Next iter should reveal.

### Trader 7d rolling (all 5 now active, all 5 negative)
| Trader | n | Wins | PnL | 7d WR | Verified note |
|---|---|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 | 40.6% | verified +$26 per memory — brain signal is wrong |
| Jargs | 17 | 8 | -$10.67 | 47.1% | — |
| xsaghav | 183 | 79 | **-$87.71** | 43.2% | highest $ bleed |
| sovereign2013 | 173 | 80 | -$40.00 | 46.2% | just added #3175 |
| fsavhlc | 20 | 8 | -$21.05 | 40.0% | — |

Combined: **523 closed trades, -$172 realized**. (Matches memory finding "5 trader roster bleeds -$182/7d".)

### Reconcile
Latest visible: 11:43:54 UTC → 27 ghosts / $18.61. Stable. No change since iter 29.

### Flags
- [x] **🚨 RETIRED_TRADER_ACTIVE_BUY**: #3175 sov2013 tennis $1.00 — first actual capital deployment from a retired trader since the revert. Escalation from iter 29's "wasted scan budget" to actual capital risk.
- [x] **FEEDBACK_COVERAGE_BLEED**: 98.4% → 92.6% → 75.0% → **54.3%** over 4 iters. Score dedup TTL edge pollution. Will cross FEEDBACK_DYING threshold soon if not fixed.
- [x] **BRAIN_BLACKLIST_KING_LOL_ACTIVE**: 45 blocks in 29 min on category_blacklist — mostly the KING/lol blacklist from brain #488 firing on retired-trader-generated trade attempts. Brain blacklist working but the cost-benefit is inverted (blacklists the one category KING just won).
- [x] **SCORE_DEDUP_TTL_EDGE_CONFIRMED** (continuing from iter 29): 32 rows / 2 unique triples = 16:1 row-to-state ratio
- [ ] BOT_CRASHING: 0 errors
- [ ] BRAIN_SPAM: 0 decisions this iter
- [ ] BRAIN_OSCILLATION (neither TIGHTEN nor RELAX fired this iter — mutex still unverifiable)
- [ ] PHANTOM_DRIFT: wallet_delta=-1.00 (matches #3175 exactly) ✓
- [ ] WR_DROP (nobody shifted ≥5pp)
- [ ] FILTER_TOO_TIGHT: 158 blocks / 1 real buy / 0 closes — filter pressure is nearly absolute

### One-line summary
Iter 30: 🚨 sov2013 **actually bought** (#3175 tennis $1, wallet -$1 exactly) — reverted roster escalated from scan-budget waste to capital deployment. 158 blocks this iter (89 sov, 40 xsag, 29 KING). Feedback coverage hemorrhaging 98→54% in 4 iters from score dedup TTL edge. Brain silent (no cycle fired since 11:11:55). Portfolio $92.94 flat. **Roster re-clean + lifecycle fix deploy status verification needed now** — each hour of inaction means 1-3 more retired-trader capital deployments.

---

## Iteration 29 — 2026-04-13 13:39 UTC (Δt ≈ 15 min) — Brain blacklisted KING/lol right after KING's first LoL win. Score dedup TTL edge confirmed.

### Snapshot
- Portfolio: $92.92 (Wallet $68.13 + Positions $24.80), Δ **+$0.55** since iter 28 — positive drift despite reverted roster (no new buys landed, just filtered blocks + slight position revaluation)
- Today PnL: -$7.04 unchanged (0 new closes this iter)
- Today closes: 10, 1 win (#3146 still the only one)
- Bot errors last 10min: **0**
- Settings hash: `ffca70f7...` (was `e0dde1c7...` in iter 28 — another write)
- Settings mtime: **2026-04-13 11:11:55** — **exact same timestamp as brain decision #488** below → confirms brain writes settings.env

### New context from updated memory (acknowledged)
- **Lifecycle bypass fix shipped** (commits `60158e2` + `a0ea171`): `_check_paper_to_live()` and `_add_followed_trader()` both gated behind `AUTO_DISCOVERY_AUTO_PROMOTE`. The revert I flagged in iter 28 predates this fix — it was exactly the bypass the fix closes. Going forward new promotions are blocked, but the **already-reverted 5-trader roster is still active** because the fix doesn't retroactively retire them.
- **89% ghost-close rate real bleed**: 552/618 closed trades have `usdc_received=NULL` (~$515 size). The $18.61 reconcile number is just the tip — most of the "closes" are never actually sold on-chain.
- **Scorer IS inverse-correlated** on the 63 outcome-stamped rows (80-100 bucket = 0% WR / -$47.90, 60-79 = 80% WR / +$3.95). My iter-25 debunk was wrong; memory has the corrected analysis.
- **KING is actually verified-profitable** (+$26.21 across 23 verified trades) but brain sees the DB-estimated -$15 and acts on that.

### NEW closed/open trades
**None this iter.** #3146 already closed (+$0.56), #3150 still open. 16 QUEUE scores for KING ex-RUBY Map 2 (see below) never became actual buys.

### 🚨 NEW brain decision #488: BLACKLIST_CATEGORY KING7777777/lol @ 11:11:55

```
id=488 action=BLACKLIST_CATEGORY target=KING7777777/lol
reason="Brain: KING7777777 WR < 40% in lol" created_at=2026-04-13 11:11:55
```

Timeline:
- **10:53:35**: #3146 KING LoL Nongshim vs Hanwha Life closed **+$0.56** (KING's first winning LoL trade visible in the recent feedback cohort)
- **11:11:55** (18 min later): Brain reads `copy_trades` for KING/lol, sees ~117 historical LoL trades with DB-estimated WR<40%, blacklists the category.

**Perfect illustration of the memory finding**: brain acts on DB-estimated `pnl_realized` (corrupted by 89% ghost-closes) rather than verified outcomes. KING's verified LoL win (+$0.56, real sell) was immediately drowned out in the brain's window by 100+ ghost-closed LoL rows with estimated losses. Net result: brain blacklists the category in which KING just printed a real win.

Confirmed this is the writer: `brain._add_category_blacklist()` calls `_update_setting("CATEGORY_BLACKLIST_MAP", ...)` which rewrites all of settings.env. The settings file mtime matches the decision timestamp to the second.

**Note**: brain decision ID #487 is missing from the sequence (gap between #486 and #488). Possible causes: silent rollback, dedup guard silently failed insert, or sqlite autoincrement skipped. Not investigating — just noted.

### 🚨 NEW blocked trades — retired roster is actively burning scan budget

86 new blocks in ~15 min (5.7/min). **81 of 86 from the reverted-roster traders**:
- **sovereign2013: 58** (!!) — 58 blocks in 15 min = 3.9/min for one trader
- **xsaghav: 23**
- KING: 5

Block reasons:
- price_range: 50 (mostly sov/xsaghav trying to enter outside their reverted maps)
- category_blacklist: 19 (mostly the KING/lol blacklist just fired above)
- min_trader_usd: 7
- conviction_ratio: 6
- event_timing: 4

The revert is **actively costing us** in terms of scan cycles and block-log I/O. Without the revert these 81 blocks wouldn't exist because sov+xsaghav wouldn't be scanned at all. This is the exact scenario the roster shrink in `e2c6129` was supposed to prevent — now undone by the pre-fix bypass.

**Zero-risk hits: 0 all-time still.** No esports underdog under 40¢ has been attempted.

### 🎯 CONFIRMED: SCORE_DEDUP_TTL_EDGE

16 new scores (#853-#868), all **exactly** one per minute:
```
853 11:20:46  QUEUE 45 ex-RUBY Map 2 @ 0.545
854 11:21:46  QUEUE 45 ex-RUBY Map 2 @ 0.545
855 11:22:46  QUEUE 45 ex-RUBY Map 2 @ 0.545
856 11:23:47  QUEUE 45 ex-RUBY Map 2 @ 0.545
857 11:24:56  QUEUE 45 ex-RUBY Map 2 @ 0.545
858 11:25:56  QUEUE 45 ex-RUBY Map 2 @ 0.545
...
868 11:35:56  QUEUE 45 ex-RUBY Map 2 @ 0.56
```

**Proof**: 16 minutes, 16 rows, Δt ≈ 60-70s each. Same (trader=KING, cid=ex-RUBY Map 2, action=QUEUE) triple. The 60s TTL lets the row through exactly once per minute instead of exactly once per state. **Dedup reduction effective: 16× → 16/min cap = 1× reduction** for this specific pattern (worse than I thought in iter 28). 

Fix recommendation (for next session): either (a) raise TTL to 600s for QUEUE action specifically, or (b) convert to debounce — only write when action changes. Option (b) is cleaner because long-running QUEUE really only needs one row total, not one per interval.

### Feedback coverage
**63/84 = 75.0%** — dropped from 98.4% in iter 27 and 92.6% in iter 28 due to the 16 new NULL QUEUE rows. If the score TTL edge isn't fixed soon, coverage will keep degrading every time a trader has a long-running QUEUE on a single market.

### Trader 7d rolling
| Trader | n | Wins | PnL | Note |
|---|---|---|---|---|
| KING7777777 | 128 | 52 | -$12.77 | verified-profitable +$26 per memory |
| Jargs | 17 | 8 | -$10.67 | unchanged |
| xsaghav | 183 | 79 | **-$87.71** | window rotated +$10.54 vs earlier iter (older large losers aged out) |
| sovereign2013 | 173 | 80 | -$40.00 | unchanged |
| fsavhlc | 20 | 8 | -$21.05 | unchanged |

### Reconcile
Latest run captured: **11:13:54 → 27 ghosts / $18.61**. One more ghost than iter 28's 26. Stable $18-22 range across iterations — pre-existing gap not growing.

### Flags
- [x] **BRAIN_VS_REALITY**: Brain blacklisted KING/lol 18 min after KING's first winning LoL real-sell. Operating on DB-corrupted signal (memory finding, now with live proof).
- [x] **ROSTER_REVERT_ACTIVE_BURN**: 81/86 blocks this iter from the reverted retired traders. Lifecycle fix prevents future promotions but doesn't retroactively retire the already-promoted.
- [x] **SCORE_DEDUP_TTL_EDGE_CONFIRMED**: 16 rows, 1/min exact, same triple. Specific failure mode documented.
- [x] **FEEDBACK_COVERAGE_DROPPING**: 98.4% → 92.6% → 75.0% across iters 27-29. TTL edge is the accumulating pollution source.
- [x] **BRAIN_WRITES_SETTINGS_CONFIRMED**: settings.env mtime exactly matches brain_decision.created_at — root-cause for iter 28's SETTINGS_REVERTED mystery partly identified. Brain preserves (not reverts) the 5-trader roster it reads; actual revert happened via lifecycle `_check_paper_to_live` bypass fixed in `60158e2`.
- [x] **BRAIN_DECISION_ID_GAP**: #487 missing between #486 and #488. Noted, not investigated.
- [ ] BOT_CRASHING (0 errors)
- [ ] BRAIN_SPAM (1 decision in 15 min, within norms)
- [ ] BRAIN_OSCILLATION (no TIGHTEN/RELAX fired, mutex still unverifiable empirically)
- [ ] PHANTOM_DRIFT
- [ ] MAX_DAILY_LOSS_TRIGGER
- [ ] FIRST_WIN_OF_DAY (stays from iter 28)

### One-line summary
Iter 29: Portfolio $92.92 (Δ +$0.55, drift-only). 0 new closes. Brain blacklisted KING/lol 18 min after KING's first winning LoL trade — perfect live example of "brain acting on corrupted DB signal". 16 QUEUE rows confirm SCORE_DEDUP_TTL_EDGE (1/min exact bypass). Feedback coverage bleeding 98→75% due to this pattern. 81/86 blocks from reverted retired traders burning scan budget. Roster still needs re-cleaning post-bypass-fix.

---

## Iteration 28 — 2026-04-13 13:24 UTC (Δt ≈ 32 min) — 🚨 ROSTER REVERT + first win of day

Two very different stories in one iter: the first day-win landed (+$0.56 real sell), AND my entire roster cleanup was silently reverted on the server by an unknown writer.

### Snapshot
- Portfolio: $92.37 (Wallet $68.13 + Positions $24.25), Δ **-$0.14** since iter 27
- Today PnL: **-$7.04** (Δ +$0.56 🎉), **1 win** (first of the day)
- Today closes: 10 (+1)
- Bot errors last 10min: **0**
- Settings hash: `e0dde1c7...` (was `3404b3af...` in iter 27) — **changed by unknown writer**

### 🎉 First win of the day
- **#3146 KING7777777 `lol` entry=0.587 closed=+$0.56 REAL_SELL** — "LoL: Nongshim Esports Academy vs Hanwha Life Esports Challengers" — closed 10:53:35
- **Breaks 4-trade zero-close streak AND is the first positive-PnL day-close.** Real sell, normal exit.

### New real close
(Just the one above — #3146.)

### 🚨 CRITICAL: ROSTER REVERT (unknown writer)

Post-iter-27 settings.env was reverted between 11:04 and 11:08 UTC. Current state of `FOLLOWED_TRADERS` on server:
```
FOLLOWED_TRADERS=Jargs:0xf1649daae29c44bdb406a4dbb7f1748eac398fa4,
  xsaghav:0xdbb36e465641957d32376f0e5d32a1f725ce76a9,
  sovereign2013:0xee613b3fc183ee44f9da9c05f53e2da107e3debf,
  KING7777777:0xad72ffe37df00548959c2f86f0333e7c958e4f5e,
  fsavhlc:0x40cfb29411d29f4fa0908f2a121297042cccd21d
```

**xsaghav, sovereign2013, fsavhlc are back**. The 2 whale entries (`0x3e5b23e9f7`, `0x6bab41a0dc`) did **not** return. `wallets.followed` also reverted for the 3 usernames but NOT the whales:
```
Jargs=1, KING7777777=1, fsavhlc=1, sovereign2013=1, xsaghav=1
0x3e5b23e9f7=0, 0x6bab41a0dc=0
```

Also reverted: `MIN_ENTRY_PRICE_MAP` and `MAX_ENTRY_PRICE_MAP` now list all 8 traders (including the 2 whales). KING's min got loosened from 0.43 → 0.38 as a side effect of the rewrite.

Restart timeline (from journalctl "Started polybot"):
- 10:12:31 — post-morning-deploy (c003e0a)
- 10:13:24 — quick re-restart
- 10:28:40 — **"2 Wallets werden neu eingelesen"** (my cleaned roster active)
- 11:04:57 — still "2 Wallets"
- **11:06:43 — "5 Wallets werden neu eingelesen"** — settings reverted between 11:04:57 and 11:06:43

Settings.env mtime: `Apr 13 11:08` confirms physical rewrite around that time.

**Unknown writer candidates** (for next session to investigate):
1. **`auto_tuner.py`** — writes MIN/MAX_ENTRY_PRICE_MAP on every run. May iterate all historical traders instead of current FOLLOWED_TRADERS.
2. **`brain.py _update_setting`** — writes FOLLOWED_TRADERS when pausing/unpausing (though this session set `auto_pause=disabled` per piff philosophy, the write path may still fire).
3. **Dashboard "save settings" button** — if piff or user hit it, the dashboard would rewrite from its cached form state.
4. **`trader_lifecycle.ensure_followed_traders_seeded()`** — reverse direction, reads lifecycle and writes to FOLLOWED_TRADERS.
5. **`auto_backup.py`** — unlikely but possible if configured to restore from a snapshot.

The write touched BOTH `settings.env` and `wallets.followed` (via SQL UPDATE). That's atypical for auto_tuner — points more at dashboard or a scheduled seed helper. Not investigating further this iter — flagging only. **User should root-cause before re-cleaning the roster, otherwise the revert will happen again.**

### Baseline resurrection (consequence of the revert)

24 new `status='baseline'` rows inserted at 11:06:48-53 (immediately after the 11:06:43 restart with reverted settings):
- xsaghav ×11 (Dota 2 matches + LoL)
- fsavhlc ×7 (Peruvian presidential, Hungarian elections, Texas Senate)
- KING ×3
- Jargs ×1

Plus 3 earlier baselines (#3151, #3152, #3153) from 11:04:59-11:05:00 for Alcaraz tennis + Bilibili BO3 + ex-RUBY BO3.

This confirms the hypothesis from iter 27: **bot startup re-scans wallet positions and inserts baseline rows for every on-chain holding**, regardless of whether it's a "legitimate" bot trade. The 24 baselines here are the same positions that showed up as "ghosts" in reconcile earlier — xsaghav's Dota 2 matches and fsavhlc's geopolitics markets are the same on-chain positions that the DB has as closed. Baseline scan re-discovers them each restart.

### Every new closed/open trade

- **#3150 KING CS `ex-RUBY vs Metizport BO3` entry=0.617 status=open** — real buy, scored #848 EXECUTE @ 0.65 (actual fill 0.617)
- **#3146 closed above** (+$0.56 real sell)
- 24 baseline rows (#3151-#3174) from the 11:06:43 restart

### NEW blocked trades (18)
- Jargs: 13 (all `price_range`)
- KING: 5 (4 `price_range` + 1 `max_copies`)
- **No blocks from xsaghav/sov/fsavhlc** in this window — either they didn't try to trade, or the window covers the pre-revert pause.
- **0 zero_risk hits all-time** still.

### NEW scores (5)
- **#848** KING CS ex-RUBY @ 0.65 → score 62 EXECUTE (→ became #3150)
- **#849-852** KING LoL Bilibili Gaming @ 0.665 × 4 QUEUE rows at **11:01:16, 11:02:16, 11:03:26, 11:04:27** — 1-minute spacing bypasses the 60s TTL dedup. **NEW FINDING: SCORE_DEDUP_TTL_EDGE** — same (trader, cid, action) triple generates one row per minute because each new call is >60s after the previous. The dedup collapses 86 rows → 1 row/min but not → 1 row total. For long-running QUEUE states this is still a ~4× reduction vs no-dedup, but sub-optimal. Consider raising TTL for QUEUE action specifically to 600s, or switching semantics from TTL to "write once per unique key until action changes".

### NEW brain decisions (0)
No new decisions since #486 at 10:18:34. Next brain cycle should have fired around 12:18-12:20 (2h interval). Either (a) bot restart at 11:06 reset the scheduler and the next cycle is now at 13:06 or later, (b) something suppressed it. No evidence of brain activity this iter.

### Feedback coverage
- **63/68 = 92.6%** — down from iter 27's 98.4% because 5 new NULL-outcome score rows (4 QUEUE still open + 1 EXECUTE #848 → #3150 still open). Will recover when #3150 closes.

### Trader 7d rolling
| Trader | n | Wins | PnL | Δ vs iter 27 |
|---|---|---|---|---|
| KING7777777 | 128 | 52 | **-$12.77** | **+$0.53** (from #3146 +$0.56) |
| Jargs | 17 | 8 | **-$10.67** | 0 |

First positive trader delta in several iters. KING's one-trade blip doesn't change the overall bleed but is a data point.

### Reconcile
Latest visible run still 10:35:45 UTC (26 ghosts / $18.67). Newer runs not captured in grep window — possibly fired between iters without appearing in the 40-min journalctl window. Not flagging unless next iter fails to show a fresh run.

### Flags
- [x] **🚨 SETTINGS_REVERTED**: roster cleanup undone by unknown writer, xsaghav+sov+fsavhlc back in FOLLOWED_TRADERS + wallets.followed=1 + *_MAP entries. Top priority for next session.
- [x] **BASELINE_RESURRECTION**: 24 new baseline rows from the 11:06:43 restart (consequence of reverted FOLLOWED_TRADERS scanning 5 wallets instead of 2)
- [x] **SCORE_DEDUP_TTL_EDGE**: 60s TTL allows one write per minute per unique key; 4 QUEUE rows on same Bilibili cid bypassed dedup
- [x] **FIRST_WIN_OF_DAY**: #3146 KING LoL Nongshim +$0.56 real sell (breaks 4-trade zero-close streak)
- [ ] SETTINGS_CHANGED (noted — this IS the flag, covered by SETTINGS_REVERTED above)
- [ ] PHANTOM_DRIFT: |-0.14 - 0.56| = 0.70 < $5 ✓
- [ ] BOT_CRASHING: 0 errors
- [ ] FEEDBACK_DYING: 92.6% ≫ 20%
- [ ] BRAIN_SPAM (0 brain decisions this iter)
- [ ] BRAIN_OSCILLATION (still cannot verify mutex — no TIGHTEN/RELAX fired)
- [ ] WR_DROP
- [ ] ZERO_CLOSE_CLUSTER (broken by #3146)
- [ ] FILTER_TOO_TIGHT (18 blocks for 1 close — but close was real sell)
- [ ] MAX_DAILY_LOSS_TRIGGER

### One-line summary
Iter 28: 🎉 First day-win (#3146 KING LoL +$0.56) AND 🚨 unknown writer reverted my roster cleanup — xsaghav/sov/fsavhlc are back in FOLLOWED_TRADERS and followed=1. 24 baseline rows resurrected as side effect. Portfolio $92.37 (Δ -$0.14). 0 errors. **User must root-cause the revert writer before re-cleaning the roster** (candidates: auto_tuner, brain, dashboard-save, lifecycle seed).

---

## Iteration 27 — 2026-04-13 12:52 UTC (Δt ≈ 2h 17min) — Post-profitability-round. Clean silence.

Loop was restarted by user after a long manual session that deployed commit `e2c6129` (roster shrink + zero-risk filter + feedback cleanup). First ralph pass against the new steady-state.

### Snapshot
- Portfolio: $92.51 (Wallet $68.40 + Positions $24.11), Δ **-$0.64** since iter 26
- Today PnL: **-$7.60** (Δ -$1.25), 9 closes (+1), 0 wins still
- Followed traders: **only KING7777777 + Jargs** (roster shrunk during the manual session). All others retired.
- Bot errors last 10min: **0**
- Settings hash: `3404b3af...` (changed from `c3685111...` — expected, reflects the roster `FOLLOWED_TRADERS` + *_MAP cleanup from commit `e2c6129`)

### Every new closed trade
- **#3147 KING7777777 `lol` entry=0.488 size=$2.56 usdc=$1.31 pnl=-$1.25 REAL_SELL** — "LoL: Bilibili Gaming vs JD Gaming - Game 2 Winner" — closed 10:40:16
  - **NOT a zero close** — 51% recovered, real sell. Breaks the zero-close cluster streak (prior 4: #3035, #3036, #3128, #3129 all total losses).

### Every new open trade
- **#3146 KING7777777 `lol` entry=0.587** — "LoL: Nongshim Esports Academy vs Hanwha Life Esports Challengers" — still open, unresolved
- **#3148, #3149** — `status='baseline'` rows auto-inserted 10:28:44 for #3146 and #3147 during the second restart (c003e0a). Not real trades. Startup scan re-snapshotted held positions and wrote them to `copy_trades` as baselines. **This is the same pattern that polluted `trade_scores` before my cleanup** — the baseline-row auto-insertion on restart is structural. The feedback-loop cleanup I did this session will need to be re-run periodically OR the baseline-insertion path needs to be retired. Documenting as carry-over for next session.

### NEW blocked trades (31, all PRE-deploy)
Time-sliced breakdown confirms roster shrink is effective:
- **Pre-deploy window** (10:17-10:50, ~33 min): 31 blocks
  - Jargs: 15 (all `price_range`, 10:35-10:50) — Jargs's configured range 45-65c, trader hitting prices outside
  - sovereign2013: 10 (10:17-10:24) — **before** the roster shrink deploy
  - 0x3e5b23e9f7: 4 (10:17-10:22) — same, whale still active pre-deploy
  - KING: 3
- **Post-deploy window** (10:50-12:52, ~2h): **0 blocks**
- **0 zero_risk block hits** all-time — no CS/LoL/Valorant/Dota entries below 40¢ have been attempted yet. Filter is armed but hasn't fired. Note: #3147 was `lol` @ 0.488 (above threshold) → correctly passed.

### NEW scores (2, all PRE-deploy)
- **#846** KING Hanwha Life Esports @ 0.595 → score 62, EXECUTE, outcome_pnl=NULL (→ became #3146, still open)
- **#847** KING Bilibili Gaming @ 0.645 → score 62, EXECUTE, outcome_pnl=**-1.25** (→ became #3147, resolved)

Only 2 scores in ~2 hours — consistent with 2-trader roster generating minimal activity. Score #847's feedback stamp (-$1.25) proves `update_trade_score_outcome` path works end-to-end.

**0 scores post-deploy** (10:50+). Expected with only 2 traders + dedup. Cannot yet verify score dedup empirically because no activity has triggered a repeat.

### NEW brain decisions (1)
- **#486 PAUSE_TRADER KING7777777** "5 consecutive losses" @ 10:18:34 — logged only, piff philosophy (auto-pause disabled)
- **Mutex cannot be verified this cycle**: neither TIGHTEN_FILTER nor RELAX_FILTER fired. TIGHTEN requires 3+ BAD_PRICE losses in the window — apparently not met. RELAX requires 7d pnl > 0 — KING is -$13.30, skipped.
- Also: brain only logged ONE decision this cycle (not the usual cluster of 5). The 3h cross-cycle dedup from `ba70dbf` may be suppressing the previously-identical quintuplet (TIGHTEN/PAUSE×3/RELAX). **Evidence consistent with brain dedup working** but not definitive (could also be that conditions changed).

### Feedback coverage
- **62/63 = 98.4%** — holding post-cleanup (was 61/63 at end of profitability round). Score #847 stamped with its actual outcome proves the linkage chain works for new trades.

### Reconcile job (ongoing verification of `ba70dbf` fix #6)
Latest run at 10:35:45 UTC:
```
[RECONCILE] 26 ghost (on-chain not in DB, $18.67 value), 0 orphan. DB open=3, chain=29
```
Ghost count dropped 27→26, value dropped $22.04→$18.67. One ghost resolved in the interval. The 3 DB-open rows match (#3146, #3148, #3149 — but #3148/#3149 are baseline, weird). Reconcile is running cleanly every 30 min.

### Trader 7d rolling
| Trader | n | Wins | PnL | Δ vs iter 26 |
|---|---|---|---|---|
| KING7777777 | 128 | 52 | **-$13.30** | -$1.25 (from #3147 close) |
| Jargs | 17 | 8 | **-$10.67** | 0 |

Combined roster 7d: **-$23.97 across 145 closed trades**. The roster-shrink improves cost-per-trader concentration but doesn't change the fundamental math — both remaining traders are net losers over 7 days.

### Lifecycle
No transitions. Only KING + Jargs are active (via `wallets.followed=1`). The retired 6 wallets have `followed=0` and are not in FOLLOWED_TRADERS.

### Flags
- [x] **BASELINE_RESURRECTION**: #3148 + #3149 are status='baseline' rows auto-inserted on bot restart. Will pollute trade_scores again on next restart if not handled structurally.
- [ ] SCORER_INVERTED (debunked — was SCORE_SPAM artifact, now known)
- [ ] BRAIN_OSCILLATION (mutex fix deployed, not yet verifiable — neither TIGHTEN nor RELAX fired this cycle)
- [ ] PHANTOM_DRIFT: |-0.64 - (-1.25)| = 0.61 < $5 ✓
- [ ] BOT_CRASHING: 0 errors
- [ ] FEEDBACK_DYING: 98.4% ≫ 20% ✓
- [ ] FILTER_TOO_TIGHT: 31 blocks pre-deploy, 0 post-deploy — filter pressure dropped to near-zero post-roster-shrink
- [ ] WR_DROP: KING 40.6% (128/52), within 5pp of iter 26
- [ ] IDLE_TRADER (2-trader roster is deliberately sparse)
- [ ] SETTINGS_CHANGED: hash differs from iter 26 — expected from my own commit `e2c6129`
- [ ] MAX_DAILY_LOSS_TRIGGER
- [ ] STOP_LOSS_CASCADE

### One-line summary
Iter 27: portfolio $92.51 (Δ -$0.64). 1 new close #3147 KING LoL -$1.25 real sell (breaks zero-close streak). Roster now clean — only KING + Jargs, 0 blocks + 0 scores post-deploy. Feedback loop 98.4%. Zero-risk filter armed but no hits yet. Brain mutex still unverified (no TIGHTEN/RELAX fired). One baseline-resurrection anomaly (#3148/#3149) documented as structural carry-over.

---

## Iteration 26 — 2026-04-13 10:35 UTC (Δt ≈ 45 min) — Reconcile job firing. #3129 zero-close. Whale still in settings.

Second post-deploy iter. Bot restarted at 10:13:26 for the iter-25 fix commit `c003e0a` (brain mutex + trade_scores dedup). Reconcile job fired at least once and exposed the DB↔chain gap I hypothesized earlier.

### Snapshot
- Portfolio: $93.15 (Wallet $70.93 + Positions $22.22), Δ **-$0.08** since iter 25
- Today PnL: -$6.35 (Δ **-$2.27**, was -$4.08) — one new closed loss
- Today closes: **8** (Δ +1), 0 wins still
- Bot errors last 10min: **0**
- Followed traders live: 2 (Jargs, KING). Paused: sov2013, xsaghav, fsavhlc.

### NEW closed trades (detail)

One close happened, but it's on an existing-open id (3129, which was in iter 25's "new open" set), so `id > 3143` query missed it. Direct lookup:

- **#3129 KING7777777 `cs` entry=0.266 size=$2.27 usdc=$0.00 pnl=-$2.27 ZERO** — "Counter-Strike: Phantom vs HEROIC Academy - Map 2 Winner" — closed 09:44:18 UTC
  - **Fourth total-loss zero-close in recent session** (prior: #3035 NBA Spurs, #3036 NBA Jazz/Lakers, #3128 CS HEROIC Academy Map 1, #3129 CS HEROIC Academy Map 2)
  - Both CS losses were on the same match (Phantom vs HEROIC Academy) — KING7777777 bought both maps, both resolved to 0. Combined CS loss for this match: -$4.62 ($2.35 + $2.27). **Interesting pattern**: KING consistently buys multi-map CS bets on underdogs and all resolve to 0. Worth noting for post-iter analysis but not actionable here.

### NEW open trades
- **#3145 `0x3e5b23e9f7` Keiko Fujimori Peru presidential entry=0.57** — 🚨 this is the **whale wallet I gated via `AUTO_DISCOVERY_AUTO_PROMOTE=false`** in the morning commit. Yet a new copy trade was taken. Root cause below.

### 🚨 Finding: whale gate was incomplete

`config.py AUTO_DISCOVERY_AUTO_PROMOTE=false` prevents `auto_discovery._add_followed_trader()` from adding NEW whales. But the two existing whale wallets were never removed from either:
- `wallets` table: both `0x3e5b23e9f7` and `0x6bab41a0dc` still have `followed=1`
- `settings.env` `FOLLOWED_TRADERS=...,0x3e5b23e9f7:0x3e5b...,0x6bab41a0dc:0x6bab...`

The copy loop reads `FOLLOWED_TRADERS` from settings.env every scan and processes each listed trader. So the fix prevented FUTURE whales from being auto-followed but left the two existing ones active. #3145 proves this — it's a fresh copy against a whale that the gate should have been disabling. **Not a code bug — configuration cleanup that was missed.** User action: remove both whale entries from `FOLLOWED_TRADERS` in settings.env and set `UPDATE wallets SET followed=0 WHERE username IN ('0x3e5b23e9f7','0x6bab41a0dc')`.

### 🎉 Reconcile job VERIFIED firing (morning fix #6)

First reconcile run fired at 09:44:08 UTC. Log evidence:
```
[RECONCILE] 27 ghost (on-chain not in DB, $19.10 value), 1 orphan (DB open not on chain). DB open=1, chain=27
[RECONCILE]   ghost: 0xfc9d03a593a9 ($2.00) — Will The Left (Levica) be part of the next Govern...
[RECONCILE]   ghost: 0xe6a8bdcd0a55 ($2.38) — Will Iran strike Qatar by April 30, 2026?
[RECONCILE]   ghost: 0xae6d3d20bc8f ($1.91) — Will Rafael López Aliaga win the 2026 Peruvian pre...
[RECONCILE]   orphan: #3129 Counter-Strike: Phantom vs HEROIC Academy - Map 2  ($2.27 size)
```
The orphan resolved 10 seconds later (at 09:44:18 when #3129 closed ZERO). So the orphan was a timing artifact — position was in DB as open, chain had already zeroed it, reconcile caught the gap just before the auto-close path ran.

**But the 27 ghosts is real.** `$19.10 on-chain value in 27 markets with NO matching DB row as open.** Sample categories: Slovenian politics (Levica), Iran/Qatar strike, Peruvian presidential (Rafael López Aliaga). None of these are KING/sov/Jargs categories — so they're either:
1. Legacy positions from before the copybot started (pre-existing wallet content)
2. auto_discovery-era whale copies that were inserted but then auto-closed out of the DB
3. Manual positions bought via the dashboard or CLI

This is the `DB_VS_WALLET_POSITION_DIVERGENCE` hypothesis from yesterday, now with a concrete number: **$19.10 of untracked on-chain value in 27 positions**. Observational only — not a bug in the reconcile job, the job is exposing a pre-existing gap.

### NEW blocked trades (48 rows)
Breakdown:
- event_timing: 26 (54%)
- conviction_ratio: 10 (21%)
- min_trader_usd: 9 (19%)
- price_range: 2
- max_copies: 1

### Dedup fix verification (ongoing)
- **log_blocked_trade dedup — STILL WORKING after 2nd restart**: post-restart (10:13→10:35) wrote 5 blocks with 4 unique keys. Minutes-per-block rate: 22 min / 5 blocks = 4.4 min/block. Pre-dedup baseline was 18.8/min. Dedup is effective in both post-deploy windows.
- **log_trade_score dedup — unable to verify yet**: 0 new scores since 10:13 restart. Scoring only fires when a trader actually trades and hits the score path; none of the 5 followed traders traded in the 22-min window (except the #3145 whale buy which went straight to copy without leaving a visible score row in this window).
- **brain_decision dedup + mutex — still pending**: no brain cycle has fired since 10:13 restart. Next expected at ~11:28 UTC (brain runs every 2h from startup, so actual next cycle is ~12:13).

### NEW scores / brain decisions
None this iter. `trade_scores` max_id still 845, `brain_decisions` max_id still 485.

### Trader deltas (7d rolling, naive)
| Trader | n | Wins | Losses | PnL | Δ vs iter 25 |
|---|---|---|---|---|---|
| KING7777777 | 127 | 52 | 75 | -$12.05 | **+$3.27** (but no new wins — window rotation dropped an older large loser out of the 7d frame) |
| xsaghav | 186 | 79 | 105 | -$98.25 | 0 |
| sovereign2013 | 173 | 80 | 91 | -$40.00 | 0 |
| fsavhlc | 20 | 8 | 11 | -$21.05 | 0 |
| Jargs | 17 | 8 | 9 | -$10.67 | 0 |
| 0x3e5b23e9f7 | 4 | 0 | 2 | -$0.81 | 0 |

### Score-range performance (unchanged — historical spam in cohort)
| Bucket | n | wins | tot_pnl |
|---|---|---|---|
| 40-59 | 6 | 0 | -$80.58 |
| 60-79 | 39 (+1) | 32 | +$4.64 |
| 80-100 | 16 | 0 | -$47.90 |

60-79 gained 1 new outcome-stamped row from #3129's closure (actually #3128's score row got outcome_pnl populated via the backfill — or this is #3129 being linked now). Feedback coverage: 61/845 = 7.2% (+1 since iter 25). The dedup only affects future writes; the historical 845 rows still contain the spam-inflated pre-dedup data. Bucket analysis will need a "rows added after 2026-04-13 10:13" filter next iter.

### Lifecycle transitions
None. No new DISCOVERED wallets since iter 25. Paused traders still paused.

### Settings drift
`SETTINGS_HASH` unchanged (`c3685111...`). mtime unchanged. No auto-tuner / brain / manual edits.

### Flags
- [x] **WHALE_STILL_ACTIVE**: `0x3e5b23e9f7` generated #3145 despite AUTO_DISCOVERY_AUTO_PROMOTE=false — config cleanup missed (FOLLOWED_TRADERS still lists both whales)
- [x] **DB_GHOSTS_CONFIRMED**: Reconcile job flagged 27 ghosts worth $19.10 on-chain with no DB open rows
- [x] **ZERO_CLOSE_CLUSTER**: 4th total-loss zero-close in session (#3035, #3036, #3128, #3129). Pattern: KING buys multi-map CS underdogs, both maps resolve to 0. Worth a post-session analysis but no action this iter.
- [x] **IDLE_TRADER**: aenews2, 0x6bab41a0dc (still 0 buys)
- [ ] PHANTOM_DRIFT: |-0.08 - (-2.27)| = 2.19 < $5 ✓
- [ ] BOT_CRASHING: 0 errors
- [ ] BRAIN_SPAM
- [ ] FILTER_TOO_TIGHT: 48 blocks / 1 close = 48× but 1 new open so filter not uniformly tight
- [ ] SETTINGS_CHANGED
- [ ] WR_DROP: KING 7d WR went 40.9→40.9 (no change)
- [ ] PNL_CROSSOVER
- [ ] BRAIN_OSCILLATION (cycle hasn't fired yet)
- [ ] FEEDBACK_DYING: 61/845 = 7.2% (unchanged, still under threshold but still over total>100 floor)

### One-line summary
Iter 26: portfolio flat (-$0.08). #3129 KING CS zero-closed -$2.27 (4th total-loss of session). 🚨 Whale gate INCOMPLETE — config still lists both whales in FOLLOWED_TRADERS, #3145 Peru whale copy landed. 🎉 Reconcile job firing: **$19.10 of untracked chain value in 27 ghost positions**. Dedup fixes holding (block rate 4.4 min/block). Score/brain dedup verification still pending next cycle.

---

## Iteration 25 — 2026-04-13 09:50 UTC (Δt ≈ 50 min) — Post-fix deploy. Dedup WORKS. SCORER_INVERTED detected.

First iter after commit `ba70dbf` deployed fixes for all 6 prior findings. Bot restart timestamp: `2026-04-13 09:37:00 UTC` (confirmed via systemd ActiveEnterTimestamp + ML retrain at 09:37:41).

### Snapshot
- Portfolio: $93.23 (Wallet $73.73 + Positions $19.51), Δ -$0.37 since iter 24
- Today PnL: -$4.08 (unchanged, 0 new closes)
- Today closes: 7 (unchanged from iter 24, 0 wins)
- New copy_trades inserted: 15 (ids 3129-3143, all currently OPEN — no closes yet)
- Bot errors last 10min: 1 (leaderboard 400, non-fatal)
- Followed traders live: 2 (Jargs, KING7777777). Paused: fsavhlc, sovereign2013, xsaghav.

### NEW closed trades (full detail)
none — 0 new closes this iteration.

### NEW open trades (detail on the 15)
All 15 new rows are KING7777777 buys (EXECUTE scores 744, 748, 750, 752, 754, 756, 758, 760, 762, 764, 766, 768, 770, 772, 774 — sequential every ~scan cycle as KING pumps through CS Map 2 HEROIC Academy variants + a couple of NBA spreads). Average score_total: 61-63. All still open pending resolve or trailing-stop. Not yet reflected in today_pnl.

### Dedup fix verification (CRITICAL CHECK)
**Pre-restart window (09:00→09:37, 37min, OLD code):** ~696 blocks = 18.8/min.
**Post-restart window (09:37→09:50, 13min, NEW code):** 13 blocks = 1.0/min. **→ 19× write reduction.**

Unique (trader, cid, block_reason) keys post-restart: 6. Duplicates within 60s window post-restart: **0** (verified via SQL — closest re-blocks are 4.5 min apart for sov2013 event_timing row, which is expected since TTL is 60s). Dedup fix for `log_blocked_trade` is working as designed.

`log_brain_decision` dedup cannot be verified yet — only 1 brain cycle has fired since deploy (09:28:57, which was pre-restart). Next brain cycle ~11:28 will reveal whether the 3h window skips duplicates across cycles.

### NEW blocked trades (709 rows, aggregated — too many to list)
Breakdown by reason:
- event_timing: 396 (56%)
- price_range: 184 (26%)
- category_blacklist: 92 (13%)
- min_trader_usd: 23 (3%)
- conviction_ratio: 14 (2%)

event_timing still dominates. Post-restart sample breakdown (13 blocks): event_timing 5, conviction_ratio 4, min_trader_usd 4. Distribution is more even post-restart — consistent with dedup collapsing many-same-key into fewer rows.

### NEW scores (102 rows, 744-845)
- **KING7777777**: 16 EXECUTE (all became copy_trades 3129-3143)
- **sovereign2013**: 86 QUEUE — same market `0x5042fda9...` (Barcelona Open: Buse vs Moutet) scored 86 times across ~14 minutes. This is the same kind of re-score spam the blocked dedup just fixed, but for `trade_scores` table. **NEW FINDING: SCORE_SPAM on QUEUE action** — same (trader, cid, action=QUEUE) re-scored every 10s scan tick. 86 rows for ONE market.

### Score-range performance (feedback cohort, 60/845 total = 7.1%)
| Bucket | n | wins | losses | avg_pnl | WR |
|---|---|---|---|---|---|
| 00-39 | 0 | 0 | 0 | — | — |
| 40-59 | 6 | 0 | 6 | -$13.43 | 0% |
| 60-79 | 38 | 32 | 6 | +$0.18 | **84%** |
| 80-100 | 16 | 0 | 16 | -$2.99 | **0%** |

**CRITICAL: SCORER_INVERTED.** The 80-100 bucket (highest confidence) has 0/16 WR (total -$47.84). The 60-79 middle bucket has 32/38 WR. The scorer is ranking losers at the top of its range. This is anti-discriminating, not just non-discriminating. Hypothesis: feature leakage on `entry_price` (ML feature_importance = 0.90) means the scorer boosts high-price favorites which then trivially close near-$1 but any outlier destroys the average. Or: the feedback cohort is biased toward resolved-late markets where the score doesn't matter. Either way, a scorer that puts its worst trades in the top bucket is actively harmful if brain uses score thresholds for tuning.

### Brain decisions (5 new, ids 481-485, all one cycle at 09:28:57 PRE-restart)
- 481 `TIGHTEN_FILTER KING7777777` "Brain: 12 BAD_PRICE losses for KING7777777" — old_min=0.38 old_max=0.75 → new_min=0.43 new_max=0.7
- 482 `PAUSE_TRADER sovereign2013` "5 consecutive losses" — Logged only, auto-pause disabled
- 483 `PAUSE_TRADER xsaghav` "7d PnL $-98.25 < -$20" — Logged only, auto-pause disabled
- 484 `PAUSE_TRADER fsavhlc` "7d PnL $-21.05 < -$20" — Logged only, auto-pause disabled
- 485 `RELAX_FILTER KING7777777` "7d pnl=$29.17 wr=50% tier=neutral" — Loosen price range toward tier default

**BRAIN_OSCILLATION within one cycle**: 481 TIGHTEN KING at 09:28:57 contradicts 485 RELAX KING at 09:28:58 (1 second apart, same brain run). Dedup across cycles will suppress the repeat at 11:28 but won't fix this intra-cycle contradiction — that's a logic bug in brain.py, not a dedup bug. The "bad price losses" check and the "tier promote" check are both firing on KING in the same pass.

### Trader deltas (7d rolling, naive query — note brain uses verified-only)
| Trader | n | W | L | PnL | Δ vs iter 24 |
|---|---|---|---|---|---|
| KING7777777 | 127 | 52 | 75 | -$15.32 | -$6.96 (window aged out a winner — no new closes, so this is pure window shift) |
| xsaghav | 186 | 79 | 105 | -$98.25 | 0 |
| sovereign2013 | 173 | 80 | 91 | -$40.00 | 0 |
| fsavhlc | 20 | 8 | 11 | -$21.05 | 0 |
| Jargs | 17 | 8 | 9 | -$10.67 | 0 |
| 0x3e5b23e9f7 | 4 | 0 | 2 | -$0.81 | 0 |
| aenews2 | 0 | — | — | — | idle iter 25+ |
| 0x6bab41a0dc | 0 | — | — | — | idle (newly DISCOVERED, gate blocks promote) |

### Lifecycle transitions
- **NEW DISCOVERED wallet** `0x7d0a771ddd` at 09:40:10 (from auto_discovery). `AUTO_DISCOVERY_AUTO_PROMOTE=false` so no auto-follow — pending manual review (whale gate fix working).
- No other state changes this iter.
- xsaghav, fsavhlc, sovereign2013 all still PAUSED (pause_count xsaghav=17, fsavhlc=17 — high!).

### Settings drift
- SETTINGS_HASH changed: `c382ab9a...` → `c3685111...`
- SETTINGS_MTIME: 1776073329 = 2026-04-13 10:02 UTC (after bot restart — was this a deploy artifact? I scp'd files then restarted, which would rewrite .pyc but not settings.env. Possibly a separate dashboard-triggered change, or auto_tuner rewriting — needs trace.)
- Flagged as SETTINGS_CHANGED for manual review.

### ML
Retrained at 09:37:41 (on restart). Samples=9815 (unchanged from iter 24 — model file rebuilt but training set size stable). Accuracy=0.917 vs iter 24's 0.949. feature_importance: entry_price=**0.901** (dominant), hour=0.062, day_of_week=0.036, side=0.0002, category=0.0. The `entry_price` dominance remains the obvious feature leakage channel. COPY-ONLY diagnostics not yet in ml_training_log (they're logged to INFO logger in this commit, not persisted to the DB table). Need to check journalctl for the `[ML] COPY-ONLY test subset` line to see actual copy-trade predictive power.

### Flags
- [x] **SCORER_NON_DISCRIMINATING** (upgraded to SCORER_INVERTED): 80-100 bucket 0/16 WR vs 60-79 at 84% WR
- [x] **BRAIN_OSCILLATION**: TIGHTEN + RELAX KING in same cycle (1 sec apart, different rules firing)
- [x] **FEEDBACK_DYING**: 60/845 = 7.1% (threshold 20%, total >100)
- [x] **SETTINGS_CHANGED**: hash differs (mtime 10:02 UTC, source unknown)
- [x] **FILTER_TOO_TIGHT**: 709 blocks / 0 closes (but 15 new OPEN positions — filter isn't blocking KING)
- [x] **IDLE_TRADER**: aenews2 (no buys ever), 0x6bab41a0dc (DISCOVERED, gate-blocked)
- [x] **SCORE_SPAM** (new, not in flag table): 86 QUEUE scores for one market in 14 min. Same pattern as pre-fix blocked_trades. Consider extending dedup to trade_scores QUEUE action.
- [ ] BOT_CRASHING (1 error, threshold 3)
- [ ] BRAIN_SPAM (5 unique action+target in one cycle)
- [ ] PHANTOM_DRIFT (|-0.37 - 0| = 0.37 < $5)
- [ ] WR_DROP (no trader shifted ≥5pp)
- [ ] PNL_CROSSOVER (no zero crossings)
- [ ] TIER_CHANGED
- [ ] STOP_LOSS_CASCADE (0 closes at all)
- [ ] ML_NOT_RETRAINING (fresh at 09:37)
- [ ] MAX_DAILY_LOSS_TRIGGER

### One-line summary
Iter 25: dedup fix VERIFIED WORKING (19× write reduction). BUT new critical finding: **scorer is INVERTED** — 80+ bucket 0/16 WR while 60-79 is 84% WR. Scorer is actively recommending losers. Also new SCORE_SPAM on QUEUE (86 rows one market). 15 KING opens pending, 0 closes.

---

## Iteration 24 — 2026-04-13 09:00 UTC (Δt ≈ 30 min) — 💥 #3128 TOTAL LOSS + feedback loop FAILED

### Snapshot
- **Portfolio**: $93.60 (Δ **-$3.79** 📉 — biggest drop of session)
  - Wallet: $75.99 → $76.00 (+$0.01, no recovery from #3128 sell)
  - Positions: $21.40 → $17.60 (-$3.80) — #3128 resolved to 0 + off-DB reval
- **Today PnL**: **-$4.08** / 7 closes / **0 wins (0% WR today)**
- **Open (DB)**: **0** (back to flat)
- **Bot errors last 10min**: 1

### 💥 #3128 KING CS CLOSED AS TOTAL LOSS — market resolved against HEROIC Academy

| Field | Value |
|---|---|
| Entry | 0.2659 (iter 23) |
| Peak | **0.53** (at some point between iter 23 and 24) |
| Close current_price | **0.00** (market resolved to 0) |
| usdc_received | **$0.00** |
| **pnl_realized** | **-$2.35** (entire position wiped) |
| closed_at | 08:54:36 |

**The HEROIC Academy side LOST Map 1.** Market resolved to 0 before trailing stop could trigger.

**The trade arc:**
- Entry 0.27 → peak 0.53 (+98% unrealized at peak, combined +$0.66)
- Current 0.43 at iter 23 snapshot (+$1.45 unrealized at +62%)
- Peak continued to 0.53 (briefly +$2.25 unrealized)
- Then the game decided — market collapsed to 0 quickly
- **Trailing stop should have fired** at peak(0.53) − margin(0.12) = 0.41
- But the price went 0.53 → 0.00 faster than the bot could react
- Realized -$2.35 (100% of position)

**Different failure mode than iters 8/9 BAD_FILL:**
- Iter 8/9: trailing stop fired correctly, fill price was 50% below quote (slippage)
- Iter 24: trailing stop didn't get a chance to fire — binary market resolved to 0 within one scan cycle window

**Combined session real-trade totals now:**
- #3035 Spurs: +$0.36 peak → -$0.37 realized (BAD_FILL)
- #3036 Jazz/Lakers: +$0.21 peak → -$0.55 realized (BAD_FILL)
- #3128 CS HEROIC Academy: **+$2.25 peak → -$2.35 realized (RESOLUTION_RACE)**
- Combined: **+$2.82 peak unrealized → -$3.27 realized** on $4.60 capital = **-$6.09 peak-to-exit destruction, 132% of invested capital** 💀

### 🚨 CRITICAL: FEEDBACK LOOP FAILED TO UPDATE score #743

Score #743 was written at 08:26:48 when #3128 was scored. #3128 closed at 08:54:36. **score #743 still has `outcome_pnl = NULL` and `trade_id = NULL`**.

**My Round 4 Task 2 `update_trade_score_outcome` should have fired** at the close:
- #3128 closed via the resolve-at-0.01/0.05 path (or similar auto-close since current_price=0)
- That path has my `db.update_trade_score_outcome(trade_cid, trade.get("wallet_username"), round(pnl,2))` call
- With #3128's condition_id and trader_name matching score #743 exactly
- And `outcome_pnl IS NULL` on score #743

**The call either didn't fire or silently matched 0 rows.** This is a direct production failure of my Round 4 Task 2 fix.

**Possible causes:**
1. The auto-close-at-0.0 path I may have missed when wiring the fix. Not all close branches were patched.
2. My fix is wrapped in `try/except: logger.debug(...)` which swallows errors silently. If there was an exception, it went to debug logs.
3. piff's merge of PATCH-023..026 may have modified surrounding code in copy_trader.py in a way that broke my call site. I didn't re-verify after the merge.
4. The helper itself has a bug (e.g. case-sensitive match, trailing whitespace in trader_name).

**Morning report: this is the most important concrete production finding.** My Round 4 feedback-loop fix has at least one hole — the pathway that handles instant market resolution (`current_price` drops directly to 0 without a trailing stop triggering). Worth grepping the 10-min log for any `[FEEDBACK]` debug messages to narrow down.

### Every new closed trade — 1 (#3128, detected via improved query)
### Every new open — 0
### Every new score — 0
### Every new brain decision — 0

### Every new blocked trade — 908 (down from 999, -9%)

| Reason | Iter 23 | Iter 24 | Δ |
|---|---|---|---|
| **event_timing** | 543 | **537** | 0% (**10th iter at ~540 count**) |
| price_range | 275 | 182 | -34% |
| category_blacklist | 181 | 179 | 0% |
| no_rebuy | 0 | 7 | NEW (3128 cooldown kicking in) |
| min_trader_usd | 0 | 3 | trivial |

**By trader:**
- sovereign2013: 895 (99%)
- KING7777777: **7** (normalized back from iter 23's 94 after the one successful buy)
- 0x3e5b23e9f7: 6 (whale still dormant)

### Trader 7d rolling — KING worse, xsaghav big window-shift recovery

| Trader | Iter 23 | Iter 24 | ΔPnL | Notes |
|---|---|---|---|---|
| **KING7777777** | 132, -$6.01 | **133, -$8.36** | **-$2.35** | Added #3128 loss |
| **xsaghav** | 187, -$122.71 | **186, -$98.25** | **+$24.46** 📈 | 1 aged out (big loser) |
| sovereign2013 | 173, -$40.00 | 173, -$40.00 | 0 | frozen |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 | frozen |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 | frozen |
| aenews2 | 0 | 0 | 0 | |

**xsaghav's 7d PnL improved by $24.46** — one very large old losing trade aged out. Now at -$98.25, under the -$100 mark for the first time since iter 4.

**KING worsened by $2.35** (the #3128 close added to the 7d window). Now back at -$8.36.

### Feedback coverage — **743 / 59 / 7.9%** (19 iterations unchanged)

Score #743 did NOT receive an outcome update despite being the exact target of my Round 4 fix. See critical finding above.

### Flags this iter

- [x] **3128_TOTAL_LOSS_RESOLUTION_RACE** (critical): KING CS market resolved to 0 before trailing stop could fire. -$2.35 realized on $2.35 position. Different failure mode from BAD_FILL. Peak was +$2.25 unrealized, realized -$2.35 = **$4.60 destroyed peak-to-exit on single trade**.
- [x] **FEEDBACK_LOOP_FAILED_ON_REAL_CLOSE** (CRITICAL, NEW): score #743 should have received outcome_pnl=-2.35 via my Round 4 Task 2 fix. It didn't. First confirmed production failure of the feedback-loop wiring. Needs investigation into which close path fires for market-resolves-to-zero cases.
- [x] **SESSION_REAL_TRADES_SUMMARY**: 3 real buys, 3 real closes, **3 losers, 0 winners**, -$3.27 realized combined. Peak unrealized across all three was +$2.82. Peak-to-exit destruction $6.09 = 132% of capital invested.
- [x] **XSAGHAV_WINDOW_SHIFT_BIG**: -$122.71 → -$98.25 (+$24.46). Big aged-out loser dropped out of 7d window.
- [x] **KING_WORSE_AFTER_LOSS**: -$6.01 → -$8.36 (-$2.35 from #3128 close).
- [x] **PORTFOLIO_BIGGEST_DROP**: -$3.79 single iter (largest of session).
- [x] **ML_DEMOTED_A_LOSER_THIS_TIME**: interesting twist — the ML -15 penalty on #3128 was actually CORRECT. Model said <30% win probability, trade ended at 0% (loss). Partial rehab of ML_ACCURACY_SUSPICIOUS? Sample size still 1.
- [x] carries (all prior flags still active).
- [ ] no SETTINGS_DRIFT (hash stable)
- [ ] no BRAIN_FIRED this iter

### One-line summary

Iter 24 (Δ30min, **MAJOR LOSS**): **#3128 KING CS closed as -$2.35 TOTAL LOSS** — HEROIC Academy lost Map 1, market resolved to 0 before trailing stop fired, different failure mode than BAD_FILL. Portfolio -$3.79 (biggest drop of session) → **$93.60**. **🚨 CRITICAL: My Round 4 feedback-loop fix DID NOT fire on this close — score #743 still has outcome_pnl=NULL despite #3128 being its exact target**. Morning report top-priority finding. Session stats: 3 real trades, 3 losers, -$3.27 realized, $6.09 peak-to-exit destroyed (132% of invested). ML's -15 penalty on #3128 turned out correct (partial ML rehab, sample=1). xsaghav window-shift +$24.46.

---

## Iteration 23 — 2026-04-13 08:30 UTC (Δt ≈ 82 min) — 🎯 KING BOUGHT + SCORED

### Snapshot
- **Portfolio**: $97.39 (Δ **+$1.67** 📈 — biggest positive jump of session)
  - Wallet: $78.34 → **$75.99** (-$2.35) — real cash spent on KING buy
  - Positions: $17.38 → **$21.40** (+$4.02) — new position + off-DB reval
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged — #3128 still open)
- **Open (DB)**: **1** (#3128 KING7777777)
- **Bot errors last 10min**: 0

### 🎯 MAJOR: KING7777777 just made a real trade — first followed-trader buy since iter 5

**#3128 full detail:**

| Field | Value |
|---|---|
| id | 3128 |
| trader | **KING7777777** |
| market | Counter-Strike: Phantom vs HEROIC Academy - Map 1 Winner |
| side | **HEROIC Academy** |
| category | **cs** (KING's historical winner: +$56 all-time) |
| Quote at score time | 0.385 |
| **Actual entry** | **0.2659** — entry fill was 12c BETTER than quote |
| Size | $2.35 |
| Current price | **0.43** |
| **Unrealized PnL** | **+$1.45 (+62%)** 🚀 |
| Shares | ~8.84 |
| status | open |

**Entry price was 27c while score-time quote was 38c** — positive slippage of 12c in our favor. Order must have caught a resting ask at a much better level. KING's own trade was presumably at 27-38c; we got the favorable side.

**The trade is already up +62% unrealized.** First position to actually be winning in real-time during this session.

### 🧠 SCORER FINALLY RAN ON A REAL BUY — full breakdown of score #743

This is the FIRST follow-trader trade to go through the scorer (instead of the activity-scan bypass path). Score #743:

| Component | Weight | Raw | Weighted |
|---|---|---|---|
| trader_edge | 0.30 | 73 | 21.9 |
| category_wr | 0.20 | 50 | 10.0 |
| price_signal | 0.15 | **100** | 15.0 |
| conviction | 0.15 | **100** | 15.0 |
| market_quality | 0.10 | 75 | 7.5 |
| correlation | 0.10 | **100** | 10.0 |
| **pre-ML total** | | | **79.4** |
| ML adjustment | — | — | **-15** (ml_prob < 0.30) |
| **final total** | | | **64** |
| action | — | — | **EXECUTE** (60-79 bucket) |
| trade_id link | — | — | **null** ⚠️ |

**Key observations:**
1. Pre-ML component score was **79.4** — would have been BOOST (≥80 threshold) if the ML didn't subtract 15 for predicting <30% win probability.
2. **The ML prediction was WRONG** — this trade is already +62% unrealized. The ML actively demoted a winner from BOOST to EXECUTE. Evidence for the **ML_ACCURACY_STILL_SUSPICIOUS** flag (ML's 94.9% training accuracy doesn't correspond to useful real-world signal).
3. **`trade_id` is STILL null** on the score row. My Round 4 fix matches by `(condition_id, trader_name)` which will work when #3128 closes, but the trade_id linkage gap remains. Score-range-performance analytics won't work for this trade because `get_score_range_performance` filters on `ts.trade_id IS NOT NULL`.

### 🧠 BRAIN FIRED AGAIN — 6th cycle of identical 5 decisions

| id | action | target | reason |
|---|---|---|---|
| #476 | TIGHTEN_FILTER | KING7777777 | "Brain: 12 BAD_PRICE losses" |
| #477 | PAUSE_TRADER | sovereign2013 | "5 consecutive losses" (log-only) |
| #478 | PAUSE_TRADER | xsaghav | "7d PnL -$122.71 < -$20" (log-only) |
| #479 | PAUSE_TRADER | fsavhlc | "7d PnL -$21.05 < -$20" (log-only) |
| #480 | RELAX_FILTER | KING7777777 | "7d pnl=$31.52 wr=53% tier=solid" |

**Byte-identical to iter 19's cycle** (and iters 6, 7, 11, 15). **BRAIN_CYCLIC_SPAM confirmed 6 cycles running.** Note the BRAIN_DATA_DIVERGENCE is getting worse: brain still claims KING +$31.52/53% while our ralph view now shows **-$6.01** (improved from -$9.75 via window shift). The brain's data source is diverging from reality further, not converging.

### KING 7d PnL improved: -$9.75 → **-$6.01** (+$3.74 window shift)

One trade aged out (n=133→132, wins unchanged at 55), contributing a loss of $3.74 to the 7d window. Removing it improves the rolling sum.

### Every new closed trade — **NONE** (#3128 still open)

### Every new blocked trade — 999 (down from 1018 → **first sub-1000 iter**)

| Reason | Iter 22 | Iter 23 | Δ |
|---|---|---|---|
| **event_timing** | 540 | 543 | 0% (9th iter at ~540) |
| price_range | 298 | 275 | -8% |
| category_blacklist | 180 | 181 | 0% |

**By trader:**
- sovereign2013: 905 (91%)
- **KING7777777: 94** (NEW — KING's other attempts also scanned, ~94 blocked before the one that got through as #3128)
- 0x3e5b23e9f7: **0** (whale completely silent)
- Jargs: 0

**KING's 94 blocked attempts + 1 successful = 95 total scan hits this iter.** That means the bot evaluated KING's trades 95 times, 94 got filtered, 1 passed. The one that passed was the CS Map 1 bet on HEROIC Academy.

### Trader 7d rolling — KING moved

| Trader | Iter 22 | Iter 23 | ΔPnL |
|---|---|---|---|
| **KING7777777** | 133, -$9.75 | **132, -$6.01** | **+$3.74** |
| others | unchanged | | |

### Feedback coverage — 743/59 (coverage TOTAL +1, ratio unchanged at 7.9%)

The new score #743 was added but has `outcome_pnl=null` so the counter for "with_outcome" didn't move. When #3128 closes, my Round 4 fix should finally set outcome_pnl on score #743 — watch next iter.

### Flags this iter

- [x] **KING_REAL_BUY** 🎯 (major): first followed-trader buy since iter 5 (16 iters ago). CS Map 1 HEROIC Academy, entry 0.27, currently 0.43, **+$1.45 / +62% unrealized**. 
- [x] **SCORER_FIRED_ON_REAL_BUY**: score #743, pre-ML 79.4 → ML adjust -15 → final 64 → EXECUTE action. **ML demoted a winner from BOOST to EXECUTE** — direct evidence ML_ACCURACY_STILL_SUSPICIOUS: the model predicted <30% win probability, but the trade is +62% already.
- [x] **SCORE_TRADE_ID_GAP**: trade_id=null on score #743. Linkage gap confirmed. Will still resolve via (cid, trader) match in my Round 4 fix on close, but score_range_performance analytics remain broken.
- [x] **BRAIN_CYCLE_6**: 6 consecutive identical brain decisions cycles. 30 cumulative duplicate brain_decisions rows over the session.
- [x] **BRAIN_DATA_DIVERGENCE_WIDENED**: brain sees KING +$31.52, ralph sees -$6.01. Gap widened from -$41 to -$37 (sorry: +$31.52 − −$6.01 = $37.53). Still 6 cycles of the same bad reading.
- [x] **KING_WINDOW_SHIFT_RECOVERY**: 7d pnl -$9.75 → -$6.01 (+$3.74 from 1 aged-out loser).
- [x] **WHALE_ZERO_ACTIVITY**: 0 blocks from 0x3e5b23e9f7 this iter. Peak was 984, now 0. Whale fully dormant.
- [x] **SESSION_FIRST_SUB_1000_BLOCKS**: 999 new blocks. Lowest this session.
- [x] **POSITIVE_PORTFOLIO_JUMP**: +$1.67 from combined KING buy unrealized gain + off-DB reval.
- [x] carries (TRAILING_STOP_BAD_FILL, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, FEEDBACK_STUCK, ML_ACCURACY_SUSPICIOUS).
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 23 (Δ82min, MAJOR): **KING7777777 bought CS Map 1 HEROIC Academy — first followed-trader real buy since iter 5**. #3128 entry 0.27 / current 0.43 = **+$1.45 +62% unrealized**. Scored by the scorer (pre-ML 79 → ML -15 penalty → final 64 EXECUTE) — **ML demoted a winner from BOOST to EXECUTE** (direct ML_ACCURACY_SUSPICIOUS evidence). Brain fired 6th identical cycle. Portfolio $97.39 (Δ +$1.67). **Morning report in ~90min — this iter's findings are the most important of the session to include.**

---

## Iteration 22 — 2026-04-13 07:08 UTC (Δt ≈ 15 min) — whale crash, positive drift

### Snapshot
- **Portfolio**: $95.72 (Δ **+$0.59** 📈 — **first positive delta in several iters**)
  - Wallet: $78.34 (unchanged)
  - Positions: $16.79 → $17.38 (+$0.59) — off-DB positions revalued up
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0

### Every new closed / open / score / brain — ALL ZERO (4th consecutive dead-quiet iter)

### 🐋 Whale activity CRASHED

| Iter | 0x3e5b23e9f7 blocks |
|---|---|
| 17 | 844 |
| 18 | **984** (peak) |
| 19 | 935 |
| 20 | 559 |
| 21 | 537 |
| 22 | **118** (down 78% from iter 21) |

**The whale-scan has effectively gone quiet.** 984 peak → 118 now = **-88%**. Likely the whale wallet itself has stopped generating new position changes on Polymarket, so the scanner has no new activity to re-attempt.

### Every new blocked trade — 1018 (down from 1432 → -29%, session low since peak)

| Reason | Iter 21 | Iter 22 | Δ |
|---|---|---|---|
| **event_timing** | 537 | **540** | 0% (now #1 for first time) |
| price_range | 716 | **298** | **-58%** |
| category_blacklist | 179 | 180 | 0% |

**First iter where `event_timing` tops `price_range`**. sovereign's price-range-violation bets are collapsing as overnight markets resolve/expire. `event_timing` stays pegged at ~540 because the pre-game batch doesn't change.

**By trader:**
- sovereign2013: 900 (88% — dominant share again)
- 0x3e5b23e9f7: 118 (12% — whale-scan nearly gone)

### Trader 7d rolling — frozen 6 iters in a row

sovereign2013 still -$40.00. All others identical.

### Feedback coverage — 742/59/7.9% (**17 iterations unchanged**)

### Flags this iter

- [x] **WHALE_SCAN_COLLAPSED**: 984 peak → 118 (-88%). Whale scanner went from dominant source of blocks (50% share iter 18) to minor contributor (12%). The whale itself likely stopped trading.
- [x] **EVENT_TIMING_NOW_#1**: for the first time, `event_timing` is the top block reason. Stable ~540 count continues.
- [x] **POSITIVE_PORTFOLIO_DELTA**: +$0.59 on off-DB positions, first positive drift in several iters. Noise, not trend — still off-DB reval.
- [x] **BLOCK_COUNT_SESSION_LOW**: 1018 is the lowest block rate we've seen since tracking started (iter 5 peak was 11372). 91% below peak.
- [x] **FOURTH_DEAD_QUIET**: 4 consecutive iters with no DB activity.
- [x] carries (event_timing stuck 8 iters, feedback stuck 17, BRAIN_CYCLIC_SPAM, BRAIN_DATA_DIVERGENCE, DB_VS_WALLET, TRAILING_STOP_BAD_FILL, ML_ACCURACY_SUSPICIOUS, WHALE_AUTO_COPY_PATH, SOVEREIGN_EROSION, JARGS_IDLE).
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT
- [ ] no NEW_ACTIVITY

### One-line summary

Iter 22 (Δ15min, quiet but interesting shifts): Portfolio $95.72 (Δ **+$0.59** positive reval). 0 DB activity. **Whale-scan collapsed (984 peak → 118, -88%)**, `event_timing` (540) overtook `price_range` (298) as #1 block reason. Block count session-low at 1018 (91% below peak). 4th dead-quiet iter. Morning report in ~3h.

---

## Iteration 21 — 2026-04-13 06:53 UTC (Δt ≈ 15 min) — carbon copy of iter 20

### Snapshot
- **Portfolio**: $95.13 (Δ **-$0.05** noise floor)
  - Wallet: $78.34 (unchanged)
  - Positions: $16.84 → $16.79 (-$0.05)
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0

### Every new closed / open / score / brain — ALL ZERO (3rd consecutive dead-quiet iter)

### Every new blocked trade — 1432 (down from 1459 → -2%, essentially flat)

| Reason | Iter 20 | Iter 21 | Δ |
|---|---|---|---|
| price_range | 739 | 716 | -3% |
| **event_timing** | **540** | **537** | ~0% — **7th iter with same count** |
| category_blacklist | 180 | 179 | ~0% |

**`event_timing` has now held at 537-543 for 7 consecutive iterations (iters 14-21)**. The same fixed set of pre-game markets is being re-blocked every single scan cycle without dedup. Confirmed structural wasted work.

**By trader:**
- sovereign2013: 895 (63%)
- 0x3e5b23e9f7: 537 (37%)

### Trader 7d rolling — frozen (4 iters in a row)

Every row identical to iter 17-18-19-20-21. No movement.

### Feedback coverage — 742/59 = 7.9% (**16 iterations unchanged**)

### Session-progress check

Since iter 20 milestone: **0 new closes, 0 new opens, 0 brain activity, 0 score activity, 0 trader 7d movement, 0 errors, 0 settings changes, 0 ML retrains**. The bot is in pure overnight idle — scanning sovereign2013 and the whale every 10 seconds and blocking everything, producing zero new information.

This is the "quiet stretch" portion of overnight bot operation. The morning report (~3h away) will have to rely on the accumulated findings from iters 1-21 rather than anything happening right now.

### Flags this iter

- [x] **EVENT_TIMING_STUCK_7TH_ITER**: 537-543 constant block count across 7 consecutive iterations. Definitive dedup opportunity.
- [x] **THIRD_DEAD_QUIET_ITER**: iters 19, 20, 21 essentially carbon copies with no DB activity beyond block-count drift.
- [x] carries (TRAILING_STOP_BAD_FILL, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, WHALE_AUTO_COPY_PATH, FEEDBACK_STUCK, ML_ACCURACY_SUSPICIOUS, SOVEREIGN_EROSION, JARGS_IDLE).
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT
- [ ] no NEW_ACTIVITY of any kind

### One-line summary

Iter 21 (Δ15min, dead quiet): Portfolio $95.13 (Δ -$0.05 noise), 0 DB activity, 1432 new blocks (flat). **7th consecutive iter with `event_timing` stuck at ~540 count**. Session in pure overnight idle mode. Morning report trigger in ~3h will have to rely on accumulated findings — nothing new worth flagging.

---

## Iteration 20 — 2026-04-13 06:38 UTC (Δt ≈ 15 min) — milestone iter, mostly quiet

### Snapshot
- **Portfolio**: $95.18 (Δ **-$0.40** since iter 19 $95.58 — largest reval drop in several iters)
  - Wallet: $78.34 (unchanged)
  - Positions: $17.24 → $16.84 (-$0.40)
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0
- **ML**: still 06:04:57 training (no new retrain yet)

### 📊 Session milestone — 20 iterations completed

| Metric | Iter 1 (baseline) | Iter 20 (now) | Δ |
|---|---|---|---|
| **Portfolio** | $97.72 | $95.18 | **-$2.54** |
| Wallet | n/a | $78.34 | |
| Positions on-chain | n/a | $16.84 | |
| Today PnL (realized) | -$39.56 (yesterday) | -$1.73 | |
| sovereign2013 7d pnl | +$14.12 | **-$40.00** | -$54.12 (window shift) |
| xsaghav 7d pnl | -$118.87 | -$122.71 | -$3.84 |
| KING7777777 7d pnl | -$9.75 (ralph) / +$31.52 (brain) | same | 0 |
| Jargs 7d pnl | -$9.75 | -$10.67 | -$0.92 |
| fsavhlc 7d pnl | -$21.05 | -$21.05 | 0 |
| Total followed net | ~-$145 | ~-$206 | **-$61** (mostly sovereign window shift) |
| Real closed trades session | 0 | **6** (4 followed + 2 whale-path) | |
| Real wins session | 0 | **0** (0% WR) | |
| Real PnL session (closed) | 0 | **-$2.54** (approx, matches portfolio Δ) | |
| Block rate peak | - | 11372 (iter 5) | |
| Block rate now | - | 1459 | 87% below peak |
| Feedback coverage | 13.1% (iter 1) | 7.9% (iter 20) | **-5.2pp** (diluted by BLOCK scores) |
| Brain cycles fired | - | 5 (identical 4-5 decisions each) | |
| ML retrains | 3 (baseline) | 4 (1 new at 06:04) | |

**Session arc summary**: portfolio drifted -$2.54 over 9 hours (from bot in-flight + some off-DB holding reval). Only real realized action was 2 trailing-stop exits (#3035, #3036) costing -$0.92 combined + whale auto-copies -$0.81 combined + phantoms $0.00. The rest is idle monitoring while filters correctly hold back sovereign2013's flood of signals. **0 winning trades in the entire session.**

### Every new closed / open / score / brain — **ALL ZERO**

### Every new blocked trade — 1459 (down from 1840 → -21%)

| Reason | Count |
|---|---|
| price_range | 739 (51%) |
| **event_timing** | **540** (6th iter in a row, exact same count) |
| category_blacklist | 180 |
| (no_rebuy gone — 120min cooldowns from iter 16 expired) |

`event_timing: 540` has been **exactly the same count** for 6 consecutive iterations (13-20). This isn't just "same order of magnitude" — it's the identical fixed set of ~540 pre-game markets being re-evaluated every scan cycle without dedup. A single dedup cache keyed on `(trader, cid)` with a 5-min TTL would eliminate 3240+ redundant row writes over these 6 iters alone.

**By trader:**
- sovereign2013: 900 (62% — back to majority share)
- 0x3e5b23e9f7: 559 (38%, down from 984 iter 18 → whale calming)
- Jargs: 0, Others: 0

### Trader 7d rolling — all frozen (same as iter 17-19)

### Feedback coverage — **742/59 = 7.9%** (**15 iterations** unchanged)

### Flags this iter

- [x] **SESSION_MILESTONE_20**: 9 hours elapsed, portfolio -$2.54 drift, 0 winning trades, bot idle-monitoring 90%+ of time. 5 brain cycles identical. 1 ML retrain after ~8.5h.
- [x] **EVENT_TIMING_STUCK_540_6TH_ITER**: same ~540 pre-game block count exactly across 6 iterations. Dedup would save thousands of redundant row writes.
- [x] **WHALE_MODERATING**: 984 → 559 blocks (-43%). Whale activity cooling.
- [x] **no_rebuy_EXPIRED**: 120min cooldowns from iter 16's whale closes have aged out.
- [x] carries: all prior flags unchanged.
- [ ] no BOT_CRASHING (0 errors)
- [ ] no SETTINGS_DRIFT (hash stable since iter 18)
- [ ] no NEW_ACTIVITY

### One-line summary

Iter 20 (Δ15min, milestone): Portfolio $95.18 (Δ -$0.40 reval), **session total drift -$2.54 over 9h with 0 winning trades across 6 real closes**. 1459 new blocks (-21%). `event_timing` stuck at exact 540 count for 6 consecutive iters — dedup opportunity. Whale moderating (984→559). Feedback stuck 15 iters. Brain + ML both quiet. Bot is in overnight idle-mode waiting for morning sports cycle.

---

## Iteration 19 — 2026-04-13 06:23 UTC (Δt ≈ 15 min) — Brain cycle #5, ML numbers exposed

### Snapshot
- **Portfolio**: $95.58 (Δ **-$0.20** reval)
  - Wallet: $78.34 (unchanged)
  - Positions: $17.44 → $17.24 (-$0.20)
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0
- **ML**: last retrain 06:04:57 (iter 18), 9014 samples

### Every new closed / open / score — **ALL ZERO**

### 🧠 BRAIN FIRED AGAIN — 5 decisions, **5th cycle of byte-identical pattern**

| id | action | target | reason |
|---|---|---|---|
| #471 | TIGHTEN_FILTER | KING7777777 | "Brain: 12 BAD_PRICE losses" |
| #472 | PAUSE_TRADER | sovereign2013 | "5 consecutive losses" (log-only) |
| #473 | PAUSE_TRADER | xsaghav | "7d PnL $-122.71 < -$20" (log-only) |
| #474 | PAUSE_TRADER | fsavhlc | "7d PnL $-21.05 < -$20" (log-only) |
| #475 | RELAX_FILTER | KING7777777 | "7d pnl=$31.52 wr=53% tier=solid" |

**5 consecutive brain cycles writing the same 5 rows.** That's 25 duplicate rows accumulated for information that could be deduped to 5. Not catastrophic but wasteful. Settings hash was `c382ab9...` before brain fired and `c382ab9...` after — the TIGHTEN+RELAX pair on KING cancels out to zero net file content change. **Cosmetic no-op writes.**

Morning report: add `brain_decisions` cross-cycle dedup as a recommendation. The dedup I added in Round 4 Task 4 only protects WITHIN a single `_classify_losses` pass; it doesn't stop identical decisions across 2h cycles.

### 🤖 ML TRAINING NUMBERS EXPOSED (from log grep)

The 06:04:57 retrain logged detailed output that confirms Round 4 Task 8 is actually working:

```
[ML] Class balance: 2892 wins / 6122 losses (32.1% win rate)
[ML] Trained on 9014 samples (614 copy + 8400 blocked) | Train: 94.7% | Test: 94.9% | Baseline: 65.3%
```

**Reading this carefully:**

| Metric | Value | Interpretation |
|---|---|---|
| Total samples | 9014 | 614 real copy_trades + 8400 blocked outcomes |
| Class balance | 32.1% wins | Heavy imbalance toward losses |
| Majority baseline | **65.3%** test accuracy | Always-predict-loss gets this for free |
| Train accuracy | 94.7% | |
| Test accuracy | **94.9%** | 29.6pp over baseline |

**Good news:** the baseline+class-balance logging from my Round 4 fix is live and working. We now know exactly how much the model beats the dumb baseline.

**Bad news (NEW FLAG: ML_ACCURACY_STILL_SUSPICIOUS):**

1. **Test > Train** (94.9 > 94.7) — unusual for non-pathological cases. Hints at either a small lucky test slice or underfitting on train.
2. **94.9% test accuracy is implausibly high** for a 5-feature model (`entry_price, category, side, hour, day_of_week`) on noisy prediction market outcomes. Real-world accurate binary classifiers on this kind of data land 55–70%, not 95%.
3. **29.6pp gap over baseline** — if this were real signal, we'd be printing money. Since we're net-losing money, something in the features is leaking the label.
4. **The mix**: 614 copy + 8400 blocked means the model is dominated (93%) by `blocked_trades` with `would_have_won` outcomes populated by `outcome_tracker`. If the resolved-at-0-or-1 price signal correlates trivially with `entry_price`, the model can predict "extreme price → matches-resolution direction" with high accuracy.

**Hypothesis for remaining leakage**: `blocked_trades` are heavily concentrated in categories where sovereign2013's bets outside 42-70c range get rejected. Those same extreme-price markets tend to resolve close to their quoted price (heavy favorites → win at ~85c entry, heavy underdogs → lose at ~15c entry). So "extreme entry_price" is a near-perfect predictor of "price at resolution matches entry direction" — which the outcome_tracker counts as `would_have_won=1` for favorites.

If that's true, the 94.9% accuracy means **"high entry → won, low entry → lost"** which is a trivial majority-side statement, not a useful signal for live trading (where we're trading more balanced 40-60c markets, not 15/85c extremes).

**Morning report: flag ML_ACCURACY_STILL_SUSPICIOUS as a remaining leakage suspicion in the feature/label pipeline. Recommend computing a confusion matrix on just the 614 copy_trades subset to see real-world model usefulness.**

### Every new blocked trade — 1840 (-7% vs iter 18)

| Reason | Count |
|---|---|
| price_range | 902 (49%) |
| event_timing | 543 (still stuck same count as iter 14-18) |
| no_rebuy | 214 (tapering from 276 iter 17) |
| category_blacklist | 181 |

**`event_timing` count has been 543±6 across iters 14-19** — confirms there's a fixed set of pre-game markets being re-evaluated every cycle without dedup.

**By trader:**
- 0x3e5b23e9f7: 935 (50.8%)
- sovereign2013: 905 (49.2%)
- **Jargs: 0** (was 53 iter 18, 180 earlier). Genuinely inactive on Polymarket now.

### Trader 7d rolling — ALL FROZEN

No movement. Same as iter 17/18.

### Feedback coverage — **742/59/7.9%** (14 iterations stuck)

### Flags this iter

- [x] **ML_ACCURACY_STILL_SUSPICIOUS** (NEW): 94.9% test accuracy, 65.3% baseline, 29.6pp gap. Real model signal should be 5-15pp not 30pp. Likely feature leakage via entry_price/category correlation with blocked_trades resolution outcomes. Recommend confusion matrix on 614-copy-trades subset only.
- [x] **BRAIN_CYCLE_5_IDENTICAL**: fifth consecutive cycle writing same 5 decision rows. 25 cumulative duplicates. Hash net-unchanged (TIGHTEN+RELAX cancel).
- [x] **JARGS_ZERO_BLOCKS**: completely gone from block count, confirming Polymarket-side inactivity (not scan issue).
- [x] **EVENT_TIMING_STUCK_543**: same pre-game batch being re-blocked 5 iterations running. Dedup opportunity.
- [x] **FEEDBACK_STUCK_14_ITERS**: 742/59 unchanged.
- [x] carries (TRAILING_STOP_BAD_FILL, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, WHALE_AUTO_COPY_PATH, SOVEREIGN_EROSION).
- [ ] no BOT_CRASHING

### One-line summary

Iter 19 (Δ15min): Portfolio $95.58 (Δ -$0.20). 0 closes. **Brain fired 5th cycle verbatim identical**. **ML numbers exposed from log grep**: 9014 samples, 32.1% class balance, Train 94.7% / Test 94.9% / Baseline 65.3%. **29.6pp gap over baseline is suspicious — likely feature leakage via entry_price/category correlation with blocked_trades resolution outcomes** (new flag ML_ACCURACY_STILL_SUSPICIOUS). Jargs now 0 blocks (totally idle).

---

## Iteration 18 — 2026-04-13 06:08 UTC (Δt ≈ 38 min) — ML retrained, whale #1, settings rotated

### Snapshot
- **Portfolio**: $95.78 (Δ **-$0.10** since iter 17 $95.88)
  - Wallet: $78.34 (unchanged)
  - Positions: $17.54 → $17.44 (-$0.10) — small reval
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 1 (known auto_discovery 400)
- **blocked_trades table size**: **528,778 rows** (up ~87k since iter 1, ~15k/hour)

### 🤖 ML RETRAINED! Last train `2026-04-13 06:04:57` (was `2026-04-12 21:35:52`)

**ML_SCHEDULER_SILENT flag RETRACTED.** The `ml_train_job` did fire, ~8h29m after the previous training. NOT the 6h cadence I assumed from the CHANGELOG — actual interval was closer to 8.5h. Could be:
- Every-6h cron with drift from apscheduler jitter
- Data-count-triggered threshold finally hit
- Some other irregular schedule

Either way: **training happened**, no silent skip from my Round 4 single-class guard. The time-split fix is working. Need to grep the log for the `[ML] Class balance` and `[ML] Baseline` lines to see the actual numbers — those aren't persisted to the DB. Worth checking next iter.

### ⚙️ SETTINGS_HASH CHANGED

Hash: `b4de11f...` → `c382ab9...`. 

**Important context**: brain didn't fire this iter (`N_BRAIN=0`), but hash changed. The most likely writer is **auto_tuner** running its 2h scheduled job independently of the brain cycle. auto_tuner refreshes all per-trader tier maps (BET_SIZE_MAP, MIN/MAX_ENTRY_PRICE_MAP, etc.) without logging `brain_decisions`. Consistent with piff's design.

### Every new closed / open / score / brain — ALL ZERO in DB

### Every new blocked trade — **1984** (down from 2111 → -6%)

| Reason | Iter 17 | Iter 18 | Δ |
|---|---|---|---|
| price_range | 930 | 952 | ~0% |
| event_timing | 543 | 537 | 0% (same pre-game batch still stuck) |
| no_rebuy | 276 | 264 | -4% |
| category_blacklist | 362 | 231 | -36% |

### 🚨 WHALE OVERTOOK SOVEREIGN2013 — first time this session

| Trader | Iter 17 blocks | Iter 18 blocks | Δ | Share |
|---|---|---|---|---|
| **0x3e5b23e9f7** | 844 | **984** | +17% | **49.6%** |
| sovereign2013 | 1086 | 947 | -13% | 47.7% |
| Jargs | 181 | **53** | -71% | 2.7% |

**First iter where the whale-scan produces MORE blocks than sovereign2013.** The whale is now the #1 source of trading attempts. sovereign2013's attempt volume is slowly winding down (overnight, his markets resolving) while the whale continues probing Peruvian election markets.

**Jargs dropped from 181 → 53 blocks (-71%)**. Either:
- Jargs genuinely went quiet on Polymarket side (most likely)
- auto_discovery re-prioritized scan order and is visiting Jargs less frequently
- The ~180 count for the last few iters was a cached stale count that finally refreshed

### Trader 7d rolling — ALL UNCHANGED (frozen)

Same as iter 17. No aging, no closes, no new activity. sovereign2013 locked at -$40.00, whale at n=4 / -$0.81.

### Feedback coverage — **742/59/7.9%** (13 iterations stuck)

### Flags this iter

- [x] **ML_RETRAINED** (RETRACTING EARLIER FLAG): job fired at 06:04:57, ~8h29m after previous train. Not 6h cron. ML_SCHEDULER_SILENT flag was a false alarm. No silent skip from my Round 4 single-class guard.
- [x] **WHALE_DOMINANT_BLOCKS**: 0x3e5b23e9f7 at 49.6% (984), sovereign2013 at 47.7% (947). First time whale > sovereign in share.
- [x] **JARGS_BLOCK_DROP_71%**: 181 → 53. Genuine Jargs inactivity likely.
- [x] **SETTINGS_ROTATED**: hash changed without brain firing → auto_tuner-only update. Consistent with 2h tuner cadence.
- [x] **BLOCKED_TRADES_TABLE_528K**: ~87k row growth over session (~15k/hour sustained). At this rate the table will cross 1M rows later today. Storage/query pressure building. Morning report: recommend retention policy or rollup.
- [x] **FEEDBACK_STUCK_13_ITERS**: 742/59 = 7.9% unchanged for 13 iters.
- [x] carries (TRAILING_STOP_BAD_FILL, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, WHALE_AUTO_COPY_PATH).
- [ ] no BOT_CRASHING

### One-line summary

Iter 18 (Δ38min): Portfolio $95.78 (Δ -$0.10). **ML retrained at 06:04:57 after ~8h29m gap — ML_SCHEDULER_SILENT flag retracted**. **Whale 0x3e5b23e9f7 overtook sovereign2013 in block share (984 vs 947, first time)**. Settings rotated (auto_tuner ran, no brain). Jargs blocks dropped 71% (genuinely idle). blocked_trades table at 528k rows, +87k over session. Feedback coverage stuck 13 iters running.

---

## Iteration 17 — 2026-04-13 05:30 (Δt ≈ 15 min) — whale dominating blocks

### Snapshot
- **Portfolio**: $95.88 (Δ **-$0.28** since iter 16)
  - Wallet: $78.34 (unchanged)
  - Positions: $17.82 → $17.54 (-$0.28) — reval drift
- **Today PnL**: -$1.73 / 6 closes / 0 wins (unchanged, 0 new closes)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0
- **ML**: still 21:35:52 (~8h old)

### Every new closed / open / score / brain — **ALL ZERO**

Nothing new in the DB. Quiet cycle.

### Every new blocked trade — **2111** (up from 1537 → +37%)

Block count bounced up slightly from iter 16's floor. But the composition shifted dramatically.

| Reason | Iter 16 | Iter 17 | Δ |
|---|---|---|---|
| price_range | 531 | **930** | +75% |
| event_timing | 537 | 543 | 0% (stuck) |
| category_blacklist | 358 | 362 | 0% |
| **no_rebuy** | 99 | **276** | **+179%** |
| max_copies | 4 | 0 | fade |
| min_trader_usd | 8 | 0 | gone |

**`no_rebuy` more than doubled** — the Peruvian election market cooldowns from iter 16 are still firing repeatedly. The whale keeps trying to rebuy those markets and the bot correctly keeps blocking them.

### 🐋 By trader — whale nearly matching sovereign2013

| Trader | Iter 16 | Iter 17 | Δ |
|---|---|---|---|
| sovereign2013 | 1074 | **1086** | ~0% |
| **0x3e5b23e9f7** | 284 | **844** | **+197%** (3x surge) |
| Jargs | 179 | 181 | ~0% |

**The whale now represents 40% of all blocks this iter** (844 / 2111), up from ~14% last iter. Previously sovereign2013 was always 95%+ of blocks. **Now the whale-scan path is almost matching sovereign2013's attempt rate.**

This confirms that the auto_discovery/whale-scan path scales aggressively: once a whale is in `trader_lifecycle.DISCOVERED` state, the bot scans his wallet continuously and re-attempts every buy on every cycle. That's how 284 → 844 in one 15-minute window.

### Trader 7d rolling — FROZEN

Every single row unchanged from iter 16 → iter 17. No aging, no closes, no new activity. sovereign2013 still -$40.00, whale still -$0.81 at n=4.

### Feedback coverage — **742/59/7.9%** (12 iterations now with no movement)

### Flags this iter

- [x] **WHALE_BLOCK_SHARE_SURGE**: 0x3e5b23e9f7 now 40% of all blocks (up from 14% iter 16). Whale scan is nearly matching sovereign2013's attempt rate. Scan loop is scaling whale-wallet attempts aggressively.
- [x] **NO_REBUY_COOLDOWNS_FIRING_REPEATEDLY**: 276 blocks — the 2 whale closes from iter 16 keep triggering the 120min rebuy guard. Working as designed but noisy.
- [x] **PORTFOLIO_TINY_DRIFT**: -$0.28 reval on off-DB positions. Noise floor.
- [x] **FEEDBACK_COVERAGE_STUCK_12_ITERS**: 742/59 unchanged. Confirms architectural disconnect between scorer and real buy path.
- [x] **ALL_TRADERS_FROZEN**: no 7d rolling movement for any trader this iter.
- [x] carries (TRAILING_STOP_BAD_FILL, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, WHALE_AUTO_COPY_PATH, ML_SCHEDULER_SILENT, JARGS_IDLE).
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 17 (Δ15min, quiet): Portfolio $95.88 (Δ -$0.28 reval). 0 new closes/opens/scores/brain. 2111 new blocks (+37%) but composition shifted: **whale 0x3e5b23e9f7 now 40% of all blocks (up from 14%)**, effectively matching sovereign2013's attempt rate. auto_discovery whale-scan is aggressive. `no_rebuy` +179% from still-firing Peruvian election cooldowns. Feedback coverage stuck 12 iters running.

---

## Iteration 16 — 2026-04-13 05:15 (Δt ≈ 95 min) — whale activity surge

### Snapshot
- **Portfolio**: $96.16 (Δ **-$0.26** since iter 15)
  - Wallet: $81.06 → **$78.34** (-$2.72) — **real cash out**
  - Positions: $15.36 → **$17.82** (+$2.46) — new positions opened
  - Net: -$0.26 drag (spent $2.72 on positions now worth $2.46)
- **Today PnL**: -$1.73 on **6 closes** / 0 wins (was 4/-$1.62 last iter → **2 new closes**, both whale)
- **Open (DB)**: 0 (the new positions aren't tracked in copy_trades — whale-scan path again)
- **Bot errors last 10min**: 1 (known auto_discovery 400)
- **ML**: still 21:35:52 (~7h30m old now)

### 🐋 Whale 0x3e5b23e9f7 escalating — 2 more closes, both Peruvian election

| id | market | size | recv | pnl | time |
|---|---|---|---|---|---|
| **#3126** | Will Rafael López Aliaga win 2026 Peruvian presidential election? | **$8.00** | null | **-$0.11** | 04:57:41 |
| **#3127** | Will Keiko Fujimori win 2026 Peruvian presidential election? (third time) | $1.00 | null | $0.00 | 05:00:41 |

**Two observations:**

1. **#3126 is size=$8.00** — that's 5-8x bigger than any previous whale copy ($1.47, $1.00, $1.00, $1.47). This whale-scan path is scaling up. Our bet-sizing for `0x3e5b23e9f7` is apparently not tier-constrained because he's not in FOLLOWED_TRADERS at all.

2. **Third bet on Keiko Fujimori** market (#3124 iter 7, #3125 iter 11, #3127 now). The `NO_REBUY_MINUTES=120` cooldown only blocks re-entries in copy_trades — but these whale entries keep coming via a path that seems to treat the 120-min window differently. Or the whale is making trades far enough apart (#3124 at 00:11 → #3125 at 02:36 → #3127 at 05:00 ≈ 2.5h gaps) to slip past the cooldown.

**Running total for 0x3e5b23e9f7**: 4 copy_trades, 0 wins, 1 loss (-$0.70), 3 NO_USDC, **total pnl -$0.81**. The whale is slowly bleeding.

**Critical note**: Our wallet spent **$2.72** this iter. That almost certainly includes the #3126 size=$8 entry — but size=$8 should have cost ~$4-6 at entry (not $2.72). Either entry was at very deep slippage or there's more math I can't see. Morning report should check: what was the entry price for #3126?

### Every new closed trade — 2 (both whale, detected via improved query)
### Every new open — 0 in DB (but $17.82 on-chain — off-DB divergence continues)

### 🧠 Brain — no new fire this iter

### Every new blocked trade — 1537 (down from 2099 → -27%)

Block count continuing to collapse. Rate ~100/min now (vs iter 5 peak ~900/min).

| Reason | Iter 15 | Iter 16 | Δ |
|---|---|---|---|
| **event_timing** | 540 | **537** | 0% (stuck count, same pre-game batch still re-evaluating) |
| price_range | 1184 | 531 | -55% |
| category_blacklist | 360 | 358 | 0% |
| **no_rebuy** | 13 | **99** | +661% (NEW surge — 2 whale closes triggered 120min cooldowns) |
| min_trader_usd | 2 | 8 | minor |
| max_copies | 0 | 4 | minor |

**`no_rebuy: 99` surge**: the 2 whale closes at 04:57 and 05:00 triggered 120-min cooldowns on those markets. 99 subsequent scan attempts on Keiko Fujimori / Rafael López Aliaga got blocked by the rebuy guard. Expected behavior.

**By trader:**
- sovereign2013: 1074 (70% — **lowest share** of any iter this session, whales catching up)
- **0x3e5b23e9f7: 284** (up from 132 → 2.15x surge — whale very active)
- Jargs: 179 (still functionally idle)

### Every new score / brain decision — 0

### Trader 7d rolling

| Trader | Iter 15 | Iter 16 | ΔPnL |
|---|---|---|---|
| sovereign2013 | 173, -$40.00 | 173, -$40.00 | 0 (frozen) |
| **0x3e5b23e9f7** | 2, -$0.70 | **4, -$0.81** | -$0.11 (new whale closes) |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 |
| aenews2 | 0 | 0 | 0 |

Only 0x3e5b23e9f7 moved. All 5 followed traders completely idle — hasn't been a followed-trader close since iter 9.

### Feedback coverage — 742/59 = 7.9% (unchanged)

Again: 2 new closes neither got outcome_pnl because the whale path bypasses the scorer. The 59 counter hasn't moved since iter 1's baseline backfill. **It might never move again given the current buy-path distribution.**

### Flags this iter

- [x] **WHALE_AUTO_COPY_ESCALATING** (updated): n=1 iter 7 → n=2 iter 11 → **n=4 iter 16**. Growing share of trades. #3126 was **size $8** (5x larger than prior whale entries). auto_discovery path is taking bigger positions on DISCOVERED wallets without tier gating.
- [x] **CASH_OUT_2.72**: wallet -$2.72 reflects real buys into the off-DB positions tracking. Matching the $2.46 new positions value.
- [x] **NO_REBUY_SURGE**: +661% blocks for `no_rebuy` reason — correctly guarding the 120min cooldowns on the just-closed whale markets.
- [x] **SOVEREIGN_FROZEN_AT_-$40**: second iter in a row with no change. Rolling-window erosion stopped for now.
- [x] **FOLLOWED_TRADERS_IDLE_SINCE_ITER_9**: no closes from any of the 5 official followed traders in 6+ iterations. The only real activity is sovereign2013's attempts (all blocked) + the whale. Overnight behavior.
- [x] **FEEDBACK_LOOP_NEVER_GROWING**: 59/742 coverage hasn't moved in 11 iterations. Architectural gap confirmed: the scorer is completely disconnected from the buy path that actually produces trades.
- [x] **BRAIN_CYCLIC_SPAM** (carry, 4 cycles confirmed)
- [x] **BRAIN_DATA_DIVERGENCE** (carry, 4 cycles confirmed)
- [x] **BLOCK_COUNT_TAPER**: 11372 peak → 1537 now = 86% reduction from peak. Overnight floor nearly reached.
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 16 (Δ95min): **Whale auto-copy path escalating** — 2 new whale closes (#3126 Rafael López Aliaga **$8 size** -$0.11, #3127 Keiko Fujimori rebuy $0). Wallet -$2.72 real spend. 0x3e5b23e9f7 n=4 total pnl -$0.81. sovereign2013 frozen -$40. 1537 new blocks (-27%, 86% below session peak). No new scores/brain. Feedback coverage stuck 11 iters running — the scorer is architecturally disconnected from the real buy path.

---

## Iteration 15 — 2026-04-13 03:40 (Δt ≈ 15 min) — Brain fired again, wallet +$1.02

### Snapshot
- **Portfolio**: $96.42 (Δ **+$0.06**)
  - **Wallet: $80.04 → $81.06 (+$1.02)** — real cash inflow
  - Positions: $16.32 → $15.36 (-$0.96)
- **Today PnL**: -$1.62 / 4 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0
- **ML**: **STILL 21:35:52** — 6h5m old now, **zero `[ML]` log lines in last 2 hours**

### 💰 Wallet +$1.02 but no DB close → off-DB event

Some off-DB position was sold or redeemed. Likely candidates:
- `auto_redeem` picked up a ~$1 position from the old $16 on-chain set and redeemed it (positions -$0.96 matches roughly)
- A stale position somehow closed without writing to `copy_trades`

Either way, **real cash landed in the wallet** that we don't see in our DB. Morning report: the reconciliation job recommendation gets stronger evidence this iter.

### Every new closed / open / score — ALL ZERO

### 🧠 BRAIN FIRED AGAIN — 5 decisions, IDENTICAL pattern (3rd consecutive cycle)

| id | action | target | reason |
|---|---|---|---|
| #466 | TIGHTEN_FILTER | KING7777777 | "Brain: 12 BAD_PRICE losses for KING7777777" |
| #467 | PAUSE_TRADER | sovereign2013 | "5 consecutive losses" |
| #468 | PAUSE_TRADER | xsaghav | "7d PnL $-122.71 < -$20" |
| #469 | PAUSE_TRADER | fsavhlc | "7d PnL $-21.05 < -$20" |
| #470 | RELAX_FILTER | KING7777777 | "7d pnl=$31.52 wr=53% tier=solid" |

**BYTE-for-BYTE identical to iter 11's #461-#465.** This is the third cycle in a row producing the exact same 5 rows:
- Cycle A (iter 6): #453-456 (4 decisions, no sovereign pause yet)
- Cycle B (iter 7): #457-460 (4 decisions, same)
- Cycle C (iter 11): #461-465 (5 decisions, sovereign joined)
- Cycle D (iter 15): #466-470 (5 decisions, same as C)

`brain_decisions` is now accumulating ~5 duplicate rows per 90-120min brain cycle with no dedup. If the bot runs for a week unchanged, that's ~60-80 brain cycles × 5 = 300-400 duplicate rows for information that could be represented as 5 rows with a `last_seen_ts` column.

**Also still showing BRAIN_DATA_DIVERGENCE: KING 7d pnl brain-view +$31.52/53% vs ralph -$9.75/41%.** 4 brain cycles with the same divergence. The source of `db.get_trader_rolling_pnl` needs investigation.

### Every new blocked — 2099 (down from 4563 → -54%)

Block count **collapsing** — bot is winding down for the night. Rate ~140/min (lowest this session).

| Reason | Iter 14 | Iter 15 | Δ |
|---|---|---|---|
| price_range | 3639 | **1184** | -67% |
| event_timing | 534 | 540 | 0% (exact, same game batch) |
| category_blacklist | 356 | 360 | ~0 |
| no_rebuy | 33 | 13 | -61% |
| min_trader_usd | 1 | 2 | trivial |

**`event_timing` stuck at 540** — same exact count as iter 13+14. Those blocks are being logged against the same set of pre-game markets that are still outside the 8h window. The bot keeps re-evaluating them every scan cycle.

**By trader:**
- sovereign2013: 1787 (85% — lowest % share of blocks this session)
- Jargs: **180** (EXACT same count as iter 11 and iter 13 — Jargs truly idle)
- 0x3e5b23e9f7: 132 (up from 71 — whale scan picked up)

### Trader 7d rolling — sovereign2013 RECOVERY

| Trader | Iter 14 | Iter 15 | ΔPnL |
|---|---|---|---|
| **sovereign2013** | 175, -$50.51 | **173, -$40.00** | **+$10.51** (2 big losers aged out) |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 |

**sovereign2013 bounced back +$10.51** via window-shift. 2 trades aged out of the 7d window, both losers, net contribution -$10.51 to the 7d sum → removing them added +$10.51. He went from session-low -$50.51 back to -$40.00. Still in the red but the erosion stopped.

Worth noting: the brain fired in this iter and STILL saw KING +$31.52 (not sovereign's recovery). Brain data source is definitely different.

### Feedback coverage — 742/59/7.9% (unchanged)

### 🚨 FLAG: ML_COMPLETELY_SILENT_2H

`[ML]` log grep over last 2 hours: **0 lines**. Zero. The `ml_train_job` scheduler entry added `[ML]` logs on every successful or skipped run via my Round 4 fix. If it were firing, we'd see something. 

**Updated hypothesis**: the ml_train_job scheduler interval is NOT 6h as I assumed from the CHANGELOG. The 3 rapid-fire trainings at session start (21:31, 21:32, 21:35) suggest it might be triggered by something else (bot startup, data-count threshold, manual invocation). Since there's been nothing new to trigger it, it simply hasn't fired. Worth grepping for "ml_train_job" in the scheduler config or main.py to find the actual trigger.

Less likely but possible: `MIN_TRAINING_SAMPLES` check or some other early-return blocks it silently without logging.

### Flags this iter

- [x] **BRAIN_CYCLIC_SPAM_CONFIRMED_PATTERN**: 4 consecutive cycles (B/C/D, all writing same 4-5 rows). 18-20 duplicate rows accumulated over the session. 
- [x] **SOVEREIGN_RECOVERED**: -$50.51 → -$40.00 (+$10.51 window shift, 2 big losers aged out). Moved back from session-low.
- [x] **WALLET_OFF_DB_INFLOW**: +$1.02 landed in wallet with no DB-tracked close. Second confirmation of off-DB reconciliation need.
- [x] **ML_SCHEDULER_SILENT_2H** (ESCALATED): zero `[ML]` log lines in 2h. Hypothesis revised: the job isn't on a 6h cron, it's startup-triggered or data-count-triggered. Not necessarily a bug, just different from what I documented.
- [x] **BLOCK_COUNT_FLOOR**: 2099 blocks (lowest of session). The `event_timing` 540 count is exact-same across iter 13-15, meaning the same set of pre-game markets keeps getting re-evaluated. Block dedup would cut this entirely.
- [x] **JARGS_IDLE_CONSTANT**: 180 blocks for 3 iterations — Jargs has made zero new attempts.
- [x] **BRAIN_DATA_DIVERGENCE** (carry, 4th cycle confirmed): brain KING +$31.52 vs ralph -$9.75.
- [x] carries: TRAILING_STOP_BAD_FILL, FEEDBACK_LOOP_COVERAGE_GAP, DB_VS_WALLET, WHALE_AUTO_COPY_PATH.
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 15 (Δ15min): Portfolio $96.42 (Δ +$0.06), **wallet +$1.02 off-DB inflow** (auto_redeem likely). **Brain fired 5 decisions, byte-identical to iter 11** — BRAIN_CYCLIC_SPAM confirmed 3 cycles running, brain still sees KING +$31.52. **sovereign2013 window-shift recovery -$50.51 → -$40.00** (+$10.51, 2 big losers aged out). Blocks collapsed to 2099 (lowest session). **Zero `[ML]` log lines in 2h** — ml_train_job likely not 6h-cron, probably startup/data-triggered.

---

## Iteration 14 — 2026-04-13 03:25 (Δt ≈ 15 min) — still dead quiet

### Snapshot
- **Portfolio**: $96.36 (Δ **-$0.01** noise floor again)
  - Wallet: $80.04 (unchanged)
  - Positions: $16.34 → $16.32 (-$0.02)
- **Today PnL**: -$1.62 / 4 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0
- **ML**: **STILL** 21:35:52 — 5h50m old, `ml_trainings_since_iter1 = 0`

### Every new closed / open / score / brain — ALL ZERO (2nd iter in a row)

Two consecutive dead-quiet iterations. Nothing moved in trader_rolling_7d either — everything frozen at iter 13 values.

### Every new blocked trade — 4563 (down from 5050 → -10%)

| Reason | Iter 13 | Iter 14 | Δ |
|---|---|---|---|
| price_range | 3988 | **3639** | -9% |
| event_timing | 540 | 534 | ~0% |
| category_blacklist | 496 | 356 | -28% |
| no_rebuy | 26 | 33 | +27% |
| min_trader_usd | 0 | 1 | trivial |

No new reasons, no exposure_limit, no scoring. Just sovereign2013 pounding the same 5-10 markets while his prices drift outside the 42-70c window.

**By trader:**
- sovereign2013: 4314 (95%)
- Jargs: 178 (was 180 — essentially idle, tiny fluctuation)
- 0x3e5b23e9f7: 71 (up from 26 — whale somewhat active)
- 0x6bab41a0dc: 0 (appeared once iter 13, gone again)

### Trader 7d rolling — FROZEN

All 7 tracked entries identical to iter 13. No aging this iter. sovereign2013 still locked at -$50.51.

### Feedback coverage — still 742/59 = 7.9%

### 🚨 FLAG: ML_RETRAIN_OVERDUE — now at 5h50m

Last training was 2026-04-12 21:35:52 (the third of 3 back-to-back trainings at session start). ZERO retrainings have happened since then. ML is supposed to run every 6h per CHANGELOG. Current age: **5h50m**. The 6h mark hits in ~10 minutes. If the next iter still shows no new training, this is a real scheduler bug.

Candidate causes:
- `ml_train_job` scheduler entry not firing
- Fires but throws exception silently
- Fires but finds `len(copy_rows) + len(blocked_rows) < MIN_TRAINING_SAMPLES=50` → early return (unlikely since 7306 samples last time)
- Time-split check fails (`if len(set(y_train)) < 2` → "Time-split produced single-class train/test — skipping")

The last one is plausible: my Round 4 Task 8 added a guard that skips training if the time-split produces a single-class subset. If all recent closes are losers (which today's closes show: 4/4 losers today), the last 20% of sorted data may have all y=0 — forcing the skip. That would explain zero trainings since iter 1.

### Flags this iter

- [x] **ML_RETRAIN_OVERDUE_ESCALATING**: 0 retrains in 14 iterations over ~5h50m. Probable cause: my own Round 4 time-split single-class skip. Morning report must include this as a self-inflicted bug.
- [x] **SECOND_DEAD_QUIET**: 2 consecutive full-idle iterations (13 + 14). Complete stagnation. Not a bug, expected overnight-gap behavior.
- [x] **BLOCK_COUNT_TAPERING**: 11372 → 9370 → 7025 → 7714 → 6602 → 7390 → 6499 → 5050 → 4563 over the last 9 iters. Monotonic decline since iter 5 peak. Evening sports winding down.
- [x] carry flags unchanged (TRAILING_STOP_BAD_FILL, FEEDBACK_LOOP_COVERAGE_GAP, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET, WHALE_AUTO_COPY_PATH, SOVEREIGN_EROSION).
- [ ] no BOT_CRASHING (0 errors 2 iters in a row)
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 14 (Δ15min, still dead quiet): Portfolio $96.36 (Δ -$0.01 noise). **0 activity** in closes/opens/scores/brain — 2 consecutive zero-activity iters. 4563 new blocks all sovereign2013 (block count tapering monotonically since iter 5 peak). **ML retrain now 5h50m overdue** — plausible cause is my own Round 4 time-split single-class skip logic. Will escalate at iter 15 if still no retrain.

---

## Iteration 13 — 2026-04-13 03:10 (Δt ≈ 15 min) — dead quiet

### Snapshot
- **Portfolio**: $96.37 (Δ **-$0.01** vs iter 12 — essentially flat)
  - Wallet: $80.04 (unchanged)
  - Positions: $16.34 (unchanged — not even noise)
- **Today PnL**: -$1.62 / 4 closes / 0 wins (unchanged)
- **Open (DB)**: 0
- **Bot errors last 10min**: 0 (clean)
- **ML**: still 21:35:52, **5h35m old**, ML_NEW_TRAINS=0 since iter 1. Retrain remains overdue (6h mark in ~25min).

### Every new closed trade / open / score / brain decision — **ALL ZERO**

This is the quietest iter of the session: nothing closed, nothing opened, scorer didn't fire, brain didn't fire, trader rolling stats unchanged across the board, settings hash stable, wallet unchanged.

The only activity is the continuing block spam.

### Every new blocked trade — 5050 (down from 6499 → -22%)

Block count continues tapering as US late-night sports resolve and tomorrow's markets push into the `event_timing` window.

| Reason | Iter 12 | Iter 13 | Δ |
|---|---|---|---|
| **price_range** | 4307 | **3988** | -7% (still #1 at 79%) |
| exposure_limit | 1494 | **0** | **gone** |
| category_blacklist | 539 | 496 | -8% |
| **event_timing** | 100 | **540** | +440% (5.4x surge) |
| score_block | 12 | 0 | fade |
| no_rebuy | 46 | 26 | fade |
| max_copies | 0 | 0 | gone |
| min_trader_usd | 1 | 0 | gone |

**`exposure_limit` disappeared entirely.** Makes sense: we have 0 open positions, so nothing to exposure-cap against. All remaining blocks are at earlier filter stages (price, timing, category, rebuy cooldown).

**`event_timing` surged 5.4x** (100 → 540). Sovereign2013 is placing bets on games >8h in the future — likely tomorrow's MLB day game cards. `MAX_HOURS_BEFORE_EVENT=8` correctly blocks them.

**By trader:**
- sovereign2013: 4843 (96%)
- Jargs: 180 (UNCHANGED since iter 11 — idle, no new activity)
- 0x3e5b23e9f7: 26 (down from 125, whale slowing)
- **0x6bab41a0dc: 1** (new: second whale wallet appearing in scans)

### Trader 7d rolling — ALL UNCHANGED

| Trader | n | pnl | Δ from iter 12 |
|---|---|---|---|
| sovereign2013 | 175 | -$50.51 | **0** (no aging this iter) |
| xsaghav | 187 | -$122.71 | 0 |
| KING7777777 | 133 | -$9.75 | 0 (brain still divergent) |
| fsavhlc | 20 | -$21.05 | 0 |
| Jargs | 17 | -$10.67 | 0 |
| aenews2 | 0 | - | 0 |
| 0x3e5b23e9f7 | 2 | -$0.70 | 0 |

### Feedback coverage — still 742/59 = 7.9% (unchanged)

### Flags this iter

- [x] **DEAD_QUIET_ITER**: 0 closes, 0 opens, 0 scores, 0 brain, 0 trader-stat movements, 0 settings drift, 0 errors. Portfolio moved $0.01 (noise floor).
- [x] **EXPOSURE_LIMIT_GONE**: dropped to 0 blocks (was 1494 last iter) — consequence of 0 open positions means nothing to max-out.
- [x] **EVENT_TIMING_SURGE**: +540% growth → sovereign moving to tomorrow's pre-game markets.
- [x] **ML_RETRAIN_STILL_OVERDUE**: 0 new retrains since iter 1. 6h mark hits in ~25min. If not retrained by iter 15, definite flag.
- [x] **JARGS_STILL_IDLE**: 180 blocks since iter 11 unchanged → Jargs is genuinely inactive, no new attempts being made.
- [x] **WHALE_WALLET_EXPANSION**: 0x6bab41a0dc shows up for the first time with 1 block. That's the second DISCOVERED whale entering scan range after 0x3e5b23e9f7.
- [x] carry flags (TRAILING_STOP_BAD_FILL, FEEDBACK_LOOP_COVERAGE_GAP, BRAIN_DATA_DIVERGENCE, BRAIN_CYCLIC_SPAM, DB_VS_WALLET_POSITION_DIVERGENCE, WHALE_AUTO_COPY_PATH, SOVEREIGN_EROSION) unchanged.
- [ ] no BOT_CRASHING (0 errors, clean)
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 13 (Δ15min, dead quiet): Portfolio $96.37 (Δ -$0.01 noise). **Zero activity** — 0 closes, 0 opens, 0 scores, 0 brain, all trader stats unchanged. Only blocks continue (5050, -22%); `exposure_limit` disappeared (0 open positions), `event_timing` surged 5.4x as sovereign2013 moves to tomorrow's MLB pre-game markets. ML retrain still overdue. Nothing critical — the bot is idle-waiting for the next sports cycle.

---

## Iteration 12 — 2026-04-13 02:55 (Δt ≈ 15 min)

### Snapshot
- **Portfolio**: $96.38 (Δ **-$0.77** since iter 11 — biggest single-iter drop this session)
  - Wallet: $80.04 (unchanged)
  - Positions: $17.11 → **$16.34** (-$0.77) — pure reval
- **Today PnL**: -$1.62 / 4 closes / 0 wins (unchanged)
- **Open positions (DB)**: 0 (still flat)
- **On-chain positions**: $16.34 (DB_VS_WALLET divergence persists; our off-DB holdings drifted -$0.77)
- **Bot errors last 10min**: 1 (same auto_discovery 400, not critical)
- **ML**: still 21:35:52 — **now 5h20m old, past the 6h mark is coming at 03:35**. Close watch next iter.

### Every new closed trade — NONE (0 new closes)
### Every new open — NONE (0 new buys)

### 🚨 FLAG: LARGEST_PORTFOLIO_SLIP_THIS_SESSION

-$0.77 in 15 minutes from pure position revaluation. Wallet unchanged, no trades. This means the on-chain positions we can't see in DB (that $16.34 set) dropped in quoted value.

If this drift rate continued (-$0.77 per 15min = -$3/hour), we'd be at $90 by morning. That's not happening in reality — this is noise/chop. But it does highlight that **our P&L is now entirely gated on positions we don't track in copy_trades**.

### Every new blocked trade — 6499 (down from 7390 → -12%)

Late-night sports tapering. Rate ~430/min.

| Reason | Iter 11 | Iter 12 | Δ |
|---|---|---|---|
| **price_range** | 3432 | **4307** | +26% (now 66% of all blocks) |
| exposure_limit | 3393 | **1494** | -56% |
| category_blacklist | 538 | 539 | 0% |
| **event_timing** | 0 | **100** | NEW significant |
| no_rebuy | 2 | 46 | +22x |
| **score_block** | 0 | **12** | NEW |
| min_trader_usd | 11 | 1 | fade |
| max_copies | 14 | 0 | fade |

**Big shift in block profile**: price_range dominates (66%), exposure_limit cut in half. sovereign2013 moved from buying markets where we're already capped to buying markets outside his price range (42-70c). Means he's making more extreme-probability bets.

**`event_timing: 100`** — NEW. Our `MAX_HOURS_BEFORE_EVENT=8` window is blocking trades where the sports event is too far in the future. 100 new blocks at this reason means sovereign2013 is betting on games still 8+ hours out.

**`score_block: 12`** matches the 12 new BLOCK-action scores below. Scorer rejected 12 attempts.

**By trader:**
- sovereign2013: 6195 (95%)
- Jargs: 179 (stable — Jargs idle)
- 0x3e5b23e9f7: 125 (down 25% from 166 last iter — whale slowing)

### Every new score — **12 new, ALL BLOCK action**

| action | count | note |
|---|---|---|
| BLOCK | 12 | Scorer woke up, rejected 12 sovereign2013 attempts |
| (no EXECUTE/QUEUE/BOOST) | 0 | |

First scorer activity since iter 5 (which had 281 scores). The scorer is correctly down-rating sovereign2013's current stream of attempts. But the BLOCK actions don't create copy_trades, so the feedback loop gains no data from them.

### Every new brain decision — NONE (next cycle ~04:10)

### Trader 7d deltas

| Trader | Iter 11 | Iter 12 | ΔPnL |
|---|---|---|---|
| **sovereign2013** | 178, -$44.43 | **175, -$50.51** | **-$6.08** (3 winners aged out, losses stayed) |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 |
| 0x3e5b23e9f7 | 2, -$0.70 | 2, -$0.70 | 0 |
| aenews2 | 0 | 0 | 0 |

**sovereign2013 new session low: -$50.51** 7d PnL. He started iter 1 at +$14.12. He's now at -$50.51 = **total session erosion -$64.63 purely from rolling-window aging**. Not from new losing trades — from older winners falling out of the 7d window faster than new winners arrive.

His wins went 83 → 80 (3 winners aged out), losses stayed at 93. Net aged-out contribution: **+$6.08 removed = -$6.08 to displayed pnl**.

7d WR: 80/175 = 45.7% (was 83/178 = 46.6% → dropping).

At this erosion rate (~$5-6 per 15-30min iter since iter 9), sovereign2013 could hit **-$75 to -$100 by morning report time** (~7h away), purely from winners aging out.

### Feedback coverage — 742 / 59 = **7.9%** (dropped from 8.1%)

12 new scores added to total (730 → 742), 0 new outcomes. Ratio dropped from 0.081 to 0.0795. The coverage is slowly **getting worse** each iter because:
1. Scorer adds BLOCK scores (never resolve)
2. Closed trades come from non-scorer buy paths (never match an existing score row)

At current rate, coverage will drop below 5% within another few iterations unless something fills outcomes.

### Flags this iter

- [x] **LARGEST_PORTFOLIO_SLIP**: -$0.77 in 15min from pure reval on off-DB positions. Biggest single-iter drop yet. Not a trend, just chop — but watch.
- [x] **SOVEREIGN_NEW_LOW**: 7d pnl hit -$50.51 (worst this session). 3 more winners aged out. Erosion continuing; extrapolation suggests -$75 to -$100 by morning.
- [x] **SCORER_BURST_12_BLOCKS**: first scorer activity in 6 iterations. All BLOCK, none above threshold. Correctly penalizing sovereign.
- [x] **FEEDBACK_COVERAGE_DROPPING**: 8.1% → 7.9%. Ratio declining each iter as BLOCK scores accumulate without ever resolving.
- [x] **BLOCK_PROFILE_SHIFT**: price_range now 66% dominant (was 46% last iter). exposure_limit halved. sovereign2013 making extreme-probability bets outside his price window.
- [x] **EVENT_TIMING_BLOCKS**: 100 new blocks for games >8h in future. First substantial count of this reason.
- [x] **ML_RETRAIN_DUE**: still 21:35:52 — now 5h20m old. Watch for retrain log at ~03:35.
- [x] **WHALE_AUTO_COPY_PATH** (carry): unchanged this iter.
- [x] **TRAILING_STOP_BAD_FILL** (carry): no new samples.
- [x] **BRAIN_CYCLIC_SPAM** (carry): brain quiet this iter.
- [x] **BRAIN_DATA_DIVERGENCE** (carry): unchanged.
- [x] **DB_VS_WALLET_POSITION_DIVERGENCE** (carry).
- [ ] no BOT_CRASHING (1 known auto_discovery 400)
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 12 (Δ15min): Portfolio $96.38 (Δ **-$0.77**, biggest single-iter drop — pure reval on off-DB positions). 0 new closes, 0 new opens, **12 new scores all BLOCK** (first scorer activity in 6 iterations). **sovereign2013 new session-low -$50.51** (3 more winners aged out, -$6.08 window-shift). Block profile shifted: price_range now 66% dominant. Feedback coverage 8.1% → 7.9% (dropping). ML retrain overdue (~5h20m old).

---

## Iteration 11 — 2026-04-13 02:40 (Δt ≈ 63 min) — BRAIN fired, whale close, PAUSE sovereign triggered

### Snapshot
- **Portfolio**: $97.15 (Δ **+$0.13** since iter 10)
  - Wallet: $80.74 → $80.04 (-$0.70) — matches the new close
  - Positions: $16.29 → $17.11 (+$0.82)
- **Today PnL**: -$1.62 on 4 closes, 0 wins (still 0% WR today)
- **Open positions (DB)**: 0
- **On-chain positions**: $17.11 (DB_VS_WALLET divergence continues)
- **Bot errors last 10min**: 0
- **ML**: still 21:35:52 (5h old — retrain imminent at ~03:35)

### Every new closed trade — 1 new (whale wallet, not a followed trader)

| id | trader | category | size | usdc_received | pnl | kind |
|---|---|---|---|---|---|---|
| **#3125** | `0x3e5b23e9f7` (whale, NOT followed) | geopolitics | $1.47 | $0.77 | **-$0.70** | REAL_SELL |

**Who is 0x3e5b23e9f7?** This wallet appeared as `DISCOVERED` in `trader_lifecycle` at iter 1 (source=polyscan_whale). Iter 7 already had a phantom close #3124 from the same wallet at $0 pnl on the same Peruvian election market. Now #3125 closes at -$0.70.

**The auto_discovery path is creating REAL LOSING COPY TRADES from unfollowed whale wallets.** The wallet is never in `FOLLOWED_TRADERS` and never in a LIVE_FOLLOW lifecycle state — it's still `DISCOVERED`. But `copy_trades` has two rows from it now. Either:
- `auto_discovery` / PATCH-012 whale scanner is taking paper-trade positions that become real
- Or the whale was promoted somewhere we didn't see
- Or there's a scan path that ignores `trader_lifecycle.status` and trades anyway

**This is now a PATTERN not a one-off**. Morning report: investigate auto_discovery / whale-scan buy path, verify it's not making real trades from DISCOVERED wallets.

### 🧠 BRAIN FIRED AGAIN — 5 decisions (was 4 last cycle)

| id | action | target | reason | disable semantic |
|---|---|---|---|---|
| #461 | TIGHTEN_FILTER | KING7777777 | "12 BAD_PRICE losses" | writes settings |
| **#462** | **PAUSE_TRADER** | **sovereign2013** | **"5 consecutive losses"** | **log-only (NEW trigger!)** |
| #463 | PAUSE_TRADER | xsaghav | "7d PnL $-122.71 < -$20" | log-only |
| #464 | PAUSE_TRADER | fsavhlc | "7d PnL $-21.05 < -$20" | log-only |
| #465 | RELAX_FILTER | KING7777777 | "7d pnl=$31.52 wr=53% tier=solid" | writes settings (reverses #461) |

**NEW: sovereign2013 PAUSE_TRADER #462** — **first time** the consecutive-loss streak trigger fired for sovereign2013. The reason is "5 consecutive losses" (not a 7d-PnL threshold). This means sovereign's last 5 closes were all losers. His #3035 closed at -$0.37 in iter 9 and older closes were losses → hit 5-streak.

**BRAIN_CYCLIC_SPAM escalated 4→5 decisions per cycle.** Same pattern as iter 6-7 but with one additional row every cycle because sovereign2013 now also triggers pause. All pauses remain log-only per piff's PATCH-023.

### Every new open — **NONE**

### Every new blocked trade — 7390 (down 4% from iter 10, roughly stable)

| Reason | Iter 10 | Iter 11 | Δ |
|---|---|---|---|
| price_range | 3859 | 3432 | -11% |
| exposure_limit | 3178 | 3393 | +7% |
| category_blacklist | 540 | 538 | ~0% |
| **max_copies** | 0 | **14** | NEW — where from? |
| min_trader_usd | 62 | 11 | -82% |
| no_rebuy | 27 | 2 | fade |

**`max_copies: 14` is puzzling** — we have 0 open positions, so MAX_COPIES_PER_MARKET=1 shouldn't fire. Possibility: auto_discovery or whale scan is creating short-lived position-state that max_copies sees before another scan detects it as closed. Low priority to investigate.

**By trader:**
- sovereign2013: 7045 (95%)
- Jargs: 179 (stable)
- **0x3e5b23e9f7: 166** (up from 5 last iter — 33x jump). This whale is very active and 166 of his moves got blocked plus 1 actually executed as #3125.

### Every new score — **NONE** (0)

### Trader 7d deltas

| Trader | Iter 10 | Iter 11 | ΔPnL |
|---|---|---|---|
| **sovereign2013** | 182, -$46.07 | **178, -$44.43** | **+$1.64** (2 wins + 2 losses aged out, losses were bigger → pnl improved) |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 (brain still sees +$31.52 — DIVERGENCE persists) |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 |
| **0x3e5b23e9f7** | 1, $0 | **2, -$0.70** | -$0.70 (new loser #3125) |
| aenews2 | 0 | 0 | 0 |

sovereign2013 bounced slightly from -$46 → -$44 as 2 larger losses aged out. 7d WR 46.6% (was 46.2%).

**New row**: 0x3e5b23e9f7 now shows n=2 / 0 wins / 1 loss / -$0.70 pnl. Note 2 trades but only 1 loss counted — #3124 had pnl=0 (neither win nor loss), #3125 was -$0.70.

### Feedback coverage — still 730 / 59 / 8.1% (unchanged, 4th iter running)

#3125 is another copy_trade that has no matching trade_scores row — confirmed by the 59 counter not moving. Auto_discovery whale path bypasses scoring just like activity-scan path.

### Flags this iter

- [x] **WHALE_AUTO_COPY_PATH** (NEW): 0x3e5b23e9f7 is `DISCOVERED` only, not followed, yet creates real copy_trades (#3124 $0, #3125 -$0.70). auto_discovery/whale-scan has a buy path that trades DISCOVERED wallets. Morning report: investigate & decide if this is intentional.
- [x] **SOVEREIGN_PAUSE_STREAK_TRIGGER** (NEW): first time `5 consecutive losses` trigger fires for sovereign2013. Previously only 7d-PnL trigger hit. Log-only per piff.
- [x] **BRAIN_CYCLIC_SPAM_5_DECISIONS**: brain pattern grew from 4 → 5 decisions per cycle. Same content duplicated on each 2h fire.
- [x] **BRAIN_DATA_DIVERGENCE_3RD_CYCLE**: KING7777777 brain-view still +$31.52 vs ralph -$9.75. 3 brain cycles in a row. Confirmed persistent.
- [x] **MAX_COPIES_14_BLOCKS**: 14 max_copies blocks this iter despite 0 open positions. Minor mystery — likely whale-scan or race condition.
- [x] **SOVEREIGN_PNL_BOUNCED_SLIGHTLY**: -$46 → -$44 (+$1.64 window shift, 2 big losses aged out).
- [x] **TRAILING_STOP_BAD_FILL** (carry): 2/2 confirmed earlier, no new samples this iter.
- [x] **FEEDBACK_LOOP_COVERAGE_GAP** (carry): #3125 also bypassed scorer. 3 confirmed non-scorer closes now.
- [x] **DB_VS_WALLET_POSITION_DIVERGENCE** (carry): $17.11 on-chain, 0 in DB.
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 11 (Δ63min): Portfolio $97.15 (Δ +$0.13). **Brain fired, 5 decisions (up from 4): new PAUSE_TRADER sovereign2013 for 5-consecutive-losses streak** — first time that trigger fired. **NEW: whale wallet `0x3e5b23e9f7` (DISCOVERED status, not followed) created real copy_trade #3125 -$0.70** — auto_discovery buy path confirmed now trades unfollowed wallets. Today -$1.62 / 4 closes / 0 wins. sovereign2013 -$46 → -$44 window-shift recovery. BRAIN_DATA_DIVERGENCE persists 3rd cycle in a row. Morning report: whale auto-buy path + sovereign streak pause.

---

## Iteration 10 — 2026-04-13 01:37 (Δt ≈ 17 min) — quiet

### Snapshot
- **Portfolio**: $97.02 (Δ **-$0.24** since iter 9)
  - Wallet: $79.11 → **$80.74** (+$1.63)
  - Positions: $18.14 → $16.29 (-$1.85)
  - Net: -$0.24 — interesting mix

- **Today PnL**: -$0.92 / 3 closes / 0 wins (UNCHANGED — no new closes)
- **Open positions**: 0 (DB), but **$16.29 of positions reported by wallet snapshot** — something is on-chain outside our `copy_trades` DB
- **Bot errors last 10min**: 0
- **ML**: still 21:35:52 (approaching 6h retrain mark)

### 🚨 FLAG: DB_VS_WALLET_POSITION_DIVERGENCE (re-confirmed)

**`copy_trades WHERE status='open'` returns 0 rows.**  
But `PORTFOLIO: Positions=$16.29` — the on-chain wallet snapshot shows $16.29 in positions we can't see in the DB.

**Wallet +$1.63**: some external inflow. Candidates:
- `auto_redeem` cashed in an old resolved position (payoutDenominator > 0 on an old condition)
- A late settlement arrived for a position created in a prior round
- `smart_sell` path closed something that didn't update copy_trades correctly

**Positions -$1.85**: revaluation of the $16.29 set of on-chain holdings we can't see in DB.

This is the **DB_PNL_VS_WALLET_DISCREPANCY** I flagged in Round 4 (memory: "DB-PnL says $810, wallet says $100"). Confirms the DB is tracking a SUBSET of actual on-chain positions. Morning report should recommend a reconciliation job that walks `data-api.polymarket.com/positions?user=<funder>` and either imports missing rows or flags them for cleanup.

### Every new closed trade — **NONE** (in DB). Wallet moved $0.24 regardless.
### Every new open — **NONE**

### Every new blocked trade — **7714** (up from 6602 → +17%)

| Reason | Iter 9 | Iter 10 | Δ |
|---|---|---|---|
| **price_range** | 2289 | **3859** | +69% (now top) |
| exposure_limit | 3535 | 3178 | -10% |
| category_blacklist | 540 | 540 | 0% |
| min_trader_usd | 81 | 62 | -23% |
| conviction_ratio | 125 | 48 | -62% |
| no_rebuy | 32 | 27 | fade |

**`price_range` overtook `exposure_limit` as #1 reason** — sovereign2013 is making more buys outside the 42-70c window (low-prob lotto tickets at <40c or heavy favorites at >70c). Previously blocked by exposure, now by price. Probably different markets now (late-night markets have more extreme-prob spreads).

**By trader:**
- sovereign2013: 7529 (98%)
- Jargs: 180 (unchanged — Jargs idle again)
- 0x3e5b23e9f7: 5 (whale scan residual)

### Every new score — **NONE**
### Every new brain decision — **NONE** (brain last 00:10, next ~02:10 — ~33min away)

### Trader 7d deltas

| Trader | Iter 9 | Iter 10 | ΔPnL | Notes |
|---|---|---|---|---|
| sovereign2013 | 186, -$45.39 | **182, -$46.07** | -$0.68 | 4 more aged out, tiny net drift |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 | unchanged |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 | unchanged |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 | unchanged |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 | unchanged |
| aenews2 | 0 | 0 | 0 | unchanged |

sovereign2013 erosion **slowed from -$16 (last iter) to -$0.68** this iter. The aged-out burst seems over. He's stabilizing around -$45 until new closes hit. 7d WR stayed ~46%.

### Feedback coverage — still 730 / 59 / 8.1%

### Flags this iter

- [x] **DB_VS_WALLET_POSITION_DIVERGENCE** (re-confirmed): copy_trades has 0 open, wallet shows $16.29 in positions. Off-DB holdings drift by $1.85 this iter. Morning report: recommend reconciliation job.
- [x] **PRICE_RANGE_OVERTAKES_EXPOSURE**: first iter where `price_range` is the #1 block reason (50%). sovereign2013 making more extreme-price buys this window.
- [x] **SOVEREIGN_EROSION_SLOWING**: -$16 last iter → -$0.68 this iter. Window shift burst over, he's stabilizing around -$45.
- [x] **TRAILING_STOP_BAD_FILL** (carry, 2/2 samples confirmed iter 9) — unchanged.
- [x] **FEEDBACK_LOOP_COVERAGE_GAP** (carry) — unchanged.
- [x] **BRAIN_DATA_DIVERGENCE** (carry) — unchanged, brain didn't fire.
- [x] **BRAIN_CYCLIC_SPAM** (carry) — unchanged, brain didn't fire.
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT
- [ ] no NEW_ACTIVITY (quiet iter)

### One-line summary

Iter 10 (Δ17min, quiet): Portfolio $97.02 (Δ -$0.24, mixed — wallet **+$1.63** inflow from unknown source, positions -$1.85 reval). 0 new closes in DB / 0 new buys / 7714 new blocks (`price_range` now #1 reason). Bot flat in DB but $16.29 in off-DB positions per wallet snapshot — **DB_VS_WALLET_POSITION_DIVERGENCE re-confirmed**. sovereign2013 erosion slowing (-$0.68 vs -$16 last iter), stabilizing ~-$45. Nothing critical this cycle.

---

## Iteration 9 — 2026-04-13 01:20 (Δt ≈ 15 min) — SECOND BAD_FILL confirms pattern

### Snapshot
- **Portfolio**: $97.26 (Δ **+$0.62** since iter 8 — wallet rose from $78.38 → $79.11 on the sell)
- **Today PnL (2026-04-13)**: **-$0.92** on 3 closes, 0 wins (0% WR)
- **Open positions**: **0** (FLAT — #3035 just closed, no new buys)
- **Bot errors last 10min**: 1 (likely same auto_discovery 400)
- **Outcome tracker**: ran at 01:10:08, 100/100 checked, 0 errors. Healthy.
- **ML**: still 21:35:52 (4h old now, should retrain at ~03:35)

### 🎯 #3035 Spurs CLOSED via TRAILING-STOP — same BAD_FILL pattern

| id | market | entry | peak | quote@trigger | actual fill | shares | usdc_received | pnl |
|---|---|---|---|---|---|---|---|---|
| #3035 | Spread: Spurs (-9.5) | 0.5076 | **0.67 (+32%)** | 0.55 | **~0.338** ⚠️ | 2.167 | $0.7332 | **-$0.37** |
| #3036 | Jazz/Lakers O/U 235.5 | 0.5076 | 0.665 (+31%) | 0.54 | ~0.267 ⚠️ | 2.266 | $0.6048 | -$0.55 |

**Both closed, both identical pattern:**
- Entry at ~51c
- Peak at ~66-67c (+31-32% gain)
- Trailing stop trigger at 54-55c (peak - 12c margin)
- Fill at ~27-34c (**~20c below quote, exceeding max configured slippage of 20c**)
- Realized -$0.37 and -$0.55 = **total -$0.92 on $2.25 invested (-41%)**

**Both positions hit +$0.21/+$0.36 unrealized at peak**. Combined peak unrealized: **+$0.57**. Combined realized: **-$0.92**. That's **$1.49 destroyed between peak and exit fills** — 66% of capital burned by the exit-slippage pattern.

### 🚨 PATTERN CONFIRMED: TRAILING_STOP_BAD_FILL (2/2 samples)

Two consecutive real trades, both NBA/MLB O/U+Spread markets, both late-night US time, both showing:
- Correct trailing stop price trigger logic
- **Fill price ~20c below quoted mid when trailing executes**
- Loss direction and magnitude essentially symmetric (~$0.5 on $1 invested)

**Root cause hypothesis**: The 5-level slippage chain (`0.02, 0.05, 0.10, 0.15, 0.20`) walks the orderbook and in thin late-night NBA O/U markets the order reaches the 20c level and STILL doesn't fill → bot escalates beyond configured max OR fills at `take-best-available` price OR uses a different fallback path (resolving_price or emergency market order).

Whatever the mechanism, **the trailing stop is currently a PnL-destroyer, not a PnL-protector**, on these market types. It would be safer to either:
- Disable trailing stop for NBA/MLB O/U and Spread categories (like piff already disabled it for esports: cs/lol/valorant/dota)
- Tighten the slippage budget (e.g. max 10c instead of 20c) so the order fails faster and we hold through
- Move the trigger closer to peak (e.g. 4-6c margin instead of 12c) so exit is cleaner

**This is the #1 recommendation for the morning report.**

### Every new closed trade — 1 (detected via improved query)

Using the patched query `(id > LAST OR closed_at >= last_iter_ts)`:

| id | trader | category | size | fill received | pnl | kind |
|---|---|---|---|---|---|---|
| #3035 | sovereign2013 | nba | $1.10 | $0.7332 | **-$0.37** | REAL_SELL |

Query fix works. Old query missed transitions; new query catches them.

### Every new open — NONE (0 new buys, we're flat)

### Every new blocked trade — 6602 (+33% vs iter 8)

Late-night MLB + NBA still heavy.

| Reason | Count |
|---|---|
| exposure_limit | 3535 |
| price_range | 2289 |
| category_blacklist | 540 |
| conviction_ratio | 125 |
| min_trader_usd | 81 |
| no_rebuy | 32 (Jazz/Lakers + Spurs cooldowns now firing — expected after both closes) |

**`max_copies` dropped to 0** — makes sense, we have 0 open positions, nothing to max-out.

**By trader:**
- sovereign2013: 6391 (97%)
- Jargs: 180 (+13% vs iter 8)
- 0x3e5b23e9f7: 31 (whale residual)

### Every new score — **NONE** (0 new)
### Every new brain decision — **NONE** (brain last fire 00:10, next ~02:10)

### Trader 7d rolling — sovereign2013 CRASHING

| Trader | Iter 8 | Iter 9 | ΔPnL | Notes |
|---|---|---|---|---|
| **sovereign2013** | 190, -$29.40 | **186, -$45.39** | **-$15.99** | 4 aged-out winners (+$15.62) + #3035 close (-$0.37) |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 | unchanged |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 | unchanged (brain still sees +$31.52 — DIVERGENCE persists) |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 | unchanged |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 | unchanged closed count, lots of blocked buys |
| aenews2 | 0 | 0 | 0 | still idle |

**sovereign2013 has cratered from +$14 (iter 1) to -$45 over 9 iterations** — almost entirely via rolling-window-shift as his recent winners age out. The WR dropped from 49.5% → 46.2% too. He's no longer merely "worst profitable" — he's matching xsaghav's trajectory.

At current erosion rate (~$5/iter via window shift), sovereign2013 could hit -$70 by morning. Not from new losses, purely from time moving forward.

### Feedback coverage — **UNCHANGED** (730 / 59 / 8.1%)

#3035 close DID NOT populate any score row. Same reason as #3036 — it was bought via activity-scan path, not via scorer. Confirms the **FEEDBACK_LOOP_COVERAGE_GAP** flag from iter 8.

### Flags this iter

- [x] **TRAILING_STOP_BAD_FILL_CONFIRMED** (2/2 samples): #3035 and #3036 both filled 20-27c below trailing-stop quote. Consistent pattern. Morning report: top recommendation = disable or tighten trailing-stop for NBA/MLB cats (mirror piff's esports disable logic).
- [x] **$1.49_PEAK_TO_EXIT_DESTRUCTION**: Combined unrealized peak was +$0.57, combined realized -$0.92. Lost $1.49 via exit slippage alone on $2.25 capital. 66% value destroyed between peak and fill.
- [x] **BOT_NOW_FLAT**: 0 open positions. Drift stops until next buy.
- [x] **FEEDBACK_LOOP_COVERAGE_GAP_CONFIRMED**: neither #3035 nor #3036 was ever scored. Both bought via non-scorer path. Feedback loop covers < 10% of real closes by design.
- [x] **SOVEREIGN_EROSION_CONTINUES**: -$29 → -$45 (-$16). Mostly window-shift (4 aged-out winners worth $15.62). Pure time passage cost.
- [x] **NEW_CLOSED_QUERY_FIX_WORKS**: the `(id > X OR closed_at >= ts)` variant correctly caught #3035 transition where the old query missed it. Use this pattern going forward.
- [x] **BRAIN_CYCLIC_SPAM** (carry): no new brain fire this iter, nothing to add but keeping flag active.
- [x] **BRAIN_DATA_DIVERGENCE** (carry): KING still +$31 brain vs -$10 ralph — unchanged.
- [ ] no BOT_CRASHING (1 known auto_discovery 400 — non-critical)
- [ ] no SETTINGS_DRIFT (hash stable)
- [ ] no PHANTOM_DRIFT (wallet +$0.73 from real sell matches #3035 usdc_received)

### One-line summary

Iter 9 (Δ15min): **#3035 Spurs CLOSED via trailing-stop -$0.37 fill slippage identical to #3036**. Portfolio $97.26 (Δ +$0.62 wallet from sell), bot now **FLAT** (0 positions). Both real trades today closed at BAD_FILL pattern — entry 51c → peak 67c → trigger 55c → **fill 27-34c** → combined -$0.92 realized from +$0.57 peak = **$1.49 destroyed by exit slippage**. Morning report top-1 rec: disable/tighten trailing-stop for NBA/MLB/Spread. sovereign2013 -$29 → -$45 (window-shift erosion, 4 aged-out winners). Feedback loop confirmed missing both trades (non-scorer buy path).

---

## Iteration 8 — 2026-04-13 01:05 (Δt ≈ 50 min)

### Snapshot
- **Portfolio**: $96.64 (Δ **+$0.60** from iter 7 — wallet actually went UP from $77.78 → $78.38 via position exit)
- **Today PnL (2026-04-13)**: 2 closes / -$0.55 / 0 wins
- **Open positions**: **1** (down from 2) — #3036 closed
- **Bot errors last 10min**: 0
- **Outcome tracker**: FINALLY confirmed alive. Last fire 00:40:06, processed 100/100 blocked outcomes successfully. Next: 01:09:26. 4 OUTCOME log lines in last 30min.

### 🎯 MAJOR: #3036 Jazz/Lakers CLOSED via TRAILING STOP, **-$0.55 realized loss**

| id | market | entry | peak | exit price (quote) | actual fill | shares | usdc_received | pnl |
|---|---|---|---|---|---|---|---|---|
| #3036 | Jazz vs. Lakers: O/U 235.5 | 0.5076 | **0.66 (+31%)** | 0.54 | **~0.267** ⚠️ | 2.2655 | $0.6048 | **-$0.55** |

**Log trace:**
```
01:02:10 [TRAILING-STOP] #3036 closed — peak was 66c (+31%), now 54c: P&L=$-0.55
01:02:40 [SKIP] Recently closed (no-rebuy 120min): Jazz vs. Lakers: O/U 235.5
```

**What happened:**
- Peak was **66c (+31%)** — well above TRAILING_STOP_ACTIVATE=0.20
- Price fell to 54c — exactly at trigger point: peak(0.66) - margin(0.12) = 0.54
- Trailing stop fired correctly per design
- **BUT the fill executed at ~27c, not 54c** — 50% deep slippage below quote

**Math**: `usdc_received=$0.6048` / `shares_held=2.2655` = $0.267/share. Quote at trigger was 0.54 = ~50% slippage below.

**SELL_SLIPPAGE_LEVELS=0.02,0.05,0.10,0.15,0.20** — max allowed is 20c below quote = 34c. We filled at 27c, 7c below the worst configured slippage level. That means either:
- The order escalated through all 5 slippage levels and the last level still didn't match
- The orderbook was so thin the order walked down the book to 27c
- A different sell path (not slippage retry) executed the fill

**Combined trade arc**: Entry 51c → peak 66c (+$0.21 unrealized at peak) → trigger 54c → fill 27c → **realized -$0.55** (was up $0.21 at peak, lost $0.76 between peak and fill = -72% on $1.15 size).

This is a **TRAILING_STOP_BAD_FILL** finding for the morning report. Trailing stop logic is correct, but fill price divergence is destroying the realized gain. Root cause: thin orderbook on NBA O/U markets during the game + slippage cascade not catching up to real bids.

### 🚨 FLAG: FEEDBACK_LOOP_MISSED_THIS_CLOSE

I queried `trade_scores WHERE condition_id = (Jazz/Lakers cid)` — **0 rows**. The Jazz/Lakers trade was never scored.

This contradicts my iter 5 assumption that the 16 QUEUE scores produced copy_trades #3035 and #3036. In reality:
- The 281 new scores in iter 5 were for **other sovereign2013 markets** that got queued but didn't execute
- #3035 and #3036 came through a **different buy path** (likely the activity-scan in copy_trader.py) that DOES NOT call `trade_scorer.score()` before buying
- So neither position ever had a `trade_scores` row created
- Thus my Round 4 `update_trade_score_outcome` call at the close had nothing to update — rowcount=0, silent success

**Architectural finding for morning report**: The feedback loop only covers buys that go through the scorer's path. Buys from the activity-scan path bypass scoring entirely. Brain's `_optimize_score_weights` can only learn from scored+closed trades, which is a small subset. The coverage number (59 / 730 = 8.1%) is actually MORE misleading than I thought — many closes won't increment it because they weren't scored in the first place.

Fix path: move `trade_scorer.score()` call BEFORE the buy attempt in EVERY buy path (activity scan, position diff, event wait, hedge wait, pending buy). Or: create a score row opportunistically after buy if none exists.

### Every new closed trade (detection gap!)

My NEW_CLOSED query uses `WHERE id > LAST_TRADE` which doesn't catch **existing rows that transitioned from open to closed**. Iter 7 saw #3036 as open. Iter 8 sees it as closed. My query returned `N_CLOSED=0` but the `TODAY` counter shows 2 closes, up from 1. That discrepancy = 1 missed close (#3036 itself).

Flag for the prompt: the query should ALSO include `WHERE closed_at >= last_iteration_ts AND status='closed'` to catch transitions. Worth patching `ralph-prompt.md` on next revision.

### Every new open — **NONE** (0 new buys)

### Every new blocked trade — **4946** (up from 1725 → +187%)

Late-night NBA in full swing. Block rate back up to ~500/min.

| Reason | Iter 7 | Iter 8 | Δ |
|---|---|---|---|
| exposure_limit | 905 | **3462** | +282% |
| price_range | 24 | 804 | massive |
| category_blacklist | 0 | 385 | NEW surge |
| conviction_ratio | 234 | 184 | -21% |
| min_trader_usd | 532 | 107 | -80% |
| no_rebuy | 29 | 3 | -90% |
| max_copies | 1 | 1 | stable |

**By trader:**
- sovereign2013: 4786 (97%)
- **Jargs: 159** (up from 96 in iter 6 — Jargs more active, all still blocked by TERRIBLE tier)
- 0x3e5b23e9f7: 1 (residual whale scan)

### Every new score — **NONE** (0 new scored)
### Every new brain decision — **NONE** (brain didn't fire this window; last fire 00:10, next ~02:10)

### Trader 7d deltas

| Trader | Iter 7 | Iter 8 | ΔPnL | Explanation |
|---|---|---|---|---|
| **sovereign2013** | 190, -$25.19 | 190, **-$29.40** | **-$4.21** | 1 aged out (+$3.66), 1 added (#3036 -$0.55), net -$4.21 |
| xsaghav | 187, -$122.71 | 187, -$122.71 | 0 | unchanged |
| KING7777777 | 133, -$9.75 | 133, -$9.75 | 0 | unchanged |
| fsavhlc | 20, -$21.05 | 20, -$21.05 | 0 | unchanged |
| Jargs | 17, -$10.67 | 17, -$10.67 | 0 | unchanged (new blocks don't count, no closes) |
| aenews2 | 0 | 0 | 0 | unchanged |

sovereign2013 keeps sinking. Current -$29.40 = where xsaghav WAS early this session.

### #3035 Spurs position still open and rising

| id | market | entry | current | unreal | Δ from iter 7 |
|---|---|---|---|---|---|
| #3035 | Spread: Spurs (-9.5) | 0.5076 | **0.585** | **+$0.17** | **+$0.11** 📈 |

Price up 5c (0.535 → 0.585). If it keeps rising past 60c we'll hit the 20% activate threshold and trailing stop can trigger on it too. Given what happened to #3036, the trailing stop activating is actually a **bad thing** right now until we fix the fill-slippage issue.

### Feedback coverage — UNCHANGED (730 / 59 / 8.1%)

As explained above, the #3036 close SHOULD have nothing to update because it was never scored. The feedback stayed at 59 correctly by data semantics but incorrectly by design intent.

### Flags this iter

- [x] **TRAILING_STOP_BAD_FILL** (NEW critical): #3036 trailing stop triggered correctly at 54c (peak 66c - 12c margin), but filled at ~27c, realizing -$0.55 on what was a +$0.21 position. Max configured slippage 20c — actual slippage ~27c. Root: thin late-night NBA O/U orderbook.
- [x] **FEEDBACK_LOOP_MISSED_THIS_CLOSE** (NEW critical architectural): #3036 Jazz/Lakers had ZERO trade_scores rows. It was bought via the activity-scan path which bypasses `trade_scorer.score()`. Round 4 feedback loop only covers the score→buy→close path. Morning report must include this.
- [x] **QUERY_DETECTION_GAP**: My ralph-prompt `NEW_CLOSED` query misses status transitions on existing rows. Should use `closed_at >= last_iteration_ts AND status='closed'` alongside `id > LAST_TRADE`. Patched in state notes for next session.
- [x] **#3035_STILL_RISING**: Spurs position +$0.17, was +$0.06. Moving nicely, will hit trailing-stop activation soon.
- [x] **BRAIN_CYCLIC_SPAM** (carry): no new brain fire, so no new duplicate rows this iter.
- [x] **BRAIN_DATA_DIVERGENCE** (carry): same.
- [x] **OUTCOME_TRACKER_CONFIRMED_ALIVE**: fired at 00:40, processed 100/100 blocked trades, 0 errors. My prior 3-iter idle flag was wrong about the root cause — it's just the 30min cadence. Flag retired.
- [x] **SOVEREIGN_PNL_STILL_ERODING**: -$25 → -$29. Net activity loss (1 real trade -$0.55) + window shift (-$3.66). Continuing downward trajectory.
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT (hash stable)

### One-line summary

Iter 8 (Δ50min): **#3036 closed via trailing-stop at -$0.55** — was +$0.21 at peak, fill price 27c vs quote 54c = 50% slippage (BAD_FILL). #3035 still open +$0.17. Portfolio $96.64 (Δ +$0.60 wallet from the sell). **Critical architectural finding: #3036 was NEVER SCORED — it came through a non-scorer buy path, so the feedback loop has structural coverage gaps**. outcome_tracker confirmed alive (runs every 30min). Morning report: add TRAILING_STOP_BAD_FILL + FEEDBACK_LOOP_COVERAGE_GAP to top recommendations.

---

## Iteration 7 — 2026-04-13 00:12 (Δt ≈ 5 min)

### Snapshot
- **Portfolio**: $96.04 (Δ -$0.08 since iter 6)
  - Wallet: $78.02 → $77.78 (-$0.24)
  - Positions: $18.10 → $18.27 (+$0.17)
- **Today (2026-04-13) PnL**: $0.00 (1 close, exactly 0 — see phantom close below)
- **Open positions**: 2 ($2.25 invested, unrealized **+$0.27** combined — growing!)
- **Bot errors last 10min**: 0
- **ML**: still 21:35:52 (unchanged, next retrain ~03:35)

### Tracked open positions — both still green, #3036 moving in favor

| id | market | entry | current | unreal PnL | Δ from iter 6 |
|---|---|---|---|---|---|
| #3035 | Spread: Spurs (-9.5) | 0.5076 | 0.535 | +$0.06 | -$0.01 (tiny retrace) |
| #3036 | Jazz vs. Lakers: O/U 235.5 | 0.5076 | **0.60** | **+$0.21** | **+$0.09** 📈 |

Jazz/Lakers moved from 0.56 → 0.60 in 5 min, +4c on a coinflip-range position. Our first real edge appearing.

### Every new closed trade — 1 phantom close

| id | trader | market | size | pnl | kind |
|---|---|---|---|---|---|
| #3124 | `0x3e5b23e9f7` | Will Keiko Fujimori win 2026 Peruvian presidential election? | $1.00 | **$0.00** | NO_USDC |

Weird entry:
- Trader is **a raw wallet address** (no username), one of the DISCOVERED whales from iter 1 lifecycle
- `usdc_received=None` but `pnl_realized=0.00` (not `-size`) — unusual combo
- Category: geopolitics
- Closed at 00:11:20

This looks like the **auto_discovery / whale scan** path creating and auto-closing a paper-trade entry for tracking purposes. Not from our main copy path. Shouldn't count against real P&L but it does inflate the "today N closed" counter.

**Also unusual**: `0x3e5b23e9f7` appears in blocked_trades 30 times this iter, and in trader_rolling_7d with n=1. Our auto_discovery is actively scanning/tracking whales — expected per PATCH-012, but creating noise in our DB.

### Every new open — NONE (0 new buys)

### 🔁 BRAIN RAN AGAIN — same 4 decisions as iter 6

**#457 TIGHTEN_FILTER KING7777777** — "Brain: 12 BAD_PRICE losses for KING7777777"  
**#458 PAUSE_TRADER xsaghav** — "7d PnL $-135.55 < -$20" (log-only)  
**#459 PAUSE_TRADER fsavhlc** — "7d PnL $-21.05 < -$20" (log-only)  
**#460 RELAX_FILTER KING7777777** — "7d pnl=$31.52 wr=53% tier=solid"

**IDENTICAL to iter 6's #453-#456.** Brain is re-running its decision cycle and producing the same 4 rows every time. Nothing in the system detects "I already made this exact decision 30 minutes ago, skip."

### 🚨 NEW FLAG: BRAIN_CYCLIC_SPAM

Round 4 Task 4 added dedup WITHIN a single `_classify_losses` call — same `(trader, category)` pair only writes one `BLACKLIST_CATEGORY` per brain cycle. But **nothing dedupes across cycles**. If the same condition (e.g. xsaghav 7d PnL < -$20) persists, each brain cycle writes a fresh PAUSE_TRADER row even though it's functionally a no-op (log-only per piff).

Over a full 24-hour day of brain running every 2h, that's **12 cycles × 4 identical rows = 48 redundant brain_decisions rows/day** at current rate. Not catastrophic but noise for morning-report analysis. Fix would be a `WHERE NOT EXISTS (SELECT 1 FROM brain_decisions WHERE action=X AND target=Y AND created_at > now-3h)` guard in `log_brain_decision`.

Also — the BRAIN_DATA_DIVERGENCE flag from iter 6 is **persisting**: brain still reports KING +$31.52/53% tier=SOLID, ralph still queries -$9.75/41%. Brain ran again with the same inflated view. Whatever `db.get_trader_rolling_pnl` is reading hasn't updated to reflect reality.

### Every new blocked trade — 1725 (down from 9370 → **-82%**)

Block rate crashed from ~700/min to ~170/min. Evening sports events are resolving and fewer live markets available.

| Reason | Iter 6 | Iter 7 | Δ |
|---|---|---|---|
| exposure_limit | 4806 | **905** | -81% (collapsed) |
| min_trader_usd | 207 | **532** | +157% |
| price_range | 3652 | 24 | -99% (near gone) |
| conviction_ratio | 235 | 234 | ~0% |
| category_blacklist | 469 | 0 | -100% |
| **no_rebuy** | 0 | 29 | NEW |
| max_copies | 1 | 1 | 0 |

`no_rebuy` firing (29 blocks) = our NO_REBUY_MINUTES=120 cooldown kicking in for recently-closed markets (including the phantom #3124 whale close triggering rebuy guards on geopolitics markets).

**By trader:**
- sovereign2013: 1695 (98%)
- **0x3e5b23e9f7**: 30 (NEW — whale auto_discovery scan path)

### Trader 7d rolling deltas

| Trader | Iter 6 n | Iter 7 n | Δn | Iter 6 PnL | Iter 7 PnL | ΔPnL |
|---|---|---|---|---|---|---|
| **sovereign2013** | 194 | 190 | **-4** | -$11.12 | **-$25.19** | **-$14.07** 📉 |
| **xsaghav** | 188 | 187 | -1 | -$135.55 | **-$122.71** | **+$12.84** 📈 (aged-out loser) |
| others | unchanged | | | | | |
| **new: 0x3e5b23e9f7** | - | 1 | +1 | - | $0.00 | - |
| **new: 0x6bab41a0dc** | - | 0 | 0 | - | - | - |

**sovereign2013 continues to erode via window shift**: -$11 → -$25. 4 trades aged out and they were net +$14 (all winners). His remaining 7d is increasingly losers-only.

**xsaghav recovered $12** from window-shift. His oldest trade was a big loser that fell out.

Both deltas are from the rolling window, NOT new activity (no new closes for either).

### Feedback coverage — UNCHANGED (730/59/8.1%)

### Settings hash CHANGED: `e648dec...` → `b4de11f...`

Brain's TIGHTEN+RELAX on KING touched settings.env. The TIGHTEN wrote 40-75c, the RELAX wrote 35-80c back. Net should be a no-op on content, but maybe whitespace or iteration order caused a different hash. Worth inspecting if the hash keeps drifting on identical brain cycles.

### Flags this iter

- [x] **BRAIN_CYCLIC_SPAM** (NEW): same 4 brain_decisions rows written again verbatim. Nothing dedupes across cycles.
- [x] **BRAIN_DATA_DIVERGENCE** (persist): KING +$31.52 brain view vs -$9.75 ralph view, second cycle in a row.
- [x] **#3036_WINNING**: Jazz/Lakers position +$0.21 unrealized, first real edge appearing in a held copy.
- [x] **SOVEREIGN_PNL_EROSION_CONTINUING**: -$11 → -$25 via window shift. His recent wins keep aging out faster than new wins arrive.
- [x] **XSAGHAV_WINDOW_RECOVERY**: -$135 → -$122 (+$12 window shift). Marginal.
- [x] **PHANTOM_WHALE_CLOSE**: #3124 auto_discovery paper trade creating noise ($0 pnl, NO_USDC, geopolitics). Not real activity.
- [x] **BLOCK_RATE_DROPPED**: 9370 → 1725 as evening sports end. Breathing room returning.
- [x] **SETTINGS_HASH_DRIFT**: changed despite no semantic change. Brain TIGHTEN+RELAX causing cosmetic rewrites.
- [x] **OUTCOME_TRACKER_4_ITER_IDLE**: still silent. Definitely worth grepping journalctl for `[OUTCOME]` on the next scheduled 30min mark.
- [ ] no BOT_CRASHING (0 errors)
- [ ] no PHANTOM_DRIFT in wallet ($2.25 invested vs $2.25 cost basis → consistent)

### One-line summary

Iter 7 (Δ5min): Portfolio $96.04 (Δ -$0.08), **Jazz/Lakers position +$0.21 unreal (was +$0.12) — first real edge**. 1725 new blocks (down 82%), 0 new copies. **Brain ran again, SAME 4 decisions as iter 6 verbatim → BRAIN_CYCLIC_SPAM flag**. BRAIN_DATA_DIVERGENCE still showing KING +$31 brain vs -$10 ralph. sovereign2013 -$11 → -$25 window-shift erosion. Morning report: KING data divergence + brain dedup gap.

---

## Iteration 6 — 2026-04-13 00:07 (Δt ≈ ~25 min) — BRAIN FIRED + DATE ROLLOVER

### Snapshot
- **Portfolio**: $96.12 (Δ **-$0.15** since iter 5 — Wallet unchanged $78.02, Positions $18.25 → $18.10 small reval drop)
- **DATE ROLLOVER on server**: now 2026-04-13. Yesterday (2026-04-12) closed at: 26 trades / -$39.56 / 5 wins / 19% WR
- **Today PnL (fresh day)**: 0 (no closes yet)
- **Open positions**: **2** ($2.25 invested, unrealized +$0.19 combined — both slightly green)
- **Bot errors last 10min**: 1 (auto_discovery leaderboard 400 — known, non-critical)

### The 2 real buys from iter 5 — still open, both slightly profitable

| id | market | entry | current | unreal pnl |
|---|---|---|---|---|
| #3035 | Spread: Spurs (-9.5) | ~0.53 | 0.54 | +$0.07 |
| #3036 | Jazz vs. Lakers: O/U 235.5 | ~0.55 | 0.56 | +$0.12 |

### 🧠 BRAIN FIRED at 23:40:20 — 4 decisions logged

First brain cycle during the loop run. All 4 decisions verbatim from `brain_decisions`:

**#453 TIGHTEN_FILTER KING7777777** (23:40:20)  
Reason: "Brain: 12 BAD_PRICE losses for KING7777777"  
Data: `{"old_min": 0.35, "old_max": 0.8, "new_min": 0.4, "new_max": 0.75}`  
Impact: "Reduce exposure to extreme price entries"  
→ `_tighten_price_range` shrunk KING's range 35-80c → 40-75c

**#454 PAUSE_TRADER xsaghav** (23:40:21)  
Reason: "7d PnL $-135.55 < -$20" (threshold is -$20 per piff's PATCH-008)  
Data: `{"pnl_7d": -135.55, "streak": 2}`  
**Impact: "Logged only — auto-pause disabled"** ✅ piff's PATCH-023 log-only design is working correctly

**#455 PAUSE_TRADER fsavhlc** (23:40:21)  
Reason: "7d PnL $-21.05 < -$20"  
Data: `{"pnl_7d": -21.05, "streak": 0}`  
Impact: "Logged only — auto-pause disabled"

**#456 RELAX_FILTER KING7777777** (23:40:22)  
Reason: "7d pnl=$31.52 wr=53% tier=solid"  
Impact: "Loosen price range toward tier default"  
→ immediately undoes #453's tighten. Auto-revert from Round 4 Task 11 working as designed.

### 🚨 FLAG: BRAIN_DATA_DIVERGENCE

**Brain sees KING7777777 7d pnl = +$31.52 / 53% WR (→ SOLID tier, relax filter).**  
**Our ralph-loop query shows KING7777777 7d pnl = -$9.75 / 41.4% WR (→ WEAK tier, tighten more).**

$41+ divergence. Both use "7d" window, but different queries:
- Our: `SELECT SUM(pnl_realized) FROM copy_trades WHERE wallet_username='KING7777777' AND status='closed' AND pnl_realized IS NOT NULL AND closed_at >= datetime('now','-7 days')`
- Brain's `db.get_trader_rolling_pnl(name, 7)`: returns `{pnl_7d: 31.52, wr_7d: 53}` — probably uses a different table (paper_trades? trader_performance? different window math?)

This divergence matters: brain's revert logic (RELAX_FILTER) is based on its inflated view. Morning report: investigate `db.get_trader_rolling_pnl` implementation and verify source of truth.

### 62 new copy_trades rows — ALL BASELINE

| id range | trader | status | created_at |
|---|---|---|---|
| 3037–3098 | sovereign2013 | baseline | 2026-04-13 00:04:20-23 |

All 62 rows are `status=baseline` with NULL size/entry — these are position snapshots from the **midnight UTC full-rescan** triggered by the server date rollover. Not real trades, just bookkeeping so "closed today" counters start fresh. This is expected behavior but produces a spike in `copy_trades` row count.

### Every new score — **NONE** (N_SCORES=0)

The scorer went quiet again. The 281 scores from iter 5 were a burst when the pending-buy queue processed sovereign2013's accumulated signals. Now that queue is empty. Scorer won't fire until filters pass again.

### Every new blocked trade — 9370 TOTAL (down from 11372 → -18%)

| Reason | Count | Δ vs iter 5 |
|---|---|---|
| exposure_limit | 4806 | +29 (~flat) |
| price_range | 3652 | +272 |
| category_blacklist | 469 | -27 |
| conviction_ratio | 235 | -29 |
| min_trader_usd | 207 | -116 |
| **max_copies** | 1 | **NEW** |

**`max_copies: 1`** — first time we've seen this reason. It's our own MAX_COPIES_PER_MARKET_MAP=1 limit firing: sovereign2013 tried to re-enter a market where we already have 1 copy (our open #3035 or #3036). Bot correctly refused second copy. Good safety behavior.

**By trader:**
- sovereign2013: **9274** (99.0%)
- **Jargs: 96** (NEW — first time Jargs shows up in blocks)

**Jargs became active** this window (prior iters had 0 Jargs blocks). All 96 blocks are due to the tighter TERRIBLE-tier filters auto_tuner applied last iter (min_conviction 3.0, bet 0.01, max_entry 0.65). Jargs's new buys don't meet the tighter thresholds.

### Trader 7d deltas

| Trader | Iter 5 | Iter 6 | ΔPnL |
|---|---|---|---|
| sovereign2013 | -$12.12 | -$11.12 | +$1.00 (aged out loser) |
| xsaghav | -$135.55 | -$135.55 | 0 |
| KING7777777 | -$9.75 | -$9.75 | 0 (per ralph query — brain sees +$31.52!) |
| fsavhlc | -$21.05 | -$21.05 | 0 |
| Jargs | -$10.67 | -$10.67 | 0 |
| aenews2 | 0 | 0 | 0 |

All 5 followed still net-negative on ralph's view.

### Feedback coverage — still 730 / 59 (8.1%)

Unchanged. No new scored trades. No backfill hit the DB in this window.

### `OUTCOME_TRACKER` status — STILL IDLE (3rd iter in a row)

`BLOCKED_CHECKED_15M=0`. The 30-min scheduler should have fired at least once by now. Either the job is silently erroring OR it's finding `unchecked` list empty and returning early. Worth a journalctl grep for `[OUTCOME]` lines next iter.

### Settings — UNCHANGED (hash same as iter 5)

auto_tuner ran in iter 5, not this iter. Brain made decisions this iter but they were small deltas (price range on KING, which got reverted) so `settings.env` was touched but likely ended up with the same content or near-same.

### Error details

```
2026-04-13 00:07:26 [ERROR] bot.auto_discovery: Leaderboard fetch failed:
  400 Client Error: Bad Request for
  url: https://data-api.polymarket.com/v1/leaderboard?limit=50&offset=0&timePeriod=30d&orderBy=PNL
```

Known issue: Polymarket data-api's leaderboard endpoint returns 400 on some parameter combos. `auto_discovery.py` is the only consumer and it falls back to `polyscan` source. Not affecting trading. Morning report can mention this as a low-priority cleanup.

### Flags this iter

- [x] **BRAIN_FIRED**: first cycle during the loop, 4 decisions (TIGHTEN + 2 PAUSE + RELAX). Pauses correctly log-only per piff. TIGHTEN+RELAX same trader same cycle = auto-revert working.
- [x] **BRAIN_DATA_DIVERGENCE** (NEW, critical): Brain's internal `db.get_trader_rolling_pnl` returns KING +$31.52/53% while direct SQL shows -$9.75/41%. Different data source. Investigate.
- [x] **DATE_ROLLOVER**: server crossed midnight UTC. Today starts fresh 0/0. Yesterday closed -$39.56 / 26 trades / 19% WR.
- [x] **62_BASELINE_SPIKE**: midnight full-rescan of sovereign2013's positions. Expected bookkeeping, not real activity.
- [x] **OPEN_POSITIONS_SLIGHTLY_PROFITABLE**: #3035 +$0.07, #3036 +$0.12 unrealized. First green positions of the session.
- [x] **MAX_COPIES_FIRED**: first `max_copies` block ever seen — bot refused second copy of same market where we already hold one. Correct.
- [x] **JARGS_ACTIVE_BUT_BLOCKED**: 96 blocks for Jargs (first time in blocks), all due to auto_tuner's TERRIBLE tier tightening from iter 5.
- [x] **AUTO_DISCOVERY_400**: known, non-critical. Affects whale-candidate scans only.
- [x] **OUTCOME_TRACKER_3_ITER_IDLE**: no blocked-trade outcome updates for 3 consecutive iterations. Warrants investigation next iter.
- [ ] no BOT_CRASHING (1 non-critical error)
- [ ] no PHANTOM_DRIFT

### One-line summary

Iter 6 (Δ~25min, date rolled over): Portfolio $96.12, today fresh 0 (yesterday closed -$39.56 / 26t / 19% WR). **Brain ran**, 4 decisions — **log-only pauses for xsaghav/fsavhlc** (piff disable working), tighten+auto-revert on KING. **BRAIN_DATA_DIVERGENCE flagged**: brain sees KING +$31 but ralph sees -$10. Open positions #3035 +$0.07 / #3036 +$0.12 slightly green. Morning report must flag BRAIN_DATA_DIVERGENCE.

---

## Iteration 5 — 2026-04-12 22:30ish (Δt ≈ 13 min) — MAJOR ACTIVITY

### Snapshot
- **Portfolio**: $96.27 (Δ **-$1.06** since iter 4 $97.33)
  - Wallet: $80.27 → **$78.02** (-$2.25) — bot actually SPENT cash
  - Positions: $17.06 → $18.25 (+$1.19)
  - Net: -$1.06 (paid $2.25 for new positions now worth $1.19 = fresh position at slight drawdown)
- **Today PnL**: -$39.56 (unchanged — the 2 new buys are open, not closed yet)
- **Bot errors last 10min**: 0
- **ML**: not retrained (still 21:35:52, 7306 samples)

### 🎯 TWO NEW BUYS EXECUTED — first activity after 4 idle iterations

| id | trader | market | created_at | status |
|---|---|---|---|---|
| 3035 | sovereign2013 | Spread: Spurs (-9.5) | 23:12:02 | open |
| 3036 | sovereign2013 | Jazz vs. Lakers: O/U 235.5 | 23:25:52 | open |

Both NBA, both sovereign2013, both `status=open` (unresolved). The bot broke its 0-closes streak by OPENING positions. These will show up as closed trades in future iterations when the games resolve.

**Important**: These two made it through because the scorer assigned **action=QUEUE** (score 45), which means "add to pending-buy queue and execute when price drifts favorably or time expires". Neither was an EXECUTE (60-79) or BOOST (80+) score — the scorer correctly down-rated them. The queue path let them through anyway because the price drift threshold (3-5%) hit.

### 🧠 SCORER WOKE UP: 281 new scores (449 → 730 total)

This is the **first scorer activity since iter 1**. Previous iters had 0 new scores because the filter chain blocked everything upstream. Something changed this iter to let 281 attempts reach the scorer.

**Action breakdown:**

| Action | Count | Score min | Score max | Score avg |
|---|---|---|---|---|
| **BLOCK** | 265 | 20 | 36 | 29.7 |
| **QUEUE** | 16 | 45 | 47 | 45.3 |
| EXECUTE (60-79) | **0** | — | — | — |
| BOOST (80+) | **0** | — | — | — |

**Zero EXECUTE or BOOST scores.** All 281 scores are at or below 47. Scorer is correctly penalizing sovereign2013 now that his `trader_edge` component reflects his -$15.08 7d PnL.

### ⚙️ SETTINGS CHANGED — auto_tuner ran

Hash: `8a1f2bb...` → `e648dec...`. The 2h `auto_tune_settings` scheduler job fired in this window. No `brain_decisions` so brain didn't act, but auto_tuner reclassified traders based on updated 7d stats:

**Key changes (diff vs iter 1 baseline):**

| Map | Before | After | Trader impact |
|---|---|---|---|
| `BET_SIZE_MAP` Jargs | 0.02 | **0.01** | dropped 1 tier (→ TERRIBLE) |
| `BET_SIZE_MAP` KING7777777 | 0.07 | **0.05** | dropped to SOLID |
| `TRADER_EXPOSURE_MAP` Jargs | 0.03 | **0.005** | massive cut (TERRIBLE) |
| `TRADER_EXPOSURE_MAP` KING7777777 | 0.4 | **0.25** | SOLID tier |
| `MIN_TRADER_USD_MAP` Jargs | 8.0 | **10.0** | TERRIBLE |
| `MIN_ENTRY_PRICE_MAP` Jargs | 0.42 | **0.45** | TERRIBLE |
| `MAX_ENTRY_PRICE_MAP` Jargs | 0.70 | **0.65** | TERRIBLE |
| `MIN_CONVICTION_RATIO_MAP` Jargs | not set | **3.0** | TERRIBLE (only copy 3x+ conviction) |
| `MIN_CONVICTION_RATIO_MAP` sovereign2013 | 0.5 | 0.5 | unchanged (he's now TERRIBLE but the map was 0.5 before so it stays) |
| `TAKE_PROFIT_MAP` KING7777777 | 3.0 | **2.5** | SOLID |
| `TAKE_PROFIT_MAP` Jargs | 1.5 | **1.0** | TERRIBLE |

**Semantic**: Jargs got reclassified from WEAK to TERRIBLE (his 7d PnL -$10.67 crosses the -$10 threshold). KING7777777 dropped from STAR to SOLID (7d PnL -$9.75). sovereign2013 is now TERRIBLE in data but his settings reflect the prior classification (auto_tuner merges with existing values per PATCH-024).

### Every new closed trade — **NONE** (still 0 in last 13 min)

The 2 new buys are `status=open`. Nothing closed.

### Every new blocked trade — **11372 TOTAL** (up from 7025 → +62%)

Rate now ~875/min. Still accelerating, though slower rate than the doubling of iter 3→4.

| Reason | Iter 4 | Iter 5 | Δ |
|---|---|---|---|
| exposure_limit | 4777 | **6634** | +39% |
| price_range | 1309 | **3380** | +158% (huge surge) |
| category_blacklist | 541 | 496 | -8% |
| **score_block** | 0 | **265** | NEW this iter — scorer now producing BLOCKs |
| conviction_ratio | 212 | 264 | +25% |
| min_trader_usd | 186 | 323 | +74% |
| event_timing | 0 | 10 | NEW |

**New block reason `score_block` (265)** — these match the 265 BLOCK scores above. Scorer rejected, block_trades logged with this reason. Good traceability.

### Every new brain decision — **NONE** (brain still awaiting next 2h cycle)

### Trader 7d deltas

| Trader | Iter 4 n | Iter 5 n | Δn | Iter 4 PnL | Iter 5 PnL | ΔPnL |
|---|---|---|---|---|---|---|
| sovereign2013 | 196 | 195 | -1 | -$15.08 | **-$12.12** | +$2.96 (1 aged-out loser) |
| xsaghav | 189 | 188 | -1 | -$129.99 | **-$135.55** | -$5.56 (1 aged-out winner) |
| Others | unchanged | | | | | |

sovereign2013 marginally recovered from rolling-window; xsaghav marginally worsened. Both tiny deltas from window math, not real activity. All 5 followed traders remain net-negative 7d.

### Feedback coverage — **DROPPING in %**

- Total scores: 449 → **730** (+281)
- With outcome_pnl: 59 → **59** (unchanged)
- **Coverage: 13.1% → 8.1%** 📉

The feedback loop is DILUTING. 281 new BLOCK scores will NEVER get outcome_pnl because:
1. BLOCK scores don't create copy_trades (they reject the buy)
2. My Round 4 `update_trade_score_outcome` call is only in close paths (smart_sell / resolved / stop-loss / trailing) — runs when a `copy_trade` closes
3. The backfill helper joins `trade_scores` to `copy_trades` — no copy_trade = no match
4. Only the 2 new QUEUE scores that became copy_trades #3035/#3036 will eventually get outcome_pnl when those positions close

This is an **architectural gap in the feedback loop design**: brain's `_optimize_score_weights` can tune the BLOCK threshold based on "did blocked trades win?" — but it has no way to answer that question because BLOCK scores never get outcomes. The closest signal is `blocked_trades.would_have_won` (set by outcome_tracker on blocked_trades table, NOT trade_scores table) but the two tables aren't linked.

**Fix would need**: `trade_scores.outcome_pnl` should ALSO be populated from `blocked_trades.would_have_won` when the score-produced-block matches a blocked_trades row. Cross-table join on `(condition_id, trader, timestamp_window)`. Morning report: add this to recommendations.

### Score range perf — UNCHANGED (SCORER_INVERTED persists)

The same 59 outcome-bearing scores from iter 1 still show the inverted pattern. No new data to refresh it because all 281 new scores have NULL outcome.

### Flags this iter

- [x] **NEW_BUYS_EXECUTED**: First real copies after 4 idle iters. Both sovereign2013 NBA spreads/totals via QUEUE path.
- [x] **SCORER_NOW_ACTIVE**: 281 new scores this iter (vs 0 prior). All BLOCK or QUEUE, max score 47. Scorer correctly down-rating sovereign now that his pnl crossed negative.
- [x] **AUTO_TUNER_RAN**: Settings hash changed, Jargs reclassified WEAK → TERRIBLE, KING STAR → SOLID. Tier shifts reflected in all relevant maps.
- [x] **FEEDBACK_COVERAGE_DROPPING**: 13.1% → 8.1%. 281 new BLOCK scores diluting the coverage because they'll never resolve. Needs architectural fix (cross-table join trade_scores ↔ blocked_trades).
- [x] **BLOCK_SPAM**: 11372 this iter (still all sovereign2013). New category `score_block` (265) + `event_timing` (10). Rate ~875/min.
- [x] **PORTFOLIO_REAL_SPEND**: -$2.25 wallet (2 real buys), positions only +$1.19. Fresh positions opened at slight drawdown.
- [x] **OUTCOME_TRACKER_STILL_IDLE**: `BLOCKED_CHECKED_15M=0` for 2 iters now. outcome_tracker.track_outcomes either hasn't fired or is silently no-op'ing.
- [ ] no BRAIN_SPAM (0 decisions)
- [ ] no BOT_CRASHING (0 errors)
- [ ] no PHANTOM_DRIFT (wallet Δ matches cost of new buys)

### One-line summary

Iter 5 (Δ13min): **Bot executed 2 new buys** (sovereign2013 NBA, both QUEUE-path) — first activity after 4 idle iters. Portfolio $96.27 (Δ -$1.06, wallet -$2.25 from buys). **Scorer woke up: 281 new scores all ≤47, 265 BLOCK + 16 QUEUE, none EXECUTE**. Auto-tuner ran → Jargs dropped to TERRIBLE tier. **Feedback coverage 13.1% → 8.1% (droppng)** — architectural gap: BLOCK scores never get outcome_pnl. Morning report must flag this.

---

## Iteration 4 — 2026-04-12 22:17 (Δt ≈ 10 min)

### Snapshot
- **Portfolio**: $97.33 (Δ **+$1.21** since iter 3 — Wallet unchanged, Positions revalued $15.85 → $17.06, recovery on open positions)
- **Today PnL**: -$39.56 (unchanged, 0 new closes)
- **Bot errors last 10min**: 0
- **Settings unchanged** (hash identical)
- **ML**: not retrained (last 21:35:52)
- **Outcome tracker**: `blocked_checked_15m = 0` — the 30-min scheduled outcome sweep hasn't touched any blocked_trades in ≥15min. Either already caught up or scheduler isn't firing it. Watch next iter.

### 🚨 MAJOR: SOVEREIGN2013 CROSSED INTO NEGATIVE 7d PNL

| Trader | Iter 3 PnL | Iter 4 PnL | Δ | Status |
|---|---|---|---|---|
| sovereign2013 | +$3.62 | **-$15.08** | **-$18.70** | **LOST PROFITABLE STATUS** |
| xsaghav | -$129.99 | -$129.99 | 0 | unchanged |
| fsavhlc | -$21.05 | -$21.05 | 0 | unchanged |
| Jargs | -$10.67 | -$10.67 | 0 | unchanged |
| KING7777777 | -$9.75 | -$9.75 | 0 | unchanged |

sovereign2013's n dropped 199 → 196 (-3), meaning 3 old profitable trades aged out of the 7d rolling window. Those 3 trades had ~+$18 net contribution. No new closes in our DB (`N_CLOSED=0`), so this is pure window-shift math — not a fresh loss event. But the practical consequence is real: **we now have ZERO followed traders who are net-profitable over the 7d window.** Every signal source is currently losing money. The scorer's `trader_edge` component will now penalize all of them.

### Every new closed trade — **NONE** (4th iter in a row — ~30min without a close)

### Every new blocked trade — **7025 TOTAL** (up from 3015 → +133%)

**Rate escalating further**: ~700/min this iter vs ~300/min last iter. Evening sports volume peaking.

**All 7025 still from sovereign2013.** Block rate has more than doubled each iteration.

**Counts by reason:**

| Reason | Iter 3 | Iter 4 | Δ | % iter 4 |
|---|---|---|---|---|
| exposure_limit | 1802 | **4777** | +165% | 68% |
| price_range | 574 | **1309** | +128% | 19% |
| category_blacklist | 423 | 541 | +28% | 8% |
| conviction_ratio | 108 | 212 | +96% | 3% |
| min_trader_usd | 108 | 186 | +72% | 3% |

`exposure_limit` dominates more and more — we're stuck at $3 cap on the same markets while sovereign2013 keeps hammering them.

**Top 15 unique markets (all NBA/MLB/NHL evening):**

1. Bucks vs. 76ers — 360 blocks (same as iter 3, still saturated)
2. Spread: Clippers (-4.5) — 360 (same)
3. Colorado Rockies vs. Padres — 359 (same)
4. Grizzlies vs. Rockets — 356 (**+177** from 179 last iter — sovereign kept adding)
5. Spread: Raptors (-24.5) — 334 (**+296** — new heavy hitter)
6. Wizards vs. Cavaliers — 271 (new market)
7. Spread: Texas Rangers (-2.5) — 253 (new)
8. Pistons vs. Pacers — 249 (new)
9. Spread: Cavaliers (-22.5) — 218 (new)
10. Spread: Raptors (-28.5) — 211 (new)
11. Spread: Raptors (-25.5) — 198 (new)
12. Spread: 76ers (-13.5) — 181 (new)
13. Spread: Magic (-11.5) — 181 (same as iter 3)
14. Spread: San Diego Padres (-5.5) — 180 (new)
15. Canadiens vs. Islanders — 180 (same)

Notable: **sovereign2013 is making MULTIPLE Raptors spread entries** (-24.5, -25.5, -28.5) — he's betting on the same game with different spreads as the line moves. The bot correctly detects each as a different market (different condition_ids) but treats them all as new copies → spam.

### Every new score — **NONE** (scorer never reached, all 7025 blocked upstream)
### Every new brain decision — **NONE** (brain runs every 2h)

### Feedback coverage — UNCHANGED (449 / 59 / 13.1%)
### Score range perf — UNCHANGED (SCORER_INVERTED persists)

### Flags this iter

- [x] **SOVEREIGN_WENT_NEGATIVE** (NEW, critical): +$3.62 → -$15.08 via 7d rolling window shift. All 5 followed traders now net negative 7d. **Zero profitable signal sources.** The brain's `trader_edge` scoring component will now return negative numbers for all traders. When brain next runs, it may try to pause all of them (though piff's disable means it'll only log).
- [x] **BLOCK_SPAM_DOUBLING**: 1090 → 3015 → 7025 across iterations 2-3-4. Rate roughly doubling each iter as evening sports ramp up. 456k total blocked_trades now.
- [x] **OUTCOME_TRACKER_IDLE**: `BLOCKED_CHECKED_15M=0` — no blocked trades got their `would_have_won` updated in 15min. The scheduled `track_outcomes` job runs every 30min but either it has nothing to check or it's silently erroring. Worth watching next iter for a recovery.
- [x] **POSITION_REVAL_UP**: +$1.21 on open positions (no trades). Market moved slightly in our favor on whatever we're holding. Can just as easily go the other direction next cycle.
- [x] **IDLE_TRADE_LOOP**: 4 iterations / ~30min / 0 closes. Bot is effectively a read-only monitor right now.
- [x] **SCORER_INVERTED** (carry): unchanged
- [x] **LOW_FEEDBACK_COVERAGE** (carry): unchanged
- [ ] no BOT_CRASHING (0 errors)
- [ ] no SETTINGS_DRIFT
- [ ] no BRAIN_SPAM

### One-line summary

Iter 4 (Δ10min): $97.33 (Δ +$1.21 reval), today -$39.56 unchanged, **0 closes / 7025 new blocks** (rate doubling each iter). **MAJOR: sovereign2013 fell from +$3.62 → -$15.08 7d — all 5 traders now net-negative 7d, zero profitable signal sources.** Morning report must flag this loudly. Brain's next 2h cycle (~00:00) will see universally-bad trader_edge scores and may react.

---

## Iteration 3 — 2026-04-12 22:07 (Δt ≈ 10 min)

### Snapshot
- **Portfolio**: $96.12 (Δ **-$1.14** since iter 2 — Wallet unchanged $80.27, Positions $17.45 → $15.85 via price revaluation)
- **Today PnL**: -$39.56 (unchanged, still 0 new closes today)
- **Bot errors last 10min**: 0
- **Settings unchanged** (hash identical, no drift)
- **Lifecycle unchanged** (4 DISCOVERED / 2 LIVE_FOLLOW / 3 PAUSED)
- **ML**: not retrained (last 21:35:52, next ~3:35)

### Every new closed trade — **NONE** (3rd iter in a row)

### Every new blocked trade — **3015 TOTAL** (up from 1090 last iter → +176%)

**Rate escalating**: ~300/min this iter vs ~218/min last iter. More evening sports markets opening up = more sovereign2013 activity = more block spam.

**ALL 3015 still from sovereign2013.** Zero blocks from any other trader.

**Counts by reason:**

| Reason | Iter 2 | Iter 3 | Δ | % of iter 3 |
|---|---|---|---|---|
| exposure_limit | 611 | **1802** | +195% | 60% |
| price_range | 143 | **574** | +301% | 19% |
| category_blacklist | 80 | **423** | **+429%** | 14% |
| conviction_ratio | 110 | 108 | ~0% | 4% |
| min_trader_usd | 146 | 108 | -26% | 4% |

**`category_blacklist` surged 5x** — hitting sovereign2013's `nhl|soccer` blacklist harder because hockey markets are live now (evening NHL games). Plus `price_range` tripled — more sub-40c spread markets appearing.

**Unique markets blocked (top 15) — 15 markets now vs 5 last iter:**

| Count | Market | Category |
|---|---|---|
| 358 | Bucks vs. 76ers: O/U 225.5 | nba (exposure_limit) |
| 358 | Colorado Rockies vs. San Diego Padres: O/U 9.5 | mlb (price_range + exposure) |
| 358 | Spread: Clippers (-4.5) | nba (exposure_limit) |
| 181 | Spread: Magic (-11.5) | nba **new this iter** |
| 179 | Canadiens vs. Islanders: O/U 5.5 | **nhl (category_blacklist)** new |
| 179 | Bulls vs. Mavericks | nba new |
| 179 | Bruins vs. Blue Jackets: O/U 5.5 | **nhl** new |
| 179 | Spread: Chicago White Sox (-1.5) | mlb (price_range) |
| 179 | Grizzlies vs. Rockets: O/U 228.5 | nba new |
| 179 | Pelicans vs. Timberwolves | nba new |
| 141 | Nuggets vs. Spurs: O/U 232.5 | nba new |
| 134 | Los Angeles Angels vs. New York Yankees | mlb new |
| 40 | Avalanche vs. Oilers | **nhl** new |
| 39 | Spread: San Diego Padres (-5.5) | mlb new |
| 38 | Spread: Raptors (-24.5) | nba new |

### Every new score — **NONE**
### Every new brain decision — **NONE**

Scorer runs ONLY after all filters pass. Since 0 trades pass, 0 scores. Brain runs every 2h, not this iter.

### Trader 7d delta

| Trader | n Δ | pnl Δ | Notes |
|---|---|---|---|
| sovereign2013 | 203→199 (-4) | +$3.05 → **+$3.62** (+$0.57) | Window shift: 4 aged-out trades had net negative, removing them nudged pnl UP. Still profitable, just barely. |
| All others | unchanged | unchanged | idle |

### Feedback coverage — **UNCHANGED** (449 / 59 / 13.1%)
### Score range perf — **UNCHANGED** (SCORER_INVERTED still 0% on 80-100 bucket)

### Flags this iter

- [x] **BLOCK_SPAM_ACCELERATING**: block rate went 218/min → 300/min (+38%) as evening markets open. Unique blocked markets went 5 → 15. Not fiscal damage — log bloat + wasted DB writes. With `blocked_trades` at 449k rows already, this is noise that's hurting signal.
- [x] **CATEGORY_BLACKLIST_SURGE**: +429% on that reason (80 → 423). Correctly blocking sovereign2013's nhl games but creating MANY rows.
- [x] **BLOCK_DEDUP_NEEDED**: 358 hits on one market (Bucks vs 76ers) in 10 min = 36 hits/min = once every 1.6s. The scan interval is 10s, so we're getting ~6 block_rows per market per scan cycle. Likely the `for side in sides_to_check` loop times `for filter in filter_chain` + duplicate scan paths (activity, position-diff, event-wait).
- [x] **SOVEREIGN_STILL_PROFITABLE**: +$3.62 7d (improved slightly from +$3.05). Only profitable trader.
- [x] **PORTFOLIO_SLIP**: -$1.14 in 10min from position revaluation. Not a trade loss, but holding positions that are drifting down.
- [x] **SCORER_INVERTED** (carry): unchanged, no new scoring data
- [x] **LOW_FEEDBACK_COVERAGE** (carry): unchanged
- [x] **IDLE_TRADERS**: Jargs, KING7777777, fsavhlc, xsaghav all 0 new closes for 3 iterations in a row. aenews2 0 for 3 iter too (expected, new/inactive).
- [ ] no BRAIN_SPAM (0 brain decisions)
- [ ] no PHANTOM_DRIFT (portfolio Δ from revaluation is consistent with 0 closed pnl)
- [ ] no BOT_CRASHING
- [ ] no SETTINGS_DRIFT

### One-line summary

Iter 3 (Δ10min): $96.12 (Δ -$1.14 reval), today -$39.56 unchanged, 0 closes, **3015 new blocks all sovereign2013** (rate +38%, 15 unique markets now). BLOCK_SPAM accelerating. sovereign2013 only profitable (+$3.62 7d). Morning report should recommend blocked_trades dedup + investigate why the scan loop re-evaluates the same blocked markets every cycle instead of caching.

---

## Iteration 2 — 2026-04-12 21:57 (Δt ≈ 7 min)

### Snapshot
- **Portfolio**: $97.26 (Δ -$0.46 since iter 1 — position revaluation, not new closes)
- **Today PnL**: -$39.56 (unchanged — 0 new closes today on server-local clock)
- **Yesterday PnL** (2026-04-11 equivalent in server tz): -$27.99 over 57 trades / 17 wins (29.8% WR)
- **Bot errors last 10min**: 0
- **Settings unchanged** (hash identical, no drift)
- **Lifecycle unchanged** (no new transitions)
- **ML training**: no new runs (expected, every 6h)

### Every new closed trade
**NONE.** Bot has not closed a single position in the last ~7 minutes.

### Every new blocked trade — 1090 TOTAL, ALL sovereign2013

The bot is detecting the same ~5 markets every scan cycle and re-blocking them each time. Not spending money, but spamming `blocked_trades` with duplicate rows.

**Counts by reason (all 1090 rows):**

| Reason | Count | % |
|---|---|---|
| exposure_limit ($3 >= $3 max) | 611 | 56.1% |
| min_trader_usd (all $0.9–$1.8 < $8) | 146 | 13.4% |
| price_range (36c or 22c or 34c outside 42-70c) | 143 | 13.1% |
| conviction_ratio (0.0x–0.5x < 0.5x min) | 110 | 10.1% |
| category_blacklist (nhl/soccer/mlb) | 80 | 7.3% |

**Unique market-conditions re-blocked every scan cycle:**

1. `Colorado Rockies vs. San Diego Padres: O/U 9.5` (cid `0x7c0806...`, mlb)  
   — Both sides tried repeatedly at 36c/63c/34c/66c, hits `price_range` (outside 42-70c) or `exposure_limit` depending on side.
2. `Bucks vs. 76ers: O/U 225.5` (cid `0x14d57e...`, nba)  
   — Under @ 51c, hits `exposure_limit $3 >= $3 max` every cycle.
3. `Spread: Chicago White Sox (-1.5)` (cid `0xcb2c7c...`, mlb)  
   — 22c or 17c, hits `price_range`.
4. `Spread: Clippers (-4.5)` (cid `0x90e6fa...`, nba)  
   — 49.5c, hits `exposure_limit`.
5. `Magic vs. Celtics: O/U 222.5` (cid `0x183845...`, miscategorized as **cs**)  
   — sovereign2013 bought $0.9–$1.8 tiny lots, hits `min_trader_usd $<$8 min` 30+ times. **Also: category detection mis-classified NBA as `cs`** (probably because "Celtics" contains "celt..." which could match a CS team name pattern).
6. `Pistons vs. Pacers: O/U 230.5` (cid `0xefc672...`, nba)  
   — hits `conviction_ratio 0.0x < 0.5x min`

### Every new score — **NONE**

No trades scored in this iteration. All 1090 events were blocked BEFORE reaching the scorer (filter chain runs before scorer).

### Every new brain decision — **NONE**

Brain runs every 2h, not this iteration. Next brain cycle: ~2h from the last run.

### Trader 7d delta (rolling window)

| Trader | Iter1 trades | Iter2 trades | Δn | Iter1 PnL | Iter2 PnL | ΔPnL |
|---|---|---|---|---|---|---|
| sovereign2013 | 208 | 203 | **-5** | +$14.12 | **+$3.05** | **-$11.07** |
| xsaghav | 191 | 189 | -2 | -$118.87 | **-$129.99** | -$11.12 |
| KING7777777 | 133 | 133 | 0 | -$9.75 | -$9.75 | 0 |
| fsavhlc | 20 | 20 | 0 | -$21.05 | -$21.05 | 0 |
| Jargs | 17 | 17 | 0 | -$10.67 | -$10.67 | 0 |
| aenews2 | 0 | 0 | 0 | - | - | 0 |

Both sovereign2013 and xsaghav lost trades from 7d window (older trades aged out) — the delta is the rolling window shift, not new activity. sovereign2013's PnL dropped -$11 because the 5 aged-out trades were net winners, and xsaghav's PnL dropped -$11 because his 2 aged-out trades were net losers being replaced by 0 new ones → the remaining -$118 shifted to -$129 as older positives fell off.

Neither is "new loss" — just 7d window math. But worth noting for morning report that **sovereign2013 is the only still-profitable trader** and his cushion is shrinking (+$14 → +$3).

### Feedback loop coverage

- `trade_scores` total: 449 (unchanged)
- With outcome_pnl: 59 (unchanged, 13.1%)
- **LOW_FEEDBACK_COVERAGE persists** — no new scores to update. Backfill hasn't run in this window (outcome_tracker runs every 30min).

### Score range perf — UNCHANGED

Same as iter 1 baseline. Still showing:
- 40-59: 6, 0W/6L, -$80.58
- 60-79: 37, 32W/5L, +$9.26
- 80-100: 16, 0W/16L, -$47.90

**SCORER_INVERTED persists** — no new scored trades to refresh the picture.

### Flags raised this iteration

- [x] **BLOCK_SPAM**: 1090 blocks / 0 copies. 218 blocks/min from sovereign2013 only. Same 5 markets re-blocked every scan cycle. Optimization target: dedupe blocked_trades on (trader, cid, reason) within a sliding window (e.g. 60s) so we log once per unique rule+market hit, not per scan.
- [x] **FILTER_TOO_TIGHT_FOR_SOVEREIGN**: ratio 1090/0 (no copies despite massive input signal). But this is BY DESIGN — sovereign2013 is a whale ($1400 avg) making $1-$3 test trades that shouldn't be copied. The filters are correct, the noise is just making the block log explode.
- [x] **CATEGORY_MISDETECT**: `Magic vs. Celtics: O/U 222.5` being classified as `cs` category. "Celtics" partial-match with a CS team pattern. Bug in `_detect_category` keyword matching. Low priority (doesn't affect outcome, all attempts were blocked anyway).
- [x] **SOVEREIGN_PNL_EROSION**: 7d PnL dropped +$14 → +$3 (rolling window, aged-out winners). He's the only profitable trader — if this hits 0 or negative, the bot has zero profitable signal source.
- [x] **SCORER_INVERTED** (carry from iter 1): 80-100 bucket still 0% WR. Unchanged.
- [x] **LOW_FEEDBACK_COVERAGE** (carry): 13.1%, no growth this iteration.
- [ ] no BRAIN_SPAM (0 brain decisions)
- [ ] no PHANTOM_DRIFT (portfolio Δ -$0.46 matches zero closes)
- [ ] no BOT_CRASHING (0 errors)
- [ ] no SETTINGS_DRIFT (hash identical)
- [ ] no ML_NOT_RETRAINING (last train 21:35, only ~30min ago)

### One-line summary

Iter 2 (Δ~7min): Portfolio $97.26 (Δ -$0.46), today -$39.56 unchanged, 0 new closes, **1090 new blocks all sovereign2013 spamming 5 markets every scan** (exposure_limit dominant). Top concerns: BLOCK_SPAM (log bloat, not $ impact) + SOVEREIGN_PNL_EROSION (+$14 → +$3 7d). Morning report should flag both.

---

## Iteration 1 — 2026-04-12 21:50 (BASELINE, Δt=initial)

First loop run. State was empty so this is a baseline snapshot. No NEW_* queries run — instead we captured the current MAX IDs and trader snapshots so iteration 2 onward will only see deltas.

### Snapshot
- **Portfolio**: $97.72 (Wallet $80.27 + Positions $17.45)
- **Today PnL**: -$39.56 (26 closes, 5 wins / 21 losses → **19% WR today** — rough day)
- **Followed live** (from `settings.env` FOLLOWED_TRADERS): **3** (Jargs, sovereign2013, KING7777777)
- **Bot errors last 10min**: 0 (healthy)

### Scorer Feedback Coverage
- `trade_scores` total: 449
- With `outcome_pnl`: **59** (13.1%) — feedback backfill is filling but slowly
- Of those 59: 32 winners, 27 losers → 54.2% WR on outcome-bearing scores

### 🚨 FLAG: SCORER_INVERTED (critical finding)

Score-range performance on the 59 outcome-bearing scores:

| Bucket | n | Wins | Losses | Total PnL | Notes |
|---|---|---|---|---|---|
| 40-59 | 6 | 0 | 6 | **-$80.58** | all losers, but expected (QUEUE action) |
| 60-79 | 37 | 32 | 5 | **+$9.26** | **86.5% WR** — EXECUTE action works |
| 80-100 | 16 | 0 | 16 | **-$47.90** | **0% WR on 16 trades** — BOOST action is broken |

The scorer's highest-confidence predictions (BOOST, ≥80) are **100% losers**. The middle tier (EXECUTE, 60-79) is the profitable one. Brain's `_optimize_score_weights` only tunes down the BLOCK threshold when blocked trades would have won — it has **no mechanism to lower the BOOST threshold when boosted trades lose**. Need to add that logic, OR investigate whether the BOOST-bucket samples are all from one bad trader/category (small sample bias).

### Brain pause_count oscillation

Lifecycle row `pause_count` values:
- xsaghav: **17** (last changed 20:58)
- fsavhlc: **17** (last changed 20:58)
- sovereign2013: 1 (last changed 07:49)
- Jargs, KING7777777: 0 (LIVE_FOLLOW, bootstrap-seeded)

xsaghav + fsavhlc have been "paused" 17 times today. Since piff's PATCH-023 disables the actual `pause_trader()` call but still writes the lifecycle state via... wait, if PATCH-023 disables it, how is pause_count being incremented? Worth investigating: something is calling `update_lifecycle_status(..., "PAUSED", ...)` repeatedly. Not critical since settings.env FOLLOWED_TRADERS already excludes them, but cosmetically annoying and probably brain_engine running on every 2h cycle.

### Soft-vs-hard state drift (known, noted)

Expected by design per piff's philosophy, but worth noting for the morning report context:
- sovereign2013: soft=`active` (trader_performance restored at 14:29 based on +$1.04 7d PnL), hard=`PAUSED` in lifecycle, actually followed in settings.env (YES). Functional but confusing.
- xsaghav: soft=paused, hard=PAUSED, NOT followed. Consistent.
- fsavhlc: soft=paused, hard=PAUSED, NOT followed. Consistent.

### 7d trader rolling (snapshot)

| Trader | Trades | Wins | Losses | WR | PnL | Avg Size |
|---|---|---|---|---|---|---|
| sovereign2013 | 208 | 103 | 103 | 49.5% | **+$14.12** | $0.42 |
| KING7777777 | 133 | 55 | 78 | 41.4% | -$9.75 | $2.73 |
| xsaghav | 191 | 81 | 108 | 42.4% | **-$118.87** | $1.02 |
| fsavhlc | 20 | 8 | 11 | 40.0% | -$21.05 | $0.63 |
| Jargs | 17 | 8 | 9 | 47.1% | -$10.67 | $1.19 |
| aenews2 | 0 | - | - | - | - | - |

**sovereign2013 is the only profitable trader** (+$14.12). He's followed, but the "PAUSED" lifecycle row is misleading. He's also marked `active` in trader_status. Good.

### Signal performance

- `clv_tracking`: 390 trades, 276 wins / 108 losses, total PnL +$808.89 (cumulative, not session) — clv_tracker fix from Task 7 is producing real counts.

### ML training

Last 3 runs (all ~21:30-35):
- 7306 samples, reported accuracy 0.9316
- Accuracy is STILL suspiciously high after my time-split fix. Need to see the baseline-accuracy log line from journalctl (not persisted to DB) to know if it beats the majority-class baseline. Worth a targeted log grep next iteration.

### Settings (current)

- FOLLOWED_TRADERS = Jargs, sovereign2013, KING7777777 (3 traders)
- CATEGORY_BLACKLIST_MAP = KING7777777:dota, fsavhlc:geopolitics, sovereign2013:nhl|soccer, xsaghav:valorant
- MAX_DAILY_LOSS = **0** (unlimited, disabled per user)
- MAX_DAILY_TRADES = 30
- STOP_LOSS_PCT = 0.25

### Flags raised

- [x] **SCORER_INVERTED** — BOOST bucket 0% WR on 16 trades. Critical.
- [x] **LOW_FEEDBACK_COVERAGE** — only 13.1% of trade_scores have outcome_pnl. Not yet dying but watch.
- [x] **PAUSE_COUNT_OSCILLATION** — xsaghav/fsavhlc pause_count=17. Something re-pausing.
- [ ] no BRAIN_SPAM (can't tell yet, no delta data)
- [ ] no FILTER_TOO_TIGHT (can't tell yet)
- [ ] no PHANTOM_DRIFT (no prior portfolio)
- [ ] no BOT_CRASHING (0 errors)
- [ ] no ML_NOT_RETRAINING (last train 21:35, fresh)

### One-line summary

Iter 1 BASELINE: Portfolio $97.72, today -$39.56 (19% WR), 3 followed. **Top concern: SCORER_INVERTED** — 80-100 score bucket is 0% WR (16 trades, -$47.90). Brain has no logic to tune BOOST threshold down.

---

## Archive
