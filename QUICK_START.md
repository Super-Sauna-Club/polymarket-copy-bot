# Quick Start Guide - Poly Copybot Updates

## What Changed? ✅

Your Poly Copybot now has **intelligent position detection** that:
1. ✅ Only copies NEW trader positions (not existing ones)
2. ✅ Automatically closes copies when trader closes theirs
3. ✅ Tracks position history to detect changes accurately
4. ✅ Prevents accidental closes from API failures

---

## How to Use

### 1️⃣ View Current Status
```bash
python show_stats.py
```
Shows:
- Portfolio balance & P&L
- All followed wallets
- Current open trades
- Recently closed trades

### 2️⃣ Start the Bot
```bash
python main.py
```
Then open: http://localhost:8501

**What it does every 30 seconds:**
- 🔍 Scans followed traders for NEW positions
- 💰 Updates prices and calculates P&L
- 🔐 Closes trades when trader closes theirs

### 3️⃣ Reset Everything (⚠️ Be careful!)
```bash
python reset_copy_trading.py
```
- Deletes ALL trades and history
- Sets portfolio back to $100
- Keeps followed wallets

---

## Key Improvements

### Smart Detection
- **Before**: Scanned all positions, copied duplicates
- **After**: Detects ONLY new positions, never copies twice

### Better Closing
- **Before**: Closed if position missing once or twice
- **After**: Only closes after 20 consecutive scans confirm trader closed it

### Live Pricing
- **Before**: Used cached prices, sometimes stale
- **After**: Uses Gamma API for accurate exit prices

### Detailed Logging
- Clear logs showing baseline, new, open, closed trades
- Easy to debug what's happening

---

## Example Session

```
TRADER: 0xDEADBEEF

Day 1:
├─ Baseline scan → Trader has 3 positions
├─ NOT copied (baseline only)
└─ System learns these 3 baseline positions

Day 2:
├─ Trader adds NEW position #4
├─ COPIED immediately ✅
├─ Trades #1-3 just updated (prices, P&L)
└─ Tracked in position snapshots

Day 3:
├─ Trader closes position #2
├─ Miss counter starts: 1/20
├─ Other positions still open
├─ After 20 scans → confirm trader closed it
└─ Close our copy automatically

Day 4:
├─ Trader adds NEW position #5
├─ COPIED immediately ✅
└─ Continue tracking...
```

---

## Scripts Included

| File | Purpose |
|------|---------|
| `show_stats.py` | View portfolio, trades, stats |
| `reset_copy_trading.py` | Wipe all trades (reset fresh) |
| `test_reset.py` | Test reset functionality |
| `COPY_TRADING_GUIDE.md` | Detailed documentation |

---

## Monitoring Tips

**Real-time logs:**
```bash
tail -f logs/wallet-scanner.log
```

**Check specific trader:**
- Follow them in dashboard
- Wait for baseline scan (first scan)
- Monitor `show_stats.py` for new copies

**Adjust sensitivity:**
- Edit `MISS_COUNT_TO_CLOSE` in `bot/copy_trader.py` if closing too fast/slow
- Default is 20 scans (10 minutes at 30-second intervals)

---

## Troubleshooting

**No trades copying?**
- Run `show_stats.py` to check followed wallets
- Check if baseline done (should show in logs)
- Verify trader has positions > $0.50

**Closing too fast?**
- Increase `MISS_COUNT_TO_CLOSE` to 30-40
- More patient before closing

**Portfolio jumping?**
- Probably a closed trade settling
- Check previous `show_stats.py` output

---

## Need Help?

1. **See current state**: `python show_stats.py`
2. **Check logs**: `tail -f logs/wallet-scanner.log`
3. **Read full guide**: `COPY_TRADING_GUIDE.md`

---

**System Ready to Deploy! 🚀**
