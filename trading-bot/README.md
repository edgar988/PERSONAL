# AI-Infra Trading Bot 🤖📈

A personal swing-trading assistant for a Robinhood account, tilted toward the
AI-infrastructure ("picks and shovels") theme. Built in **stages** so it earns
autonomy instead of being handed the keys on day one.

> ⚠️ **Reality check.** No system reliably guarantees profit. This bot trades
> with *discipline* (consistent rules, hard risk limits, human approval) — that
> is the goal, not a promise of returns. You can lose money. Start conservative.

---

## The staged plan

| Stage | What it does | Risk |
|-------|--------------|------|
| **1 — Watcher** ← *you are here* | Watches the watchlist, texts you buy/sell signals via Telegram. **Places ZERO trades.** | None |
| **2 — Approve-first** | Proposes a trade → you tap ✅/❌ on your phone → it executes via Robinhood. | Capped, you approve every trade |
| **3 — Auto-on-a-leash** | Trades on its own inside hard limits. Only after Stage 2 earns trust. | Capped, automated |

Stage 1 cannot touch your Robinhood account. It only reads prices and sends you
messages. Run it for a couple of weeks and judge whether its calls are any good
*before* a single real dollar is at stake.

---

## The watchlist (16 names)

Diversified across sectors, leaning into the AI buildout:

- **Ballast:** SPY, COST, XOM, JPM
- **Mega-cap tech:** AAPL, MSFT, GOOGL
- **AI chips:** NVDA, AMD
- **AI infra — power/grid:** GEV, ETN, PWR
- **AI infra — cooling:** VRT
- **AI infra — metals (wire/steel/cores):** FCX, CLF, NUE

Edit the list any time in `config.py`.

## The strategy (transparent — no black box)

Every signal is explainable. For each stock the Watcher checks:

1. **Trend filter** — is price above its 50-day average? (only consider uptrends)
2. **Entry trigger** — did the 20-day average just cross above the 50-day
   (fresh momentum), **or** did RSI just climb back out of oversold (a bounce)?
3. **Caution** — is RSI above 70 (stretched / take-profit zone)?

Tune all of this in `config.py`.

---

## Setup

### 1. Install Python deps
```bash
pip install -r requirements.txt
```

### 2. Set your Telegram secrets
Copy `.env.example` to `.env` and fill in your bot token + chat id:
```bash
cp .env.example .env
# then edit .env
```
`.env` is git-ignored — your token never gets committed.

### 3. Run it
```bash
# load .env into the environment, then run
python watcher.py
```
You should get a Telegram digest within a few seconds.

---

## Running it 24/7 on a VPS (Linux)

```bash
# one-time
sudo apt update && sudo apt install -y python3-pip
git clone <this-repo-url> && cd personal/trading-bot
pip install -r requirements.txt
cp .env.example .env   # edit in your token + chat id

# schedule it — run every weekday at 4:30pm ET (after market close = 21:30 UTC)
crontab -e
# add this line:
30 21 * * 1-5  cd /home/YOU/personal/trading-bot && set -a && . ./.env && set +a && /usr/bin/python3 watcher.py >> watcher.log 2>&1
```

---

## Roadmap

- [x] **Stage 1** — Watcher (signals to Telegram, no trades)
- [ ] **Stage 2** — Approve-first execution via the Robinhood MCP + ✅/❌ buttons
- [ ] **Stage 3** — Automated trading inside hard caps + daily loss stop

## Safety limits (wired in `config.py`, enforced from Stage 2)

- Max **$500** per position
- Max **$3,000** deployed at once (keeps ~$2k cash dry)
- **$150** daily loss stop
- Suggested exit ~**8%** below entry on every buy
