"""
Parser for Format A statements (Amex-style export).

Locates the header row dynamically by searching for a row that contains
all of {Date, Description, Amount}, case-insensitive. This makes the
parser robust to small format drifts (extra/fewer pre-header rows).
"""

import io
import pandas as pd

REQUIRED_COLUMNS = {"date", "description", "amount"}
MAX_HEADER_SCAN_ROWS = 30


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """
    Scan the first MAX_HEADER_SCAN_ROWS rows for one containing all
    required column names (case-insensitive, whitespace-stripped).
    Returns the 0-indexed row number, or raises ValueError if not found.
    """
    scan_limit = min(MAX_HEADER_SCAN_ROWS, len(df_raw))
    for row_idx in range(scan_limit):
        row_values = df_raw.iloc[row_idx].astype(str).str.strip().str.lower()
        cell_set = set(row_values)
        if REQUIRED_COLUMNS.issubset(cell_set):
            return row_idx
    raise ValueError(
        f"Could not locate header row containing all of {sorted(REQUIRED_COLUMNS)} "
        f"within the first {MAX_HEADER_SCAN_ROWS} rows."
    )


def parse(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parse a Format A statement.

    Returns a DataFrame with columns: date, description, amount, source_file.
    - date: datetime.date
    - description: str (stripped)
    - amount: float (positive = spend, negative = refund/payment)
    - source_file: str (the filename)

    Raises ValueError with a clear message if parsing fails.
    """
    # Read with no header so we can inspect raw rows
    try:
        df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=object)
    except Exception as e:
        raise ValueError(f"Could not read Excel file '{filename}': {e}") from e

    if df_raw.empty:
        raise ValueError(f"File '{filename}' is empty.")

    header_row = _find_header_row(df_raw)

    # Reread with the located header row
    df = pd.read_excel(
        io.BytesIO(file_bytes),
        header=header_row,
        dtype=object,
    )

    # Normalise column names: strip whitespace, lowercase for matching
    df.columns = [str(c).strip() for c in df.columns]
    col_lookup = {c.lower(): c for c in df.columns}

    date_col = col_lookup["date"]
    desc_col = col_lookup["description"]
    amt_col = col_lookup["amount"]

    # Keep only the three columns we need
    df = df[[date_col, desc_col, amt_col]].copy()
    df.columns = ["date", "description", "amount"]

    # Drop rows where any of the three core fields are blank
    df = df.dropna(subset=["date", "description", "amount"])

    # Parse types
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["description"] = df["description"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    # Drop rows that failed type coercion (e.g., footer rows like "Total")
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""]

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    df["source_file"] = filename
    df = df.reset_index(drop=True)

    return df
