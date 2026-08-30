#!/usr/bin/env python3
"""One-time interactive Robinhood login. Run this ON THE VPS over SSH:

    ~/.tradingbot-venv/bin/python rh_login.py

It stores a session token under ~/.tokens/ that the approver bot and
dashboard reuse headlessly. You may be asked to approve the login in your
Robinhood phone app (device approval) -- keep your phone handy.
"""
import getpass
import os

import robin_stocks.robinhood as rh

print("Robinhood one-time login (credentials are NOT stored -- only a session token).")
username = input("Robinhood email: ").strip()
password = getpass.getpass("Robinhood password (typing hidden): ")

rh.login(username, password, store_session=True)

bp = rh.profiles.load_account_profile(info="buying_power")
print(f"\nLogin OK. Buying power: ${bp}")

# clear the one-alert-per-failure flag so the bot alerts again next time
try:
    os.remove(os.path.join(os.path.dirname(__file__), "login_failed.flag"))
except OSError:
    pass
print("Session stored. The approver picks it up by itself within 5 min "
      "(or: systemctl restart tradingbot-approver to hurry it along).")
