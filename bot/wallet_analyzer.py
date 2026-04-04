import json
import logging
import time

import config
from bot.wallet_scanner import fetch_wallet_positions, fetch_wallet_trades
from bot.massive_data import get_market_context

logger = logging.getLogger(__name__)

WALLET_ANALYSIS_PROMPT = """Du bist ein erfahrener Prediction-Market-Analyst. Bewerte diesen Polymarket-Trader/Wallet:

WALLET: {address}
USERNAME: {username}
RANG: #{rank}
GESAMTVOLUMEN: ${volume}
PROFIT/LOSS: ${pnl}
MÄRKTE GEHANDELT: {markets_traded}

TRADE-HISTORIE:
- Trades gesamt: {total_trades}
- Gewonnen: {wins}
- Verloren: {losses}
- Win-Rate: {win_rate}%
- Durchschnittl. Trade-Größe: ${avg_trade_size}

AKTUELLE OFFENE POSITIONEN:
{positions_text}

{market_data}

AUFGABE:
1. Bewerte die Qualität dieses Traders (Konsistenz, Risikomanagement, Strategie)
2. Schätze wie gut er als Copy-Trade-Ziel geeignet ist (1-10)
3. Identifiziere Stärken und Schwächen
4. Gib eine kurze Empfehlung
5. WICHTIG: Bewerte kritisch! Ein Trader mit negativem All-Time PnL ist KEIN guter Copy-Trader.

Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
{{
  "score": <int 1-10>,
  "strategy_type": "<z.B. Sports, Geopolitik, Crypto, Mixed>",
  "strengths": "<kurz, max 2 Sätze>",
  "weaknesses": "<kurz, max 2 Sätze>",
  "recommendation": "<COPY|WATCH|SKIP>",
  "reasoning": "<kurze Begründung, max 3 Sätze>"
}}"""


