"""
Trading bot configuration.

NO SECRETS IN THIS FILE. Telegram/Anthropic credentials come from the .env
file (see .env.example). This file is safe to commit.
"""

# -- Watchlist ---------------------------------------------------------------
WATCHLIST = [
    # Ballast (steady, lower-risk)
    "SPY",    # S&P 500 ETF -- the whole market, your anchor
    "COST",   # Costco -- consumer defensive stability
    "XOM",    # ExxonMobil -- energy
    "JPM",    # JPMorgan -- financials
    # Mega-cap tech
    "AAPL",   # Apple
    "MSFT",   # Microsoft -- AI + cloud
    "GOOGL",  # Alphabet
    # AI chips
    "NVDA",   # Nvidia -- AI leader
    "AMD",    # AMD -- volatile semi
    # AI infrastructure -- power / grid
    "GEV",    # GE Vernova -- turbines + grid transformers
    "ETN",    # Eaton -- switchgear, power distribution
    "PWR",    # Quanta Services -- builds transmission lines
    # AI infrastructure -- cooling
    "VRT",    # Vertiv -- data-center chillers
    # AI infrastructure -- metals (wire / steel / cores)
    "FCX",    # Freeport-McMoRan -- copper
    "CLF",    # Cleveland-Cliffs -- transformer-core steel
    "NUE",    # Nucor -- steel + data-center racking
    # Dividend-income sleeve
    "SCHD",   # Schwab US Dividend Equity ETF
    "JEPI",   # JPMorgan Equity Premium Income -- covered-call income ETF
    "O",      # Realty Income -- pays MONTHLY
]

DIVIDEND_TICKERS = ["SCHD", "JEPI", "O"]

# The AI-buildout theme -- concentration-capped as a group (see risk.py).
AI_THEME_TICKERS = ["NVDA", "AMD", "GEV", "ETN", "PWR", "VRT", "FCX", "CLF", "NUE"]
THEME_MAX_FRACTION = 0.6   # AI theme may use at most 60% of the deployed cap

# -- Risk caps (the brakes) --------------------------------------------------
ACCOUNT_SIZE_USD       = 5000    # your Robinhood starting balance
MAX_PER_POSITION_USD   = 500     # ceiling for any single buy
MIN_POSITION_USD       = 150     # floor after volatility scaling
MAX_TOTAL_DEPLOYED_USD = 3000    # most ever in play at once
DAILY_LOSS_STOP_USD    = 150     # down this much in a day -> buys halt
STOP_LOSS_PCT          = 0.08    # trailing: propose exit 8% below the peak
TAKE_PROFIT_PCT        = 0.15    # up 15% from avg cost -> take-profit proposal

# -- Volatility-based position sizing -----------------------------------------
# Position $ = MAX_PER_POSITION * min(1, ATR_BASELINE_PCT / stock's ATR%).
# A stock that moves 2%/day gets the full $500; one that moves 4%/day gets
# ~$250 -- equal risk per position instead of equal dollars.
ATR_PERIOD       = 14    # days for the Average True Range
ATR_BASELINE_PCT = 2.0   # "normal" daily movement earning full size

# -- Strategy parameters -----------------------------------------------------
FAST_SMA   = 20
SLOW_SMA   = 50
RSI_PERIOD = 14
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 70
LOOKBACK_DAYS     = 200
CROSS_RECENT_DAYS = 3

# -- Intraday scan -----------------------------------------------------------
BIG_MOVE_PCT      = 3.0   # alert on +/- this % day move
VOLUME_SPIKE_MULT = 2.5   # alert when volume >= this x its 20-day average

# -- Social buzz -------------------------------------------------------------
BUZZ_SUBREDDITS = ["wallstreetbets", "stocks", "investing"]
BUZZ_SPIKE_MULT = 3.0
BUZZ_SPIKE_MIN  = 5
