"""
Parser for Format E statements (bank CSV with extensive metadata header
and S$ currency prefix on amounts).

Structurally similar to Formats A/B/C in that the header row is buried
under metadata and we locate it by name. Distinct features:
- Amounts have a "S$" currency prefix and comma thousands separators
  (e.g., "-S$9.50", "-S$1,129.08").
- Date format is DD-Mon-YY (e.g., "1-Jan-26"), but we use dayfirst=True
  rather than a pinned format so that DD-Mon-YYYY exports also work.
- Sign convention: negative = spend, positive = inflow. We flip on parse
  so it matches the rest of the codebase (positive = spend).
"""

import io
import re
import warnings
import pandas as pd

REQUIRED_HEADERS = {"date", "description", "money in/out"}
MAX_HEADER_SCAN_ROWS = 300  # this format has ~30 metadata rows

# Strip S$ prefix and thousands separators. Sign sits before "S$" in this
# format (e.g. "-S$9.50"), so a simple replace preserves it.
_AMOUNT_CLEANUP = re.compile(r"S\$|,")


def _normalise(s) -> str:
    """Lowercase, strip whitespace; keep the rest verbatim."""
    return str(s).strip().lower()


def _find_header_row(df_raw: pd.DataFrame) -> int:
    """Scan first MAX_HEADER_SCAN_ROWS for a row containing all required headers."""
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
    Parse a Format E statement.

    Returns a DataFrame with columns: date, description, amount, source_file.
    - amount is positive for spend (after sign flip), negative for inflows.
    - The dashboard drops negatives, so inflows are filtered out automatically.

    Raises ValueError on parse failures.
    """
    try:
        df_raw = pd.read_csv(
            io.BytesIO(file_bytes),
            header=None,
            dtype=object,
        )
    except Exception as e:
        raise ValueError(f"Could not read CSV file '{filename}': {e}") from e

    if df_raw.empty:
        raise ValueError(f"File '{filename}' is empty.")

    header_row = _find_header_row(df_raw)

    df = pd.read_csv(
        io.BytesIO(file_bytes),
        header=header_row,
        dtype=object,
    )

    # Build a lookup from normalised header → original column name
    col_lookup = {_normalise(c): c for c in df.columns}
    date_col = col_lookup["date"]
    desc_col = col_lookup["description"]
    amt_col = col_lookup["money in/out"]

    df = df[[date_col, desc_col, amt_col]].copy()
    df.columns = ["date", "description", "amount"]

    # Drop rows where description is missing — catches the trailing "Total"
    # row's siblings (separator bands have empty descriptions) before they
    # become the literal string 'nan' after stringification.
    df = df.dropna(subset=["description"])

    # Parse date. Don't pin a format: real exports vary between DD-Mon-YY and
    # DD-Mon-YYYY. dayfirst=True disambiguates day/month order.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df["date"] = pd.to_datetime(
            df["date"].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce",
        ).dt.date

    df["description"] = df["description"].astype(str).str.strip()

    # Strip S$ prefix and comma thousands before numeric coercion.
    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).map(lambda s: _AMOUNT_CLEANUP.sub("", s).strip()),
        errors="coerce",
    )

    # Drop rows with unparseable date or amount (catches "Total" row, separator
    # rows, blank rows). Drop empty descriptions too.
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    # Flip sign so spending is positive (matches A/B/C/D convention).
    # Inflows become negative and the dashboard drops them.
    df["amount"] = -df["amount"]

    df["source_file"] = filename
    return df