def _call_zai(messages: list[dict]) -> str | None:
    """Call Z.ai GLM API (OpenAI-compatible)."""
    if not config.ZAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.ZAI_API_KEY, base_url=config.ZAI_BASE_URL)
        chat = client.chat.completions.create(
            model=config.ZAI_MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Z.ai API error: %s — falling back to Groq", e)
        return None


def _call_groq(messages: list[dict]) -> str | None:
    """Call Groq API (Llama) as fallback."""
    if not config.GROQ_API_KEY:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=config.GROQ_API_KEY)
        chat = client.chat.completions.create(
            model=config.AI_MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        return chat.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq API error: %s", e)
        return None


def _call_claude(messages: list[dict]) -> str | None:
    """Call Anthropic Claude API as 3rd fallback."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        system_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_msgs.append(m)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=500,
            system=system_msg,
            messages=user_msgs,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Claude API error: %s", e)
        return None


def _call_gemini(messages: list[dict]) -> str | None:
    """Call Google Gemini API as 4th fallback (kostenlos)."""
    if not config.GEMINI_API_KEY:
        return None
    try:
        import requests
        parts = []
        for m in messages:
            parts.append({"text": m["content"]})
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}",
            json={"contents": [{"parts": parts}]},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return None


def _fallback_score(wallet: dict, history: dict, positions: list) -> dict:
    """Score a wallet based on raw stats when AI is unavailable."""
    address = wallet["address"]
    pnl = wallet.get("pnl", 0)
    volume = wallet.get("volume", 0)
    win_rate = history["win_rate"]
    total_trades = history["total_trades"]

    # Simple scoring: PnL weight + win rate + trade count
    score = 0
    if pnl > 1_000_000: score += 3
    elif pnl > 500_000: score += 2
    elif pnl > 100_000: score += 1

    if win_rate >= 70: score += 3
    elif win_rate >= 55: score += 2
    elif win_rate >= 40: score += 1

    if total_trades >= 50: score += 2
    elif total_trades >= 20: score += 1

    # Penalty: too few trades = unreliable
    if total_trades < 5: score = max(score - 2, 1)

    score = max(1, min(10, score))
    rec = "COPY" if score >= 7 else "WATCH" if score >= 4 else "SKIP"

    logger.info("[Fallback] Wallet '%s' (%s): Score=%d/10 | Rec=%s | PnL=$%.2f | WR=%.0f%%",
                wallet.get("username", address[:10]), address[:10], score, rec, pnl, win_rate)

    return {
        "address": address,
        "username": wallet.get("username", ""),
        "rank": wallet.get("rank", 0),
        "volume": volume,
        "pnl": pnl,
        "markets_traded": wallet.get("markets_traded", 0),
        "score": score,
        "strategy_type": "Unknown",
        "strengths": f"PnL: ${pnl:,.0f}, Win Rate: {win_rate}%",
        "weaknesses": "AI-Analyse nicht verfügbar (Fallback-Score)",
        "recommendation": rec,
        "reasoning": f"Stats-basierter Score: PnL ${pnl:,.0f}, Win Rate {win_rate}%, {total_trades} Trades",
        "win_rate": win_rate,
        "total_trades": total_trades,
        "positions": positions[:5] if positions else [],
        "profile_url": wallet.get("profile_url", ""),
        "source": wallet.get("source", "leaderboard"),
    }


def analyze_wallet(wallet: dict) -> dict | None:
    """Analyze a wallet using Z.ai (primary) or Groq (fallback)."""
    address = wallet["address"]

    # Fetch additional data
    positions = fetch_wallet_positions(address)
    history = fetch_wallet_trades(address)

    # Build positions text
    if positions:
        pos_lines = []
        for p in positions[:10]:
            pos_lines.append(
                f"  - {p['side']} on '{p['market_question'][:60]}' | "
                f"Size: ${p['size']:.2f} | Entry: ${p['avg_price']:.4f} | "
                f"Current: ${p['current_price']:.4f}"
            )
        positions_text = "\n".join(pos_lines)
    else:
        positions_text = "  Keine offenen Positionen gefunden."

    market_data = get_market_context()

    prompt = WALLET_ANALYSIS_PROMPT.format(
        address=address,
        username=wallet.get("username", "Unknown"),
        rank=wallet.get("rank", "N/A"),
        volume=f"{wallet.get('volume', 0):,.0f}",
        pnl=f"{wallet.get('pnl', 0):,.2f}",
        markets_traded=wallet.get("markets_traded", 0),
        total_trades=history["total_trades"],
        wins=history["wins"],
        losses=history["losses"],
        win_rate=history["win_rate"],
        avg_trade_size=history["avg_trade_size"],
        positions_text=positions_text,
        market_data=market_data if market_data else "(Keine Marktdaten verfügbar)",
    )

    messages = [
        {"role": "system", "content": "Du antwortest IMMER nur mit validem JSON. Kein Text davor oder danach."},
        {"role": "user", "content": prompt},
    ]

    # Try Z.ai first, then Groq as fallback
    response_text = _call_zai(messages)
    ai_source = "Z.ai/GLM-5"
    if response_text is None:
        response_text = _call_groq(messages)
        ai_source = "Groq/Llama"
    if response_text is None:
        response_text = _call_claude(messages)
        ai_source = "Claude/Haiku"
    if response_text is None:
        response_text = _call_gemini(messages)
        ai_source = "Gemini/Flash-Lite"
    if response_text is None:
        logger.warning("All AI providers failed for wallet %s — using stats-based fallback.", address[:10])
        return _fallback_score(wallet, history, positions)

    try:
        # Extract JSON (handle markdown code blocks)
        if "{" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            response_text = response_text[start:end]

        result = json.loads(response_text)

        score = int(result.get("score", 0))
        score = max(1, min(10, score))

        analysis = {
            "address": address,
            "username": wallet.get("username", ""),
            "rank": wallet.get("rank", 0),
            "volume": wallet.get("volume", 0),
            "pnl": wallet.get("pnl", 0),
            "markets_traded": wallet.get("markets_traded", 0),
            "score": score,
            "strategy_type": result.get("strategy_type", "Unknown"),
            "strengths": result.get("strengths", ""),
            "weaknesses": result.get("weaknesses", ""),
            "recommendation": result.get("recommendation", "SKIP"),
            "reasoning": result.get("reasoning", ""),
            "win_rate": history["win_rate"],
            "total_trades": history["total_trades"],
            "positions": positions[:5],
            "profile_url": wallet.get("profile_url", ""),
            "source": wallet.get("source", "leaderboard"),
        }

        logger.info(
            "[%s] Wallet '%s' (%s): Score=%d/10 | Rec=%s | Type=%s | PnL=$%.2f",
            ai_source,
            wallet.get("username", address[:10]),
            address[:10],
            score,
            result.get("recommendation", "SKIP"),
            result.get("strategy_type", "?"),
            wallet.get("pnl", 0),
        )

        return analysis

    except json.JSONDecodeError as e:
        logger.error("Failed to parse AI response for wallet %s: %s", address[:10], e)
        return None


def analyze_wallets_batch(wallets: list[dict], max_analyze: int = 50) -> list[dict]:
    """Analyze a batch of wallets and return sorted results."""
    results = []

    for i, wallet in enumerate(wallets[:max_analyze]):
        logger.info("Analyzing wallet %d/%d: %s", i + 1, min(max_analyze, len(wallets)),
                     wallet.get("username") or wallet["address"][:10])

        analysis = analyze_wallet(wallet)
        if analysis:
            results.append(analysis)

        # Rate limiting
        time.sleep(2.0)

    # Sort by score (highest first), then by PnL
    results.sort(key=lambda x: (x["score"], x["pnl"]), reverse=True)

    logger.info("Analyzed %d wallets. Top score: %d/10",
                len(results), results[0]["score"] if results else 0)

    return results
