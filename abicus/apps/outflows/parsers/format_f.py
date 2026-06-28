"""
Parser for Format F statements (manual entries / round-trip of the
categorised export).

Unlike Formats A–E, this parser handles user-authored xlsx files in the
shape of the dashboard's "Download categorised" output. Two use cases:

1. Round-trip: re-import a previously downloaded categorised file
   (e.g. archived state, or after editing categories in Excel).
2. Manual statements: hand-typed transactions for cash spending or
   accounts without a CSV/xlsx export option.

Schema:
- Required columns: date, description, amount
- Optional columns: category, account, matched_pattern, source_file
- Sign convention: positive = spend (matches the export, drops negatives)

If a row has a non-blank category, it is "pre-categorised" and bypasses
the normal substring/history matching. The pipeline respects this via
the `pre_categorised` flag on the returned DataFrame.

If the `account` column is present, those values override the per-file
dropdown selection (per-row accounts). If absent, the dropdown selection
is used for every row.
"""

import io
import warnings

import pandas as pd

REQUIRED_COLUMNS = {"date", "description", "amount"}


def _normalise(s) -> str:
    """Lowercase + strip; used to match column headers regardless of case."""
    return str(s).strip().lower()


def parse(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parse a Format F xlsx file.

    Returns a DataFrame with columns:
        date, description, amount, source_file, pre_categorised
    Optionally also: category, account (if present in the source file).

    - `pre_categorised` is True for rows where the input had a non-blank
      category, False otherwise.
    - `account` is set per-row if present in the file; otherwise the column
      is omitted (app.py will fill from the dropdown).

    Raises ValueError on missing required columns or unreadable file.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=object)
    except Exception as e:
        raise ValueError(f"Could not read xlsx file '{filename}': {e}") from e

    if df.empty:
        raise ValueError(f"File '{filename}' is empty.")

    # Normalise headers for matching, but keep originals around in case
    # we need to surface them in errors.
    col_lookup = {_normalise(c): c for c in df.columns}
    available = set(col_lookup.keys())

    missing = REQUIRED_COLUMNS - available
    if missing:
        raise ValueError(
            f"File '{filename}' is missing required column(s): "
            f"{sorted(missing)}. Required: {sorted(REQUIRED_COLUMNS)}."
        )

    # Build the canonical-shape DataFrame, keeping only known columns.
    out = pd.DataFrame()
    out["date"] = df[col_lookup["date"]]
    out["description"] = df[col_lookup["description"]]
    out["amount"] = df[col_lookup["amount"]]

    has_category = "category" in available
    has_account = "account" in available

    if has_category:
        out["category"] = df[col_lookup["category"]]
    if has_account:
        out["account"] = df[col_lookup["account"]]

    # Drop rows where description is blank (catches trailing empty rows
    # often left in hand-edited xlsx files).
    out = out.dropna(subset=["description"])
    out["description"] = out["description"].astype(str).str.strip()
    out = out[out["description"] != ""].reset_index(drop=True)

    # Parse date with dayfirst=True (matches the export and other parsers).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out["date"] = pd.to_datetime(
            out["date"], dayfirst=True, errors="coerce"
        ).dt.date

    # Coerce amount; strip thousands separators if user typed them.
    out["amount"] = pd.to_numeric(
        out["amount"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )

    # Drop rows that failed type coercion.
    out = out.dropna(subset=["date", "amount"]).reset_index(drop=True)

    if out.empty:
        raise ValueError(
            f"No valid transaction rows found in '{filename}' after parsing."
        )

    # Determine pre_categorised flag. Empty/NaN/whitespace-only category
    # values are treated as "not pre-categorised" — they fall through to
    # normal categorisation.
    if has_category:
        cat_str = out["category"].fillna("").astype(str).str.strip().str.lower()
        # treat 'nan', 'none', '' as blank
        blank_mask = cat_str.isin(["", "nan", "none"])
        out["pre_categorised"] = ~blank_mask
        # Blank category cells become NaN for downstream consistency
        out.loc[blank_mask, "category"] = pd.NA
    else:
        out["pre_categorised"] = False

    if has_account:
        # Strip whitespace, treat blank/NaN as missing → fall back to dropdown.
        # We keep the column even with NaNs; app.py fills missing values from
        # the dropdown.
        acct_str = out["account"].fillna("").astype(str).str.strip().str.lower()
        blank_acct = acct_str.isin(["", "nan", "none"])
        out.loc[blank_acct, "account"] = pd.NA

    out["source_file"] = filename
    return out
