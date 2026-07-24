"""
FX rates loader.

Cache-first by default: a compile with a warm cache or the bundled snapshot
makes no outbound HTTP request. Live fetches are opt-in via `live=True` (or
`ABICUS_LIVE_FX=1`) and validate the response shape before caching so a
truncated 200 can't poison the cache.
"""

import json
import os
from pathlib import Path

import pandas as pd
import requests

CONFIG_DIR = Path(__file__).parent / "config"
RATES_CACHE_FILE = CONFIG_DIR / "fx_rates_cache.json"
RATES_SNAPSHOT_FILE = CONFIG_DIR / "fx_rates_snapshot.json"

# Currencies the UI/lookthrough code assumes are present. A 200 response
# missing any of these is treated as malformed.
EXPECTED_CURRENCIES = frozenset({"USD", "GBP", "EUR", "SGD", "AUD", "HKD", "JPY"})


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


def _is_valid_rates(rates: dict) -> bool:
    if not isinstance(rates, dict) or len(rates) <= 1:
        return False
    return EXPECTED_CURRENCIES.issubset(rates.keys())


def _live_enabled(explicit: bool) -> bool:
    if explicit:
        return True
    flag = os.environ.get("ABICUS_LIVE_FX", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def fetch_fx_rates(live: bool = False, base: str = "USD") -> tuple[dict, dict]:
    """
    Return USD-based FX rates plus a metadata dict.

    Default path is cache-first and offline: cached file → bundled snapshot →
    empty. When `live=True` (or `ABICUS_LIVE_FX` is set), issue a single HTTP
    request, validate the response contains the expected currencies, and
    refresh the cache on success.

    Returns
    -------
    (rates, meta) : tuple
        meta keys: `source` (live|cache|snapshot|empty), `fx_stale` (True when
        not from a fresh live fetch), `fx_error` (True when no usable rates).
    """
    if _live_enabled(live):
        try:
            url = f"https://api.exchangerate-api.com/v4/latest/{base}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            rates = data.get("rates") if isinstance(data, dict) else None
            if _is_valid_rates(rates):
                try:
                    RATES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(RATES_CACHE_FILE, "w") as f:
                        json.dump(rates, f, indent=2)
                except OSError:
                    pass
                return rates, {"source": "live", "fx_stale": False, "fx_error": False}
        except Exception:
            pass

    cached = _read_json(RATES_CACHE_FILE)
    if _is_valid_rates(cached):
        return cached, {"source": "cache", "fx_stale": True, "fx_error": False}

    snapshot = _read_json(RATES_SNAPSHOT_FILE)
    if _is_valid_rates(snapshot):
        return snapshot, {"source": "snapshot", "fx_stale": True, "fx_error": False}

    return {"USD": 1.0}, {"source": "empty", "fx_stale": True, "fx_error": True}


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
