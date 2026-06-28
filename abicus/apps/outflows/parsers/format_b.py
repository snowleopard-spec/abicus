"""
Parser for Format B statements (bank account export with separate
Withdrawals / Deposits columns).

Differs from Format A in three ways:
- Header is "Transaction date" / "Description" / "Withdrawals(SGD)" /
  "Deposits(SGD)" rather than Date / Description / Amount.
- Spend and income are in separate columns; we combine them into a single
  signed amount (withdrawals positive, deposits negative) so downstream
  pipeline behaviour is identical to Format A.
- File can arrive as either .xlsx (Excel export) or .csv (online banking
  download). The reader is selected by extension; the rest of the parsing
  logic is shared.

CSV variant has multi-line descriptions (embedded newlines inside quoted
fields) that we collapse to single-line at parse time.

Header detection is format-specific: each parser knows its own column names.
"""

import csv
import io
import re
import warnings
from pathlib import Path

import pandas as pd

REQUIRED_HEADERS = {"transaction date", "description", "withdrawals"}
MAX_HEADER_SCAN_ROWS = 30

# Collapse runs of any whitespace (including embedded \n) to a single space.
_WHITESPACE_RUN = re.compile(r"\s+")


def _normalise(s) -> str:
    """Lowercase, strip, remove the '(SGD)' suffix if present."""
    text = str(s).strip().lower()
    if text.endswith("(sgd)"):
        text = text[: -len("(sgd)")].strip()
    return text


def _rectangularise_csv(file_bytes: bytes) -> io.StringIO:
    """
    Use the stdlib csv module (which respects quoted fields and embedded
    newlines) to parse the raw bytes, then re-emit as a rectangular CSV
    where every row has the same number of fields.

    Necessary for OCBC online-banking exports where:
    - Pre-header metadata rows have fewer fields than transaction rows
    - Some transaction rows have more fields than the header (extra
      trailing commas, or commas inside descriptions that the bank
      didn't quote consistently)

    Without this, pandas locks in the column count from line 1 and
    errors on any wider row.
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return io.StringIO("")

    max_fields = max(len(row) for row in rows)
    padded = [row + [""] * (max_fields - len(row)) for row in rows]

    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(padded)
    out.seek(0)
    return out


def _read_raw(file_bytes: bytes, filename: str, header) -> pd.DataFrame:
    """
    Read the file using the appropriate engine for its extension.
    Returns a DataFrame with `header` interpretation passed through.

    For CSVs, pre-rectangularises ragged rows (see _rectangularise_csv).
    """
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".csv":
            buf = _rectangularise_csv(file_bytes)
            return pd.read_csv(buf, header=header, dtype=object)
        # default Excel handling for .xlsx, .xls, anything else
        buf = io.BytesIO(file_bytes)
        return pd.read_excel(buf, header=header, dtype=object)
    except Exception as e:
        kind = "CSV" if ext == ".csv" else "Excel"
        raise ValueError(f"Could not read {kind} file '{filename}': {e}") from e


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
    Parse a Format B statement.

    Returns a DataFrame with columns: date, description, amount, source_file.
    - amount is positive for withdrawals (spend) and negative for deposits.
    - The dashboard drops negatives, so deposits are filtered out automatically.

    Raises ValueError on parse failures or ambiguous rows.
    """
    df_raw = _read_raw(file_bytes, filename, header=None)

    if df_raw.empty:
        raise ValueError(f"File '{filename}' is empty.")

    header_row = _find_header_row(df_raw)
    df = _read_raw(file_bytes, filename, header=header_row)

    # Build a lookup from normalised header → original column name so we can
    # find the columns regardless of capitalisation or "(SGD)" suffix.
    col_lookup = {_normalise(c): c for c in df.columns}

    date_col = col_lookup["transaction date"]
    desc_col = col_lookup["description"]
    withdraw_col = col_lookup["withdrawals"]
    # Deposits is optional in case a future statement variant doesn't have one
    deposit_col = col_lookup.get("deposits")

    keep_cols = [date_col, desc_col, withdraw_col]
    if deposit_col is not None:
        keep_cols.append(deposit_col)

    df = df[keep_cols].copy()
    df.columns = ["date", "description", "withdrawal", "deposit"][: len(keep_cols)]
    if deposit_col is None:
        df["deposit"] = pd.NA  # normalise shape

    # Strip thousands-separator commas before numeric coercion. The .xlsx
    # variant typically has real numbers; the .csv variant has strings like
    # "1,100.00". Stripping unconditionally is harmless for already-numeric.
    df["withdrawal"] = pd.to_numeric(
        df["withdrawal"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )
    df["deposit"] = pd.to_numeric(
        df["deposit"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )

    # Drop rows where both amount columns are blank (footer/separator artifacts)
    df = df.dropna(subset=["withdrawal", "deposit"], how="all").reset_index(drop=True)

    # Detect ambiguous both-filled rows
    both_filled = df["withdrawal"].notna() & df["deposit"].notna()
    if both_filled.any():
        bad_rows = df[both_filled].index.tolist()
        raise ValueError(
            f"In '{filename}', {both_filled.sum()} row(s) have both Withdrawals "
            f"and Deposits filled (ambiguous). Row indices: {bad_rows}"
        )

    # Combine into a single signed amount: withdrawal positive, deposit negative
    df["amount"] = df["withdrawal"].fillna(0) - df["deposit"].fillna(0)
    df = df[["date", "description", "amount"]]

    # Drop NaN descriptions before stringifying (avoids the literal "nan" trap)
    df = df.dropna(subset=["description"])

    # Parse date. dayfirst=True handles both DD/MM/YY and DD/MM/YYYY for the
    # CSV variant; harmless on Excel datetimes.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df["date"] = pd.to_datetime(
            df["date"],
            dayfirst=True,
            errors="coerce",
        ).dt.date

    # Normalise descriptions: collapse embedded newlines and runs of whitespace
    # to single spaces. CSV exports from this format can contain multi-line
    # descriptions inside quoted fields; the .xlsx variant doesn't, but the
    # cleanup is a no-op on already-clean data.
    df["description"] = (
        df["description"]
        .astype(str)
        .map(lambda s: _WHITESPACE_RUN.sub(" ", s).strip())
    )

    # Drop rows that failed type coercion or have empty descriptions
    df = df.dropna(subset=["date", "amount"])
    df = df[df["description"] != ""].reset_index(drop=True)

    if df.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    df["source_file"] = filename
    return df
