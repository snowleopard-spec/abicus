"""
Parser for Format E statements (Revolut).

Handles two Revolut export shapes and auto-detects which one it's looking at:

Variant A — "classic" export
    ~30 metadata rows precede a wide header row
    (Date, Description, Category, Money in/out, Balance, Tax withheld, ...).
    Dates like "1-Mar-26". Amounts like "-S$166.70" (S$ prefix, sign before).

Variant B — "transaction list" export
    First row is the header
    (Type, Product, Started Date, Completed Date, Description, Amount, Fee,
    Currency, State, Balance).
    Dates like "1/6/26 11:41" (D/M/YY with time). Amounts are plain floats.
    Fees sit in a separate column and are always positive.

Detection is done by scanning the first rows for a variant-specific fingerprint
of column headers.

Sign convention: negative = spend, positive = inflow. We flip on parse so it
matches the rest of the codebase (positive = spend).
"""

import io
import re
import warnings
import pandas as pd

VARIANT_A_HEADERS = {"date", "description", "money in/out"}
VARIANT_B_HEADERS = {"type", "started date", "completed date", "amount", "state"}
MAX_HEADER_SCAN_ROWS = 300  # variant A has ~30 metadata rows above its header

# Strip S$ prefix and thousands separators. Sign sits before "S$" in variant A
# (e.g. "-S$9.50"), so a simple replace preserves it.
_AMOUNT_CLEANUP = re.compile(r"S\$|,")


def _normalise(s) -> str:
    """Lowercase, strip whitespace; keep the rest verbatim."""
    return str(s).strip().lower()


def _detect_variant(df_raw: pd.DataFrame) -> tuple[str, int]:
    """
    Scan the first MAX_HEADER_SCAN_ROWS for a row matching either variant's
    header fingerprint. Returns (variant_letter, header_row_index).
    """
    scan_limit = min(MAX_HEADER_SCAN_ROWS, len(df_raw))
    for row_idx in range(scan_limit):
        cells = {_normalise(v) for v in df_raw.iloc[row_idx]}
        if VARIANT_B_HEADERS.issubset(cells):
            return "B", row_idx
        if VARIANT_A_HEADERS.issubset(cells):
            return "A", row_idx
    raise ValueError(
        f"Could not identify Revolut export variant within the first "
        f"{MAX_HEADER_SCAN_ROWS} rows. Expected either "
        f"{sorted(VARIANT_A_HEADERS)} (variant A) or "
        f"{sorted(VARIANT_B_HEADERS)} (variant B)."
    )


def parse(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parse a Format E (Revolut) statement, auto-detecting the export variant.

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

    variant, header_row = _detect_variant(df_raw)

    if variant == "A":
        return _parse_variant_a(file_bytes, filename, header_row)
    return _parse_variant_b(file_bytes, filename, header_row)


def _parse_variant_a(file_bytes: bytes, filename: str, header_row: int) -> pd.DataFrame:
    """Parse the classic Revolut export (metadata header + S$ prefixed amounts)."""
    df = pd.read_csv(
        io.BytesIO(file_bytes),
        header=header_row,
        dtype=object,
    )

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

    # Don't pin a format: real exports vary between DD-Mon-YY and DD-Mon-YYYY.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df["date"] = pd.to_datetime(
            df["date"].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce",
        ).dt.date

    df["description"] = df["description"].astype(str).str.strip()

    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).map(lambda s: _AMOUNT_CLEANUP.sub("", s).strip()),
        errors="coerce",
    )

    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    # Flip so spending is positive (matches A/B/C/D convention).
    df["amount"] = -df["amount"]

    df["source_file"] = filename
    return df


def _parse_variant_b(file_bytes: bytes, filename: str, header_row: int) -> pd.DataFrame:
    """
    Parse the transaction-list Revolut export.

    Fees are emitted as separate rows (description suffix " (fee)") so they
    appear distinctly in categorisation. Only COMPLETED rows are kept —
    PENDING may still change and REVERTED were refunded (the balance already
    accounts for this).
    """
    df = pd.read_csv(
        io.BytesIO(file_bytes),
        header=header_row,
        dtype=object,
    )

    col_lookup = {_normalise(c): c for c in df.columns}
    date_col = col_lookup["completed date"]
    desc_col = col_lookup["description"]
    amt_col = col_lookup["amount"]
    fee_col = col_lookup["fee"]
    state_col = col_lookup["state"]

    df = df[[date_col, desc_col, amt_col, fee_col, state_col]].copy()
    df.columns = ["date", "description", "amount", "fee", "state"]

    df = df[df["state"].astype(str).str.strip().str.upper() == "COMPLETED"]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df["date"] = pd.to_datetime(
            df["date"].astype(str).str.strip(),
            dayfirst=True,
            errors="coerce",
        ).dt.date

    df["description"] = df["description"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["fee"] = pd.to_numeric(df["fee"], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""]

    # Base rows: flip sign so spend is positive.
    base = df[["date", "description", "amount"]].copy()
    base["amount"] = -base["amount"]
    base = base[base["amount"] != 0]

    # Fee rows: fees are always positive outflows. Distinct description keeps
    # them from colliding with the base row in duplicate detection.
    fee_rows = df[df["fee"] > 0][["date", "description", "fee"]].copy()
    fee_rows["description"] = fee_rows["description"] + " (fee)"
    fee_rows = fee_rows.rename(columns={"fee": "amount"})

    out = pd.concat([base, fee_rows], ignore_index=True)

    if out.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    out = out.sort_values("date", kind="stable").reset_index(drop=True)
    out["source_file"] = filename
    return out
