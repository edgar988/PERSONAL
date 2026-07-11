"""
Trading bot configuration.

NO SECRETS IN THIS FILE. Telegram credentials come from environment
variables / the .env file (see .env.example). This file is safe to commit.
"""

# -- Watchlist ---------------------------------------------------------------
# Liquid large-caps across sectors, tilted toward the AI-infrastructure
# "picks and shovels" theme, plus a dividend-income sleeve. Edit freely.
WATCHLIST = [
    # Ballast (steady, lower-risk)
    "SPY",    # S&P 500 ETF -- the whole market, your anchor
    "COST",   # Costco -- consumer defensive stability
    "XOM",    # ExxonMobil -- energy, 2026's leading sector
    "JPM",    # JPMorgan -- financials
    # Mega-cap tech
    "AAPL",   # Apple
    "MSFT",   # Microsoft -- AI + cloud
    "GOOGL",  # Alphabet
    # AI chips
    "NVDA",   # Nvidia -- AI leader
    "AMD",    # AMD -- volatile semi
    # AI infrastructure -- power / grid
    "GEV",    # GE Vernova -- turbines for power plants + grid transformers
    "ETN",    # Eaton -- switchgear, transformers, power distribution
    "PWR",    # Quanta Services -- builds transmission lines
    # AI infrastructure -- cooling
    "VRT",    # Vertiv -- data-center chillers + thermal management
    # AI infrastructure -- metals (wire / steel / cores)
    "FCX",    # Freeport-McMoRan -- copper (the wire)
    "CLF",    # Cleveland-Cliffs -- sole US maker of transformer-core steel
    "NUE",    # Nucor -- steel + data-center racking
    # Dividend-income sleeve
    "SCHD",   # Schwab US Dividend Equity ETF -- dividend growth
    "JEPI",   # JPMorgan Equity Premium Income -- covered-call income ETF
    "O",      # Realty Income -- pays MONTHLY
]

# The income sleeve, tracked by the dividend module.
DIVIDEND_TICKERS = ["SCHD", "JEPI", "O"]

# -- Risk caps (the brakes) --------------------------------------------------
ACCOUNT_SIZE_USD       = 5000    # your Robinhood starting balance
MAX_PER_POSITION_USD   = 500     # most the bot may put into any single stock
MAX_TOTAL_DEPLOYED_USD = 3000    # most it may ever have in play at once
DAILY_LOSS_STOP_USD    = 150     # if down this much in a day, stop trading
STOP_LOSS_PCT          = 0.08    # suggested exit ~8% below entry

# -- Strategy parameters -----------------------------------------------------
FAST_SMA   = 20     # short moving average (days)
SLOW_SMA   = 50     # long / trend moving average (days)
RSI_PERIOD = 14     # RSI lookback (days)
RSI_OVERSOLD   = 35   # below this = beaten down; a cross back up = potential entry
RSI_OVERBOUGHT = 70   # above this = stretched; caution / take-profit zone
LOOKBACK_DAYS     = 200  # how much price history to pull for the math
CROSS_RECENT_DAYS = 3    # a crossover counts as "fresh" if within this many days

# -- Intraday scan -----------------------------------------------------------
BIG_MOVE_PCT = 3.0   # alert when a ticker is up/down this % on the day

# -- Social buzz -------------------------------------------------------------
BUZZ_SUBREDDITS = ["wallstreetbets", "stocks", "investing"]
BUZZ_SPIKE_MULT = 3.0   # mentions >= 3x recent average = spike
BUZZ_SPIKE_MIN  = 5     # ...and at least this many mentions
""""""
