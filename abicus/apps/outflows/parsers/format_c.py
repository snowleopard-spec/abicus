"""
Parser for Format C statements (legacy .xls bank statements with separate
local/foreign currency columns).

Differs from Formats A and B in three ways:
- File is BIFF .xls (legacy), not .xlsx — requires the xlrd engine.
- Date is in "DD Mon YYYY" string format (e.g. "05 Apr 2026").
- Statement has both foreign and local amount columns; we use the local one.

Header detection is format-specific: each parser knows its own column names.
"""

import io
import warnings
import pandas as pd

REQUIRED_HEADERS = {
    "transaction date",
    "description",
    "transaction amount(local)",
}
MAX_HEADER_SCAN_ROWS = 30
DATE_FORMAT = "%d %b %Y"


def _normalise(s) -> str:
    """Lowercase and strip whitespace; keep the rest verbatim."""
    return str(s).strip().lower()


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """
    Scan the first MAX_HEADER_SCAN_ROWS rows for one whose normalised values
    are a superset of REQUIRED_HEADERS. Returns 0-indexed row number.
    """
    scan_limit = min(MAX_HEADER_SCAN_ROWS, len(df_raw))
    for row_idx in range(scan_limit):
        cells = {_normalise(v) for v in df_raw.iloc[row_idx]}
        if REQUIRED_HEADERS.issubset(cells):
            return row_idx
    raise ValueError(
        f"Could not locate header row containing all of {sorted(REQUIRED_HEADERS)} "
        f"within the first {MAX_HEADER_SCAN_ROWS} rows."
    )


def parse(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parse a Format C statement.

    Returns a DataFrame with columns: date, description, amount, source_file.
    - amount is positive for spend, negative for refund/credit (matches the
      statement's own sign convention).
    - The dashboard drops negatives, so credits are filtered out automatically.

    Raises ValueError on parse failures.
    """
    try:
        # xlrd emits a future-warning on every .xls read; suppress so it doesn't
        # leak into the dashboard logs.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_raw = pd.read_excel(
                io.BytesIO(file_bytes),
                header=None,
                dtype=object,
                engine="xlrd",
            )
    except Exception as e:
        raise ValueError(f"Could not read .xls file '{filename}': {e}") from e

    if df_raw.empty:
        raise ValueError(f"File '{filename}' is empty.")

    header_row = _find_header_row(df_raw)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            header=header_row,
            dtype=object,
            engine="xlrd",
        )

    # Build a lookup from normalised header → original column name
    col_lookup = {_normalise(c): c for c in df.columns}

    date_col = col_lookup["transaction date"]
    desc_col = col_lookup["description"]
    amt_col = col_lookup["transaction amount(local)"]

    df = df[[date_col, desc_col, amt_col]].copy()
    df.columns = ["date", "description", "amount"]

    # Drop rows where any of the three core fields are blank.
    # This catches non-transaction rows like "Previous Balance" (blank date)
    # and any footer artifacts.
    df = df.dropna(subset=["date", "description", "amount"])

    # Parse types
    df["date"] = pd.to_datetime(
        df["date"].astype(str).str.strip(),
        format=DATE_FORMAT,
        errors="coerce",
    ).dt.date
    df["description"] = df["description"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    # Drop rows that failed type coercion or have empty descriptions
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    df["source_file"] = filename
    return df
