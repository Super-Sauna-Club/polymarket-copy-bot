# Poly Copybot - Updates & Usage Guide

## What's New ✨

This update introduces **smart position detection** and **intelligent trade management** for the Polymarket Poly Copybot.

### Key Improvements

#### 1. **Smart Position Detection**
- **Baseline Scanning**: First scan of a followed trader records all existing positions (no copying)
- **New Position Detection**: Only copies positions that appear AFTER the baseline scan
- **Position Snapshots**: Tracks trader's position history to detect changes accurately
- **No Premature Closes**: Won't close trades just because an API call failed

#### 2. **Intelligent Closing**
- **Trader-Following**: Automatically closes your copies when the trader closes their position
- **Miss Count System**: Only closes after position is missing for 20 consecutive scans (prevents API errors from causing false closes)
- **Market Resolution**: Instantly closes trades when market resolves (redeemable)
- **Live Price Updates**: Uses Gamma API for accurate exit prices

#### 3. **Better Logging**
- Emoji indicators for quick status reading
- Clear separation of baseline, new, open, and closed trades
- Real-time P&L tracking

#### 4. **New Database Tables**
```
trader_position_snapshots   → Tracks each trader's positions over time
trader_position_trace       → Logs position changes for audit trail
```

---

## Commands & Scripts

### Run Statistics Display
```bash
python show_stats.py
```
Shows:
- Portfolio summary (balance, P&L, total value)
- Followed wallets
- All open trades with current prices & P&L
- Recently closed trades

### Reset System Completely
```bash
python reset.py
```
⚠️ **WARNING**: This will delete:
- ✓ All open trades
- ✓ All closed trades & P&L history
- ✓ All position snapshots & baselines
- ✓ Reset portfolio to $100 starting balance

**But keeps**:
- ✓ Followed wallets (follow status preserved)
- ✓ Wallet rankings and analysis

### Start Scheduler
```bash
python main.py
```
Runs the Poly Copybot with:
- **Copy Scan**: Every 30 seconds (detects new positions)
- **Price Update**: Every 30 seconds (updates P&L, closes positions)
- **Dashboard**: Available at http://localhost:8501

---

## How It Works

### Position Flow

```
1. BASELINE SCAN (First time only)
   └─ Read all current positions from trader
   └─ Save as baseline (no copying)
   └─ Mark trader as baselined

2. NEW POSITION DETECTION (Every 30 seconds)
   └─ Scan trader's current positions
   └─ Compare with previous snapshot
   └─ Detect NEW positions (not in baseline)
   └─ Copy only NEW positions at current market price
   └─ Save updated snapshot

3. PRICE UPDATES & CLOSING (Every 30 seconds)
   └─ Update current price for each open trade
   └─ Calculate unrealized P&L
   └─ Check if trader still has position:
      ├─ YES → Update price, keep open
      ├─ NO  → Increment miss counter
      │        After 20 misses → Close trade (trader closed)
      └─ RESOLVED → Close immediately (market ended)

4. SNAPSHOT FOR NEXT COMPARISON
   └─ Save current position list
   └─ Use for next scan cycle
```

### Position Matching

Trades are matched using:
1. **Primary**: `condition_id` (unique Polymarket identifier)
2. **Fallback**: `market_question` (for old trades without condition_id)

This ensures we track the exact same position even if details change.

---

## Example Workflow

```
Trader 0xDEADBEEF currently has:
  ├─ Bitcoin $75k (condition_id: abc123) - Entry: $2.50
  ├─ Ethereum $3k (condition_id: def456) - Entry: $4.00
  └─ Dogecoin Up (condition_id: ghi789) - Entry: $1.50
│
├─ BASELINE SCAN
│  └─ Saves all 3 positions as baseline (no copy)
│
├─ 30 seconds later - SCAN 1
│  └─ Trader still has same 3 positions
│  └─ No new positions detected
│  └─ Prices updated: Bitcoin $75k @ 2.55, Ethereum @ 4.10, Dogecoin @ 1.45
│
├─ 30 seconds later - SCAN 2
│  └─ Trader adds: AAPL Stock @ 2.00 (condition_id: jkl012) ✨ NEW!
│  └─ COPY → Buy AAPL at $2.00
│  └─ Bitcoin position still open → Update price
│  └─ Ethereum position still open → Update price
│  └─ Dogecoin position still open → Update price
│
└─ 30 seconds later - SCAN 3
   └─ Trader closes Bitcoin position
   └─ Miss count for Bitcoin = 1 (not found)
   └─ After 20 misses → Close our Bitcoin copy
   └─ Other positions still open → Continue tracking
```

---

## Configuration

Edit `config.py` to adjust:
```python
MIN_VOLUME = 10000          # Minimum trader volume
MIN_PNL = 100               # Minimum trader profit
AUTO_FOLLOW_COUNT = 10      # Auto-follow top N traders
SCAN_WALLET_LIMIT = 500     # Wallets to scan
```

**Position Copying Constants** (in `bot/copy_trader.py`):
```python
STARTING_BALANCE = 100      # Paper mode capital
MAX_INVESTED_PCT = 0.50     # Max 50% invested (50% cash reserve)
MAX_POSITION_SIZE = 5       # Max $5 per trade
MIN_TRADE_SIZE = 1.0        # Min $1 per trade
CASH_RESERVE = 0            # Reserved cash
MISS_COUNT_TO_CLOSE = 20    # Scans before closing as trader-closed
```

---

## Troubleshooting

### "Trader closed" but they didn't
- Check `MISS_COUNT_TO_CLOSE` - might be too low
- API pagination issues can hide positions
- Increase to 30 or 40 for more patience

### Not copying new positions
1. Check if trader is followed: `python show_stats.py`
2. Verify baseline was done: Check for "BASELINE" in logs
3. Check if conditions met:
   - Position size > $0.50
   - Entry price between 1¢ and 99¢
   - Not a resolved market

### P&L looks wrong
- Unrealized P&L updates every 30 seconds
- Live prices from Gamma API override cached prices
- Check `show_stats.py` output

---

## Database Schema

### Key Tables

**copy_trades** → Individual trade records
```
id, wallet_address, market_question, side, 
entry_price, current_price, size, 
pnl_unrealized, pnl_realized, status (open/closed),
created_at, closed_at
```

**trader_position_snapshots** → Position history
```
wallet_address, condition_id, market_question, 
side, size, current_price, is_open, snapshot_time
```

---

## Performance Tips

- Run on a server (faster API calls)
- Increase scan frequency in main.py for faster new trade detection
- Reduce MISS_COUNT_TO_CLOSE for quicker closing on trader exit
- Monitor `logs/wallet-scanner.log` for detailed activity

---

## Support

Check logs:
```bash
tail -f logs/wallet-scanner.log
```

Monitor live:
```bash
python show_stats.py  # Shows current state
```

---

**Last Updated**: 2026-03-26
