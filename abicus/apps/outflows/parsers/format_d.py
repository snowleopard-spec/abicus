"""
Parser for Format D statements (headerless CSV bank account export).

Differs from Formats A/B/C in three ways:
- No header row — column positions are hardcoded.
- Date format is "DD/MM/YY" with single-digit days/months allowed.
- Sign convention is inverted: negative = spend (account decrease),
  positive = credit. We flip on parse so it matches A/B/C semantics
  (positive = spend, negative = credit) and the dashboard's existing
  drop-negatives rule filters out inflows automatically.

Column positions (0-indexed):
    0: date
    1: description
    2: amount
    3: running balance (ignored)
"""

import io
import warnings
import pandas as pd

EXPECTED_MIN_COLUMNS = 3  # at least date, description, amount must be present
DATE_COL = 0
DESC_COL = 1
AMOUNT_COL = 2


def parse(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parse a Format D statement.

    Returns a DataFrame with columns: date, description, amount, source_file.
    - amount is positive for spend (after sign flip), negative for credits.
    - The dashboard drops negatives, so credits are filtered out automatically.

    Raises ValueError on parse failures.
    """
    try:
        # Read everything as strings so we can clean before coercion.
        df = pd.read_csv(
            io.BytesIO(file_bytes),
            header=None,
            dtype=object,
        )
    except Exception as e:
        raise ValueError(f"Could not read CSV file '{filename}': {e}") from e

    if df.empty:
        raise ValueError(f"File '{filename}' is empty.")

    if df.shape[1] < EXPECTED_MIN_COLUMNS:
        raise ValueError(
            f"File '{filename}' has only {df.shape[1]} column(s); "
            f"Format D expects at least {EXPECTED_MIN_COLUMNS} "
            f"(date, description, amount)."
        )

    # Take only the columns we care about. Ignore extras (e.g. running balance).
    df = df.iloc[:, [DATE_COL, DESC_COL, AMOUNT_COL]].copy()
    df.columns = ["date", "description", "amount"]

    # Parse types. Don't pin a format: real-world exports use both DD/MM/YY
    # and DD/MM/YYYY. dayfirst=True disambiguates the day/month order without
    # locking to year width. Suppress the pandas warning about per-row
    # inference; for a few hundred rows the perf cost is negligible.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df["date"] = pd.to_datetime(
            df["date"].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce",
        ).dt.date
    # Drop rows with missing description before stringifying (otherwise NaN
    # becomes the literal string 'nan' and we can't reliably distinguish).
    df = df.dropna(subset=["description"])
    df["description"] = df["description"].astype(str).str.strip()

    # Strip thousands-separator commas before numeric coercion. read_csv's
    # `thousands` parameter only acts during type inference, which is skipped
    # when dtype=object — so we do it explicitly here.
    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )

    # Drop rows that failed type coercion or have empty descriptions.
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    # Flip sign so spending is positive (matches A/B/C convention).
    # Inflows become negative and the dashboard drops them.
    df["amount"] = -df["amount"]

    df["source_file"] = filename
    return df
