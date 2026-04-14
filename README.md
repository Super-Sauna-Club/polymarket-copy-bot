# Poly CopyBot by Super Sauna Club

Ein automatischer Copy-Trading Bot fuer [Polymarket](https://polymarket.com). Folgt den besten Tradern und kopiert ihre Wetten mit echtem Geld.

---

## Was ist Polymarket?

Polymarket ist eine Wettboerse im Internet. Du kannst auf quasi alles wetten: Sport, Politik, Wirtschaft, Wetter — alles. Der Preis zeigt dir, wie wahrscheinlich etwas ist:

| Preis | Bedeutung | Beispiel |
|-------|-----------|----------|
| **10 Cent** | Unwahrscheinlich (10%) | "Wird es morgen in der Sahara schneien?" |
| **30 Cent** | Aussenseiter (30%) | "Gewinnen die Tigers heute?" |
| **50 Cent** | Muenzwurf (50/50) | "Kopf oder Zahl" |
| **80 Cent** | Sehr wahrscheinlich (80%) | "Gewinnt der Tabellenerste?" |
| **95 Cent** | Fast sicher (95%) | "Geht morgen die Sonne auf?" |

**So funktioniert das Geld:**

```
Du kaufst "Lakers gewinnen" fuer 30 Cent pro Anteil.
Du kaufst 10 Anteile = $3.00 investiert.

Fall A: Lakers gewinnen → 10 Anteile x $1.00 = $10.00 (Gewinn: $7.00)
Fall B: Lakers verlieren → 10 Anteile x $0.00 = $0.00 (Verlust: $3.00)
```

Je billiger du kaufst, desto mehr Gewinn wenn es klappt — aber desto unwahrscheinlicher ist es.

---

## Was macht der Bot?

Auf Polymarket gibt es Profis die den ganzen Tag Statistiken analysieren und damit Millionen verdienen. Unser Bot **schaut denen ueber die Schulter** und kopiert ihre Wetten automatisch.

```
1. Trader kauft "Lakers gewinnen" fuer $500 bei 40 Cent
2. Bot erkennt das nach 5 Sekunden
3. Bot kauft dasselbe fuer $15 bei 40 Cent
4. Lakers gewinnen!
5. Trader bekommt $1250 (Gewinn $750)
6. Bot bekommt $37.50 (Gewinn $22.50)
```

Du musst nichts ueber Sport oder Politik wissen. Der Bot kopiert einfach die Leute die sich auskennen.

### Warum nicht einfach ALLES kopieren?

Weil selbst Profis manchmal Mist machen. Deshalb hat der Bot ein ganzes System an Filtern und Sicherheiten. Dazu gleich mehr.

---

## Features

- **Copy Trading** — Kopiert Positionen von gefolgten Tradern innerhalb von 5 Sekunden
- **5 Buy-Pfade** — Activity Scan, Position-Diff, Event-Wait, Hedge-Wait, Pending-Buy (alle mit denselben Filtern und Size-Caps)
- **Thread-Safe** — Buy-Lock verhindert Race Conditions bei gleichzeitigen Scans
- **Proportionales Sizing** — Wetteinsatz skaliert mit der Ueberzeugung des Traders (0.2x bis 3.0x)
- **Kategorie-Blacklist** — Pro Trader bestimmte Sportarten/Kategorien blocken (Erkennung: NBA, MLB, NHL, NFL, Tennis, Soccer, CS, LoL, Valorant, Dota, Geopolitik, Cricket). Seit 2026-04-14 rein manuell — Brain/Auto-Tuner schreiben nur noch Empfehlungen, nicht in settings.env
- **Hedge-Erkennung** — Erkennt wenn ein Trader beide Seiten kauft und ueberspringt beides
- **Size-Caps** — Alle Limits (Event, Match, Exposure, Position) cappen die Trade-Groesse auf den verbleibenden Platz (nicht nur Skip bei voll)
- **Sell-before-Close** — Verkauft Shares BEVOR die DB geschlossen wird (keine verwaisten Positionen)
- **Atomic Close** (2026-04-14) — `close_copy_trade()` schreibt `status/pnl_realized/usdc_received/current_price` in einem einzigen atomaren UPDATE. Keine NULL `usdc_received` Rows mehr
- **Fast-Sell** — Kopiert Verkaeufe der Trader innerhalb von 5 Sekunden
- **Auto-Sell** — Verkauft gewonnene Positionen ab 96 Cent automatisch
- **Auto-Redeem** — Loest gewonnene Positionen ueber den Builder Relayer ein
- **P&L-Tracking** — Misst echten Fill-Preis (USDC-Delta), nicht geplanten Preis
- **P&L-Monitor** — Dauerhafter Service der bei jedem Close DB-P&L vs. USDC-Delta vergleicht
- **Backfill Tool** (2026-04-14) — `backfill_usdc_received.py` pullt Polymarket Activity-API und fixt historische NULL `usdc_received` Rows. 1:1 greedy matching, dry-run default, `--apply` writes
- **Stale-Position-Erkennung** — Schliesst Positionen die aus der Trader-Wallet verschwunden sind
- **Live Dashboard** — Echtzeit mit Equity-Kurve, 24h-Trader-Performance, Exposure-Meter, Sound-System, **Filter Precision Audit** (neu 2026-04-14)
- **Circuit Breaker** — Pausiert nach 8 API-Fehlern fuer 60 Sekunden
- **AI Analysis Pipeline** — Loggt alle geblockten Trades, trackt Outcomes ("was waere gewesen?"), Claude analysiert und empfiehlt Parameter-Aenderungen
- **Brain Engine** — Selbst-optimierendes Intelligenz-Modul (laeuft alle 2h): klassifiziert Verluste, pausiert/kickt schlechte Trader, optimiert Score-Gewichte automatisch
- **Trade Scorer** — Bewertet jeden Trade vor Ausfuehrung mit Score 0-100 (Trader Edge, Category WR, Price Signal, Conviction, Market Quality, Correlation). Blockt schlechte Trades, boostet gute
- **Two-Model ML System** (2026-04-14) — `ml_copy` trainiert nur auf copy_trades fuer Live-Entscheidungen, `ml_block` trainiert nur auf blocked_trades fuer Filter-Audit. Self-disabling edge gate: ml_copy adjustments greifen nur wenn Modell die Baseline schlaegt
- **Filter Precision Audit** (2026-04-14) — Pro Filter-Reason misst ob Regeln echte Winner blocken oder korrekt Verlierer aussortieren. Magnitude-aware via verified per-(trader, category) $PnL — WR-basierte LOOSEN-Empfehlung wird von Ground-Truth-Dollar-Daten ueberschrieben wenn asymmetric
- **Trader Lifecycle** — Automatischer Lebenszyklus: DISCOVERED → OBSERVING → PAPER_FOLLOW → LIVE_FOLLOW → PAUSED → KICKED. Findet, testet und promoted neue Trader selbstaendig
- **Autonomous Trading** — Eigene Trades basierend auf Momentum + AI Divergence Signalen. Startet im Paper-Modus, wird bei bewiesener Performance automatisch auf Live promoted

---

## Wie funktioniert das Sizing?

Der Bot kopiert nicht einfach blind — er schaut wie UEBERZEUGT der Trader ist.

### Conviction Ratio (Ueberzeugung)

Jeder Trader hat eine durchschnittliche Wettgroesse. Wenn er mehr als normal setzt, ist er sich sicher. Wenn weniger, ist es wahrscheinlich nur ein Test.

```
Trader setzt normalerweise $100 pro Wette (Durchschnitt).

Wette A: Trader setzt $300 (3x Durchschnitt = sehr ueberzeugt)
  → Bot setzt: $15 Basis x 3.0 Ratio = $45

Wette B: Trader setzt $100 (1x Durchschnitt = normal)
  → Bot setzt: $15 Basis x 1.0 Ratio = $15

Wette C: Trader setzt $10 (0.1x Durchschnitt = nur ein Test)
  → Bot setzt: $15 Basis x 0.2 Ratio (Minimum) = $3
```

### Preis-Signal

Wetten weit weg von 50 Cent zeigen staerkere Ueberzeugung.

```
Preis 15c → Starkes Signal  → Einsatz x 1.5
Preis 30c → Normales Signal → Einsatz x 1.0
Preis 45c → Schwaches Signal → Einsatz x 0.6
```

### Die komplette Formel

```
Endgroesse = Basis x Preis-Multiplikator x Conviction-Ratio

Basis     = Wallet x BET_SIZE_PCT (oder BET_SIZE_MAP pro Trader)
Preis     = 1.5x (stark) / 1.0x (normal) / 0.6x (schwach)
Conviction = Trader-Wette / Trader-Durchschnitt (begrenzt auf RATIO_MIN bis RATIO_MAX)
```

---

## Sicherheits-Features

### Thread-Safe Buy-Lock

Alle 5 Buy-Pfade sind mit einem `_buy_lock` geschuetzt. Verhindert dass zwei Scan-Zyklen gleichzeitig denselben Markt kaufen.

### Sell-before-Close

Bei Stop-Loss, Take-Profit und Copy-Sell wird **zuerst verkauft, dann die DB geschlossen**. Wenn der Sell fehlschlaegt, bleibt die Position offen — keine verwaisten Shares im Wallet.

### Size-Caps auf allen Limits

Jedes Limit (MAX_PER_EVENT, MAX_PER_MATCH, Exposure, Position) **cappt die Trade-Groesse** auf den verbleibenden Platz. Vorher wurde nur bei vollem Limit uebersprungen — jetzt wird die Groesse reduziert.

```
Match-Limit: $15, bereits investiert: $8
Geplante Trade-Groesse: $12
→ Gecappt auf $7 ($15 - $8)
```

### Cash Floor (Notbremse)

```
CASH_FLOOR=20        → Unter $20 wird nicht mehr gekauft
CASH_RECOVERY=6      → Erst wenn Cash $26 erreicht ($20 + $6) wird wieder gekauft
SAVE_POINT_STEP=1    → Danach steigt der Floor auf $21, naechste Recovery bei $27, usw.
```

### Max Exposure pro Trader

Jeder Trader darf nur einen bestimmten Prozentsatz deines Portfolios nutzen. Die Trade-Groesse wird auf den verbleibenden Platz gecappt.

```
Portfolio: $200, KING: 65% Exposure
→ Max $130 fuer KING, hat $50 → naechster Trade max $80
```

### Max pro Event/Match

```
MAX_PER_EVENT=15   → Maximal $15 pro Spiel
MAX_PER_MATCH=15   → Gilt auch fuer zusammengehoerende Maerkte (Map 1 + Map 2 + BO3 = 1 Match)
```

### Kategorie-Blacklist

Bestimmte Sportarten/Kategorien pro Trader blockieren. Der Bot erkennt die Kategorie automatisch anhand von Keywords im Marktnamen.

```
CATEGORY_BLACKLIST_MAP=sovereign2013:tennis|mlb|soccer|nba|nfl|nhl|cricket|geopolitics,xsaghav:cs|valorant
```

Esports-Kategorien (CS, LoL, Valorant, Dota) werden ZUERST geprueft — vermeidet falsche Matches mit generischen Sport-Keywords (z.B. "Wildcard" im Teamnamen ≠ NHL "Wild").

### NO_REBUY (Kauf-Loop-Schutz)

Esports-Maerkte resolven manchmal in 30 Sekunden. Ohne Schutz kauft der Bot denselben Markt 10x hintereinander.

```
NO_REBUY_MINUTES=120  → 2 Stunden Sperre nach Close/Sell fuer selben Markt
```

Alle DB-Queries (MAX_COPIES, Cross-Trader-Dupe) nutzen ein Fenster von `max(NO_REBUY_MINUTES, 30)` Minuten.

Bei DB-Fehler wird der Trade konservativ uebersprungen (nicht durchgelassen).

### Circuit Breaker

```
CB_THRESHOLD=8      → Nach 8 API-Fehlern hintereinander: Pause
CB_PAUSE_SECS=60    → 60 Sekunden warten, dann weiter
```

---

## P&L-Tracking

### Echte Fill-Preise

Der Bot misst nach jedem Kauf/Verkauf den echten USDC- und Token-Balance-Delta. Dadurch wird der tatsaechliche Fill-Preis (inkl. Slippage + Fees) in der DB gespeichert.

**DB-Spalten:** `actual_entry_price`, `actual_size`, `shares_held`, `usdc_received`

Die Standard-Felder (`entry_price`, `size`) enthalten den geplanten Preis. Fuer echte P&L wird immer `actual_entry_price` verwendet (Fallback auf `entry_price` wenn NULL).

### Drag (versteckte Kosten)

Polymarket Fees + Slippage kosten 10-20% pro Roundtrip. Der Bot erfasst diese Kosten korrekt:

- **Kauf:** `actual_size` = echtes USDC-Delta (Wallet vorher - nachher), inkl. Fees + Slippage
- **Verkauf:** `usdc_received` = echtes USDC-Delta, inkl. Exit-Fees
- **Resolved:** Keine Exit-Fee bei Redemption, Entry-Fee in `actual_entry_price` enthalten
- **DB-P&L = Echte P&L** fuer verkaufte und resolved Positionen

| Kostenart | Betrag | Erklaerung |
|-----------|--------|------------|
| Fees | 0-10% | Esports/Sport: 10% (1000bps). NHL/Politik: 0% |
| Slippage | 2-5c | BUY_SLIPPAGE_LEVELS startet bei +2c |
| Gesamt | 12-20% | Pro Roundtrip (Kauf + Verkauf) |

**Konsequenz:** Unrealized P&L im Dashboard enthaelt noch keine Exit-Fee — erst bei Verkauf wird die echte P&L berechnet.

### P&L-Monitor

Laeuft als dauerhafter systemd Service (`pnl-monitor.service`). Vergleicht bei jedem Close die DB-P&L mit dem echten USDC-Delta und gibt Alarm wenn die Werte abweichen:

- `[PNL OK]` — DB und USDC stimmen ueberein
- `[PNL DRIFT]` — Abweichung >$0.05 (warnung)
- `[PNL ALARM]` — Abweichung >$0.50 (fehler)

Log: `logs/pnl_monitor.log`

---

## Dashboard

Eine Website auf deinem Server die in Echtzeit zeigt was passiert:

- **Kennzahlen** — Gesamtwert, Gewinn/Verlust, Wallet-Balance, offene Positionen, Win-Rate
- **Equity-Kurve** — Portfolio-Entwicklung (4H/1D/1W/1M/Alles)
- **Trader-Performance** — Live 24h-Karten pro Trader mit P&L, Win-Rate, All-Time-Vergleich
- **Aktivitaets-Log** — Live-Feed aller Kaeufe, Verkaeufe, Gewinne, Verluste mit Sport-Emojis
- **Aktive Positionen** — Alle offenen Wetten mit aktuellem Gewinn/Verlust
- **Geschlossene Positionen** — Handelshistorie sortiert nach Datum
- **Exposure-Meter** — Balken pro Trader der zeigt wie viel vom Budget verbraucht ist
- **Settings-Ansicht** — Alle aktiven Einstellungen auf einen Blick (inkl. SELL_VERIFY_THRESHOLD, CATEGORY_BLACKLIST)
- **Sound-System** — Gewinn/Verlust/Trade Sounds mit GIFs (alles einzeln ein/ausschaltbar)
- **Widescreen-Modus** — Fullscreen-Layout fuer grosse Bildschirme (`/copy?wide=1`)

---

## Brain Engine (Self-Optimizing)

Der Bot optimiert sich alle 2 Stunden selbst. Keine manuelle Anpassung noetig.

> **WICHTIG:** Brain Engine + Auto-Tuner schreiben automatisch in
> `settings.env`. Auto-managed Maps die bei jedem Brain-Cycle (alle 2h)
> ueberschrieben werden: `BET_SIZE_MAP`, `TRADER_EXPOSURE_MAP`,
> `MIN/MAX_ENTRY_PRICE_MAP`, `MIN_TRADER_USD_MAP`, `TAKE_PROFIT_MAP`,
> `STOP_LOSS_MAP`, `MAX_COPIES_PER_MARKET_MAP`, `HEDGE_WAIT_TRADERS`,
> `MIN_CONVICTION_RATIO_MAP`, `AVG_TRADER_SIZE_MAP`.
>
> **Manual-only (piff-philosophy, NICHT auto-written)**:
> `CATEGORY_BLACKLIST_MAP`, `FOLLOWED_TRADERS`. Auto-pause/throttle/kick
> sind ebenfalls disabled. Brain und Auto-Tuner berechnen Empfehlungen
> und loggen sie (als `BLACKLIST_RECOMMENDED` in `brain_decisions` und
> als `[TUNER] Would blacklist (DISABLED, manual): ...` im log) aber
> schreiben nicht in settings.env. User manage diese Felder manuell.
>
> Initialwerte bleiben in `settings.example.env` als Fallback bis Brain
> echte Daten hat. Nach einem `settings.env` Update muss `polybot`
> restartet werden damit der laufende Prozess die neuen Werte liest.

### Verified P&L (Datenqualitaet)

Die Brain-Entscheidungen basieren auf VERIFIZIERTEN P&L-Daten wenn
verfuegbar — `usdc_received - actual_size` aus echten Wallet-Receipts
statt der Formel-basierten DB-`pnl_realized` (die durch Drag/Fees um
~10.3% vom Wallet-Wert abweichen kann).

`get_trader_rolling_pnl()` returnt verified-only Stats wenn ein Trader
>= 10 Trades mit `usdc_received` UND `actual_size` im Zeitfenster hat.
Sonst Fallback auf alle Trades (less accurate). Der Source-Mode steht
in der return dict (`source: verified_only` oder `all_trades_fallback`).

Ohne diesen Fix wuerde KING7777777 als WEAK-Tier eingestuft (DB sagt
$+7), obwohl seine 11 verifizierten Trades $+48.62 mit 81.8% WR zeigen
(STAR-Tier).

### Trade Scorer (vor jedem Trade)

Jeder Trade bekommt einen Score von 0-100 bevor er ausgefuehrt wird:

| Komponente | Gewicht | Was wird gemessen |
|------------|---------|-------------------|
| Trader Edge | 30% | 7-Tage Rolling Winrate + PnL des Traders |
| Category WR | 20% | Winrate des Traders in dieser Kategorie (CS, LoL, NHL...) |
| Price Signal | 15% | Ist der Preis im Sweet-Spot (30-65c)? |
| Conviction | 15% | Wie gross ist der Trade vs. Trader-Durchschnitt? |
| Market Quality | 10% | Spread + Zeit bis Event |
| Correlation | 10% | Haben wir schon Positionen im selben Event? |

| Score | Aktion |
|-------|--------|
| 0-39 | **BLOCK** — Trade wird nicht ausgefuehrt |
| 40-59 | **QUEUE** — Wartet laenger in Pending-Buy |
| 60-79 | **EXECUTE** — Normal ausfuehren |
| 80-100 | **BOOST** — Groesserer Einsatz (Kelly Multiplier) |

Gewichte und Schwellenwerte werden von der Brain Engine automatisch optimiert.

### Auto-Tuner Tier System

Der Auto-Tuner klassifiziert jeden Trader alle 2h in 5 Tiers basierend
auf 7d/30d P&L + Winrate (verified-only wenn moeglich):

| Tier | Kriterien | BET_SIZE | EXPOSURE | TAKE_PROFIT | MAX_COPIES | HEDGE_WAIT |
|------|-----------|----------|----------|-------------|------------|------------|
| **STAR** | 7d PnL > +$5, WR > 55% | 7% | 40% | 3.0x | 3 | 30s |
| **SOLID** | 7d PnL > $0, WR > 50% | 5% | 25% | 2.5x | 2 | 45s |
| **NEUTRAL** | 7d PnL > -$5, WR > 45% | 3% | 10% | 2.0x | 1 | 60s |
| **WEAK** | 7d PnL > -$10 | 2% | 3% | 1.5x | 1 | 90s |
| **TERRIBLE** | 7d PnL < -$10 | 1% | 0.5% | 1.0x | 1 | 120s |

TERRIBLE-Tier setzt zusaetzlich `MIN_CONVICTION_RATIO=3.0` (kopiert nur
extreme Conviction-Trades). Tier-Aenderungen werden direkt in
`settings.env` geschrieben — Polybot-Restart noetig damit sie greifen.

### Brain Engine (alle 2 Stunden)

```
1. Verluste klassifizieren
   → BAD_TRADER (Trader insgesamt negativ)
   → BAD_CATEGORY (Trader gut, Kategorie schlecht)
   → BAD_PRICE (Entry-Preis ausserhalb Sweet-Spot)

2. What-If Analyse
   → "Wie waere die PnL ohne BAD_CATEGORY Trades?"
   → Groessten Hebel identifizieren

3. Auto-Actions ausfuehren
   → PAUSE_TRADER (7d PnL < -$10 oder 5+ Verluste)
   → BOOST_TRADER (7d WR > 60% und PnL > +$5)
   → BLACKLIST_CATEGORY (Kategorie-WR < 40%)
   → TIGHTEN_FILTER (Price-Range verschaerfen)
   → ADJUST_SCORE_THRESHOLD (Scorer optimieren)

4. Autonomous Trading bewerten
   → Paper-Performance tracken
   → Bei 30+ Trades, >55% WR, PnL+ → automatisch Live schalten

5. Trader Lifecycle pruefen
   → Neue Trader promoten, schlechte pausieren/kicken
```

Sicherheitsnetz: Mindestens 2 Live-Trader bleiben immer aktiv.

### Trader Lifecycle (automatisch)

```
DISCOVERED → OBSERVING (48h) → PAPER_FOLLOW (7-14d) → LIVE_FOLLOW
                                       ↑                    ↓
                                       └──── PAUSED (24-72h) ←── Brain Engine
                                                    ↓
                                              KICKED (permanent)
```

| Uebergang | Kriterien |
|-----------|-----------|
| OBSERVING → PAPER | Nach 48h automatisch |
| PAPER → LIVE | 15+ Trades, >52% WR, PnL positiv |
| LIVE → PAUSED | 7d PnL < -$10 oder 5+ Verluste in Folge |
| PAUSED → PAPER | Nach Pause-Ablauf (Rehabilitation) |
| PAUSED → KICKED | 2x pausiert oder 30d PnL < -$30 |

### Dashboard Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /api/equity-curve` | Taegliche Portfolio-Kurve |
| `GET /api/brain/decisions` | Alle Brain-Engine Entscheidungen (inkl. `BLACKLIST_RECOMMENDED` disabled-auto-writes) |
| `GET /api/brain/scores` | Score-Performance nach Range |
| `GET /api/brain/lifecycle` | Trader gruppiert nach Lifecycle-Status |
| `GET /api/brain/filter-precision` | **Filter Precision Audit** (neu 2026-04-14): pro Filter-Reason precision + verified $ PnL + LOOSEN/KEEP/REVIEW Empfehlung |
| `GET /api/upgrade/ml-info` | ML Training History, filtert `model_name='ml_copy'` |
| `GET /api/upgrade/status` | Live Status inkl. `ml_model.samples_available` (live eligible count) |

### Neue DB-Tabellen

| Tabelle | Inhalt |
|---------|--------|
| `brain_decisions` | Jede Entscheidung mit Grund und erwartetem Impact. Enthaelt `BLACKLIST_RECOMMENDED` Rows fuer disabled auto-actions |
| `trade_scores` | Score + 6 Komponenten fuer jeden Trade |
| `trader_lifecycle` | Status-History pro Trader mit Timestamps |
| `autonomous_performance` | Taegliche Paper/Live Performance |
| `ml_training_log` (2026-04-14 erweitert) | Training snapshots mit `train_accuracy`, `copy_only_accuracy`, `baseline_accuracy`, `train_n`, `test_n`, `model_name` (ml_copy|ml_block) + Index |

---

## Two-Model ML System (2026-04-14)

Der ML-Scorer wurde in zwei spezialisierte Modelle gesplittet:

### `ml_copy.pkl` — Live-Entscheidungs-Modell

Trainiert **nur auf `copy_trades`** (echte ausgefuehrte Trades). Labels: `pnl_realized > 0`. Sample-Weighting: `clamp(|pnl_realized|, 0.1, 5.0)` — ein $5-Verlust zaehlt 50x so viel wie ein $0.10-Gewinn, richtig fuer asymmetric Polymarket-Payoffs.

Wird vom `trade_scorer` via `predict_copy(trade_data)` aufgerufen. `predict()` bleibt als Alias — `trade_scorer.py` braucht Null Aenderungen.

**Self-disabling edge gate**: Wenn `get_model_health('ml_copy').edge_vs_baseline < 0`, wird die `±15` Score-Adjustment im trade_scorer NICHT angewendet. Die `components["ml_prediction"]` Prediction wird trotzdem fuer die UI gesetzt — der User sieht was das Modell denkt, aber Trades werden nicht durch ein unterperformendes Modell beeinflusst. Sobald copy_only_accuracy die Baseline schlaegt, aktiviert sich das Adjustment automatisch wieder.

### `ml_block.pkl` — Filter-Audit-Modell

Trainiert **nur auf `blocked_trades`** wo `would_have_won IS NOT NULL`. Labels: `would_have_won` (binary). Wird **NICHT** vom `trade_scorer` aufgerufen. Einziger Consumer: `bot/filter_audit.py`.

### Training + Schedule

`train_model()` wrapper ruft `train_copy_model()` + `train_block_model()` auf. Laeuft alle 6h (`interval hours=6` in main.py Scheduler). Beide Modelle loggen separat in `ml_training_log` mit unterschiedlichem `model_name`.

### Verified Trader Stats (decoupled from PERFORMANCE_SINCE)

`_load_trader_stats()` in ml_scorer.py liest direkt aus `copy_trades` mit verified filter (`usdc_received + actual_size IS NOT NULL`), statt aus der `trader_performance` cache-Tabelle. Entkoppelt den ML predict-Pfad vom Dashboard-Reset-Marker `PERFORMANCE_SINCE` — das Modell sieht die volle verified Historie unabhaengig davon wo der User seine Display-Metric resettet.

---

## Filter Precision Audit (2026-04-14)

Neues Panel auf der Brain-Seite unter der ML Health Card. Misst **pro Filter-Reason** ob die Regel echte Winners blockt oder korrekt Verlierer aussortiert.

### Wie es funktioniert

1. `ml_block.pkl` wird geladen
2. Alle `blocked_trades WHERE would_have_won IS NOT NULL` werden geholt
3. **Stale-Row Filter**: Fuer `category_blacklist` Rows wird geprueft ob die (trader, category) Combo noch in der aktuellen `CATEGORY_BLACKLIST_MAP` steht. Historische Rows zu inzwischen gelockerten Regeln werden gedropped — der Audit reflektiert die aktuelle Policy, nicht akkumulierte Historie. Robust text search checkt ob ANY der enforced category keywords im market_question match.
4. **80/20 chronologische Split**: Precision wird nur auf dem Test-Slice berechnet, nicht auf Train-Rows (sonst 100% durch Memorization)
5. Pro Bucket: `n / actual_win_rate / confident_n (ml_block proba ≥ 0.7) / confident_wins / precision_at_conf`
6. **Magnitude-aware Override** fuer category_blacklist: Aggregierter verified $PnL aus `copy_trades` history pro (trader, cat) Combo ueberschreibt die WR-basierte Empfehlung. Bei Polymarket-asymmetric-payoffs kann 51% WR trotzdem ein Net-Loser sein.

### Recommendation Logic

```
n < 100                  → INSUFFICIENT
verified_pnl ≤ −$5       → KEEP (ground truth loses money, unabhaengig von WR)
verified_pnl ≥ +$5       → LOOSEN (ground truth winning)
sonst fallback auf WR:
  precision ≥ 70%        → LOOSEN
  precision ≤ 30%        → KEEP
  dazwischen             → REVIEW
```

Dashboard zeigt inline im Badge: `KEEP −$6` oder `LOOSEN +$67`. Rechter Pill im Panel-Header zeigt `ml_block: n=16420 · edge +39.5pp · trained 13:30` als Vertrauens-Indikator fuer die Empfehlungen.

### Files

- `bot/filter_audit.py` — neue Datei, `compute_filter_precision()` + `_verified_pnl_per_trader_category()` + `_current_category_blacklist_map()`
- `bot/ml_scorer.py::_build_block_training_data(verified_only=False, with_metas=True)` — liefert optional 5-Tuple mit per-row metadata
- `dashboard/app.py::api_filter_precision` — neuer Endpoint
- `dashboard/templates/brain.html` — Panel HTML + CSS + JS renderer

---


## AI Analysis Pipeline

Der Bot hat ein eingebautes System das lernt welche Filter zu aggressiv oder zu lasch sind.

### So funktioniert es

```
Alle 5s:  Bot scannt → BUY oder SKIP (geblockt + Grund in DB gespeichert)
Alle 30m: Outcome Tracker → checkt was geblockte Trades verdient haetten
Alle 6h:  Claude analysiert → empfiehlt Parameter-Aenderungen (optional)
```

### 1. Blocked Trade Logging (immer aktiv)

Jeder Trade der von einem Filter geblockt wird, wird in die `blocked_trades` Tabelle geschrieben:
- Welcher Trader, welcher Markt, welcher Preis
- Welcher Filter hat geblockt (category_blacklist, exposure_limit, price_range, etc.)
- Welcher Buy-Pfad (activity, diff, event_wait, hedge_wait)

### 2. Outcome Tracker (alle 30 Minuten)

Checkt per Polymarket API was aus den geblockten Trades geworden ist:
- Resolved Maerkte: sofortige Auswertung (Gewinner/Verlierer)
- Live Maerkte: tentative Auswertung nach 4 Stunden

### 3. Claude AI Analyzer (alle 6 Stunden, optional)

Braucht `ANTHROPIC_API_KEY` in `secrets.env`. Schickt geblockte + ausgefuehrte Trades an Claude und bekommt:
- Welche Filter zu aggressiv sind (blocken profitable Trades)
- Welche Filter zu lasch sind (lassen Verlierer durch)
- Konkrete Parameter-Vorschlaege mit Confidence-Score

### API Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /api/ai/blocked-stats?hours=48` | Statistiken: wie viele geblockt, pro Grund, Win-% |
| `GET /api/ai/blocked-trades?hours=48` | Rohdaten aller geblockten Trades |
| `GET /api/ai/latest` | Neueste Claude-Analyse mit Empfehlungen |
| `POST /api/ai/analyze` | Manuell Analyse triggern (braucht Auth + API Key) |

---

## Installation

### 1. Code herunterladen

```bash
git clone https://github.com/Super-Sauna-Club/polymarket-copy-bot.git
cd polymarket-copy-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` enthaelt jetzt auch `numpy` und `scikit-learn` —
diese werden vom ML Scorer (RandomForest auf historischen Trades)
gebraucht. Die Installation laedt zusaetzlich `scipy`, `joblib` und
`threadpoolctl` als Abhaengigkeiten von `scikit-learn`.

### 2. Konfiguration

Es gibt **zwei** Config-Dateien:

| Datei | Inhalt | Im Git? |
|-------|--------|---------|
| `secrets.env` | Private Keys, API-Keys, Passwoerter | **NEIN** (gitignored) |
| `settings.env` | Bot-Einstellungen (Trader, Groessen, Filter) | **NEIN** (gitignored) |
| `secrets.example.env` | Vorlage fuer secrets.env | Ja |
| `settings.example.env` | Vorlage fuer settings.env | Ja |

```bash
cp secrets.example.env secrets.env      # Deine Keys eintragen
cp settings.example.env settings.env    # Bot-Settings anpassen
```

**KEIN `.env` Fallback.** Beide Dateien muessen existieren.

#### secrets.env (Pflicht)

```env
POLYMARKET_PRIVATE_KEY=dein_private_key
POLYMARKET_FUNDER=deine_proxy_wallet_adresse
BUILDER_KEY=dein_key
BUILDER_SECRET=dein_secret
BUILDER_PASSPHRASE=dein_passphrase
DASHBOARD_SECRET=dein_passwort
```

#### settings.env (Anpassen)

Kopiere `settings.example.env` und passe an. Alle Einstellungen sind in der Datei dokumentiert.

### 3. Starten

```bash
# ZUERST im Paper-Modus testen (kein echtes Geld)
# LIVE_MODE=false in settings.env setzen
python main.py

# Wenn alles funktioniert: LIVE_MODE=true
python main.py
```

Dashboard: `http://localhost:8090`

### 4. Als Service einrichten (Server)

```bash
sudo nano /etc/systemd/system/polybot.service
```

```ini
[Unit]
Description=Polymarket Copy Trading Bot
After=network.target

[Service]
Type=simple
User=dein_user
WorkingDirectory=/pfad/zum/polymarket-copy-bot
ExecStart=/pfad/zum/polymarket-copy-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable polybot
sudo systemctl start polybot
```

Optional: P&L-Monitor als separaten Service einrichten (`pnl-monitor.service`).

### 5. Auto-Redeem

```bash
# Alle resolved Positionen on-chain einloesen via Builder Relayer
python redeem_positions.py
```

Das Script fragt die Polymarket API nach redeemable Positions und schickt
Batch-Transaktionen. Kann als Cron-Job alle 15 Minuten laufen. POL/MATIC
Gas wird durch den Relayer abgedeckt (kein MATIC im Wallet noetig).

### 6. Historisches `usdc_received` Backfillen (falls NULL Rows existieren)

```bash
# Dry-run: zeigt was geaendert wuerde, schreibt nichts
python backfill_usdc_received.py

# Apply: schreibt verified usdc_received in NULL rows
python backfill_usdc_received.py --apply
```

Nur noetig wenn es historische `copy_trades` rows mit `status='closed' AND
usdc_received IS NULL` gibt (vor dem 2026-04-14 Close-Path-Fix war das der
Normalfall). Idempotent — kann beliebig oft laufen. Das Tool matched die
NULL-Rows 1:1 zu echten Sell-Events aus Polymarket's Activity-API.
Nach dem Close-Path-Fix werden keine neuen NULL-Rows mehr erzeugt —
das Tool ist nur fuer pre-fix Historie relevant.

---

## Alle Einstellungen

Alle Einstellungen kommen in `settings.env`. Siehe `settings.example.env` fuer die komplette Liste mit Erklaerungen und aktuellen Empfehlungen.

### Kern

| Einstellung | Standard | Erklaerung |
|-------------|----------|------------|
| `LIVE_MODE` | false | false = nur tracken, true = echtes Geld |
| `STARTING_BALANCE` | 320 | Einzahlung fuer P&L-Berechnung |
| `COPY_SCAN_INTERVAL` | 5 | Alle X Sekunden nach neuen Trades schauen |

### Wettgroesse

| Einstellung | Standard | Erklaerung |
|-------------|----------|------------|
| `BET_SIZE_PCT` | 0.04 | Basis-Wette = 4% vom Portfolio |
| `BET_SIZE_MAP` | | Pro Trader eigene Basis (z.B. `KING7777777:0.08`) |
| `MAX_POSITION_SIZE` | 30 | Maximum $30 pro Position |
| `MIN_TRADE_SIZE` | 1.0 | Minimum $1 pro Wette |

### Trade-Filter

| Einstellung | Standard | Erklaerung |
|-------------|----------|------------|
| `MIN_TRADER_USD` | 5 | Trader muss min $5 setzen damit kopiert wird |
| `MIN_TRADER_USD_MAP` | | Pro Trader (z.B. `sovereign2013:750`) |
| `MIN_ENTRY_PRICE` | 0.20 | Unter 20c nicht kaufen |
| `MAX_ENTRY_PRICE` | 0.80 | Ueber 80c nicht kaufen (Drag frisst den Gewinn) |
| `MAX_COPIES_PER_MARKET` | 1 | 1 Kopie pro Markt. Zaehlt auch kuerzlich geschlossene Trades (Fenster = max(NO_REBUY_MINUTES, 30min)) |
| `NO_REBUY_MINUTES` | 120 | Sperre nach Close fuer selben Markt (0=aus) |
| `CATEGORY_BLACKLIST_MAP` | | Kategorien pro Trader blocken |
| `MAX_PER_EVENT` | 15 | Max $15 pro Event |
| `MAX_PER_MATCH` | 15 | Max $15 pro Match (Map 1 + Map 2 + BO3 gruppiert) |

### Exposure

| Einstellung | Standard | Erklaerung |
|-------------|----------|------------|
| `MAX_EXPOSURE_PER_TRADER` | 0.33 | Max 33% vom Portfolio pro Trader |
| `TRADER_EXPOSURE_MAP` | | Pro Trader (z.B. `KING7777777:0.65,xsaghav:0.03`) |
| `CASH_FLOOR` | 0 | Unter diesem Betrag nicht mehr kaufen |
| `CASH_RECOVERY` | 6 | Recovery-Schwelle ueber Floor |

### Order-Ausfuehrung

| Einstellung | Standard | Erklaerung |
|-------------|----------|------------|
| `BUY_SLIPPAGE_LEVELS` | 0.02,0.05,0.08 | Kauf-Retry Slippage-Stufen |
| `SELL_SLIPPAGE_LEVELS` | 0.01,0.03,0.05 | Verkauf-Retry Slippage-Stufen |
| `SELL_VERIFY_THRESHOLD` | 0.05 | Max verbleibende Shares (0.05 = 95% muessen verkauft sein) |
| `AUTO_SELL_PRICE` | 0.96 | Gewonnene Positionen ab 96c verkaufen |
| `AUTO_CLOSE_LOST_PRICE` | 0.00 | Unter diesem Preis als verloren markieren (0=aus) |

Alle weiteren Einstellungen sind in `settings.example.env` dokumentiert.

---

## Architektur

```
main.py                      → Scheduler + Flask + Startup, AUTO-CLOSE-won/lost paths (atomic 2026-04-14)
├── bot/copy_trader.py       → Kern: Scan, Filter, Hedge-Wait, Fast-Sell, Sizing, Buy-Lock.
│                              7 close paths (FAST-SELL, STOP-LOSS x2, TRAILING-STOP,
│                              TAKE-PROFIT, trader-closed-it, miss-close) schreiben jetzt
│                              atomar mit usdc_received via _usdc_from_sell + _real_pnl_from_sell
├── bot/order_executor.py    → CLOB Orders (Kauf/Verkauf) mit Retry + Fill-Verification
├── bot/wallet_scanner.py    → Activity Feed, Positions API
├── bot/ws_price_tracker.py  → WebSocket Echtzeit-Preise
├── bot/ai_report.py         → Performance-Report Generator
├── bot/ai_analyzer.py       → Claude AI Analyse: geblockte vs ausgefuehrte Trades → Empfehlungen
├── bot/outcome_tracker.py   → Checkt was geblockte Trades verdient haetten (Polymarket API)
├── bot/trade_scorer.py      → Score 0-100 vor jeder Trade-Ausfuehrung (6 Komponenten) + ML edge gate
├── bot/ml_scorer.py         → Two-model ML: ml_copy (Live-Decisions) + ml_block (Filter-Audit).
│                              train_copy_model + train_block_model + predict_copy + predict_block.
│                              predict() bleibt als Alias fuer ml_copy
├── bot/filter_audit.py      → **NEU 2026-04-14**: Per-Filter-Reason precision audit, magnitude-
│                              aware via verified $PnL override. compute_filter_precision()
├── bot/brain.py             → Brain Engine: Selbst-Diagnose, Auto-Actions, Score-Optimierung (alle 2h).
│                              BAD_CATEGORY auto-blacklist ist DISABLED (piff-philosophy),
│                              loggt nur BLACKLIST_RECOMMENDED
├── bot/trader_lifecycle.py  → Trader Lifecycle: Auto Discover/Observe/Paper/Live/Pause/Kick
├── bot/autonomous_signals.py → Eigene Trades: Momentum + AI Divergence (Paper/Live)
├── bot/auto_tuner.py        → Trader-Tiers (star/solid/neutral/weak/terrible) → Settings.
│                              CATEGORY_BLACKLIST_MAP auto-merge ist DISABLED (2026-04-14)
├── bot/auto_discovery.py    → Findet neue Trader via Leaderboard + PolymarketScan
├── bot/kelly.py             → Kelly Criterion Bet Sizing + Win-Streak Boost
├── bot/smart_sell.py        → Verkauft wenn Trader Position verlaesst
├── bot/clv_tracker.py       → Customer Lifetime Value Tracking
├── database/db.py           → Datenbank-Operationen (SQLite + WAL), Migration mit Verification.
│                              close_copy_trade(..., usdc_received=None) atomic
├── database/models.py       → Datenbank-Schema (inkl. blocked_trades, ai_recommendations,
│                              ml_training_log mit model_name Column)
├── config.py                → Laedt secrets.env → settings.env (kein .env Fallback)
├── monitor_pnl.py           → P&L-Accuracy-Monitor (systemd Service)
├── redeem_positions.py      → Gewinne einloesen via Builder Relayer
├── backfill_usdc_received.py → **NEU 2026-04-14**: Backfill-Tool das historische NULL
│                              usdc_received rows aus Polymarket Activity-API rekonstruiert.
│                              Idempotent. Dry-run default, --apply writes
└── dashboard/
    ├── app.py               → Flask App, SSE Stream, REST APIs (inkl. /api/ai/*, /api/brain/filter-precision)
    └── templates/
        ├── dashboard.html   → Haupt-Dashboard mit Live-Trader-Karten
        ├── brain.html       → Intelligence Dashboard, ML Health Card, Filter Precision Audit Panel
        ├── index.html       → Einstellungs-Seite
        └── history.html     → Handelshistorie
```

### 5 Buy-Pfade — Gleiche Filter ueberall

| Pfad | Beschreibung |
|------|-------------|
| Activity Scan | Hauptpfad: /trades API alle 5 Sekunden |
| Position-Diff | Fallback: findet Trades die der Activity-Feed verpasst hat |
| Event-Wait | Queued Trades fuer Events die noch nicht angefangen haben |
| Hedge-Wait | Wartet X Sekunden ob Trader Gegenseite kauft (Hedge-Erkennung) |
| Pending-Buy | Wartet bis Preis ueber Threshold steigt (standardmaessig aus) |

Alle Pfade haben dieselben Filter, Size-Caps und den Buy-Lock.

---

## Risiken und Kosten

### Drag (der groesste Feind)

Polymarket Fees sind 0-10% je nach Markt. Die meisten Esports-Maerkte haben **10% Fee**. Plus Slippage. Pro Roundtrip (Kauf + Verkauf) verlierst du **12-20%** des investierten Betrags an Kosten — egal ob der Trade gewinnt oder verliert.

**Beispiel:** Du investierst $10 bei 50c. Wenn du gewinnst, bekommst du ~$18 statt $20 (10% Fee). Wenn du verlierst, sind die $10 weg plus du hast beim Kauf schon 2c Slippage gezahlt.

**Konsequenz:** Ein Trader braucht **deutlich ueber 55% Win-Rate** um nach Drag profitabel zu sein. Bei 50/50 verlierst du garantiert durch die Gebuehren.

### Weitere Risiken

- **Slippage** — 5 Sekunden Verzoegerung heisst du bekommst einen schlechteren Preis als der Trader
- **Verluste** — Auch die besten Trader verlieren manchmal. Vergangene Performance garantiert nichts
- **Binaere Ergebnisse** — Positionen gehen auf $0 oder $1. Kein "ein bisschen verloren"
- **API-Ausfaelle** — Polymarket kann down sein. Circuit Breaker schuetzt teilweise
- **Skalierung** — Trader die mit $5000 profitabel sind, funktionieren nicht automatisch mit unseren $5-Kopien (Proportionen stimmen nicht)

---

## Deploy (Server ohne Git)

Der Server hat keinen GitHub-Account. Deploy per SCP:

```bash
scp <datei> walter@10.0.0.20:/home/walter/polymarketscanner/<datei>
ssh walter@10.0.0.20 "sudo systemctl restart polybot"
```

Fuer Dateien in Unterverzeichnissen den vollen Pfad angeben:

```bash
scp bot/copy_trader.py walter@10.0.0.20:/home/walter/polymarketscanner/bot/
scp dashboard/app.py walter@10.0.0.20:/home/walter/polymarketscanner/dashboard/
```

Immer `settings.example.env` mit dem Server syncen damit neue Einstellungen dokumentiert sind.

---

## Tech Stack

- Python 3.12+
- Flask (Dashboard + SSE)
- SQLite mit WAL-Modus
- py-clob-client (Polymarket CLOB API)
- poly-web3 (Builder Relayer fuer Redeem)
- WebSocket (Echtzeit-Preise)
- Chart.js (Equity-Kurve)
- APScheduler (Job-Scheduler)
- scikit-learn + numpy (ML Scorer, RandomForest auf historischen Trades)
- anthropic (Claude AI Analyzer, optional)

---

## Lizenz

MIT
