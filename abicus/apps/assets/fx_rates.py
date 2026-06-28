"""
Fetches live FX rates and converts balances to USD.
Uses the free exchangerate.host API (no key required).
Falls back to a local flat file if offline.
"""

import json
import os
from pathlib import Path

import pandas as pd
import requests

RATES_CACHE_FILE = Path(__file__).parent / "config" / "fx_rates_cache.json"


def fetch_fx_rates(base="USD"):
    """
    Fetch current FX rates with USD as the base currency.
    Caches to a local file so the app works offline.

    Returns
    -------
    dict : e.g. {"GBP": 0.79, "EUR": 0.92, "SGD": 1.34, "USD": 1.0}
    """
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{base}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        rates = data["rates"]

        # Cache for offline use
        with open(RATES_CACHE_FILE, "w") as f:
            json.dump(rates, f, indent=2)

        return rates

    except Exception as e:
        # Fall back to cached rates
        if os.path.exists(RATES_CACHE_FILE):
            with open(RATES_CACHE_FILE, "r") as f:
                return json.load(f)
        else:
            # Last resort: return just USD = 1
            return {"USD": 1.0}


def convert_to_usd(df, rates):
    """
    Populate the 'Balance (USD)' column using FX rates.

    If a row already has a Balance (USD) value (e.g. because the source
    parser had a USD amount directly available, like Broker C's cash rows),
    that existing value is preserved and is NOT overwritten.

    Parameters
    ----------
    df : pd.DataFrame
        Must have 'Currency', 'Balance (Local)', and 'Balance (USD)' columns.
    rates : dict
        FX rates with USD as base (from fetch_fx_rates).

    Returns
    -------
    pd.DataFrame with 'Balance (USD)' populated.
    """
    df = df.copy()

    def to_usd(row):
        # Preserve any pre-populated USD value (e.g. from broker_c.py Forex rows)
        existing = row.get("Balance (USD)")
        if pd.notna(existing):
            return existing

        ccy = row["Currency"]
        local_amount = row["Balance (Local)"]
        if pd.isna(local_amount):
            return None
        rate = rates.get(ccy)
        if rate and rate != 0:
            return local_amount / rate  # rates are USD-based, so divide
        return None

    df["Balance (USD)"] = df.apply(to_usd, axis=1)
    return df
