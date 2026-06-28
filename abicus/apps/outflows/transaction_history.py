"""
transaction_history.py
=======================

Read/append logic for config/transaction_history.xlsx — the user-curated log
of transactions that didn't match a substring rule.

The file has four columns: date, description, amount, category.

- The dashboard appends new unmapped rows to this file with a blank category.
- The user fills in categories manually in Excel.
- At categorisation time, rows with a filled-in category form an exact-match
  layer that runs *before* substring matching.

Read is forgiving: missing file = empty history. Append is idempotent: rows
already present (deduped on description, case-insensitive) are skipped.
"""

from pathlib import Path
import pandas as pd

DEFAULT_PATH = Path(__file__).parent / "config" / "transaction_history.xlsx"

REQUIRED_COLUMNS = ["date", "description", "amount", "category"]


def load_history_dataframe(path: Path = DEFAULT_PATH) -> pd.DataFrame:
    """
    Read the history file. Returns an empty DataFrame with the right
    columns if the file is missing.
    """
    if not path.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    df = pd.read_excel(path, dtype=object)
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"{path.name} is missing required columns: {sorted(missing)}. "
            f"Found: {list(df.columns)}"
        )

    return df[REQUIRED_COLUMNS]


def load_history_mapping(
    path: Path = DEFAULT_PATH,
    valid_categories: set[str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """
    Build the {description_lowercased: category} dict for runtime lookup.

    Only includes rows where category is filled in AND (if valid_categories
    is provided) the category is in the allowed set.

    Args:
        path: History file path.
        valid_categories: Optional allowed category set. Rows with categories
            not in this set are excluded from the mapping and reported as
            warnings. The reserved "Uncategorised" is always invalid here
            because it's a no-op assignment that should fall through to
            substring matching anyway.

    Returns:
        (mapping, warnings)
        mapping: {lowercased_description: category}
        warnings: list of human-readable warning strings for invalid rows.

    On case-insensitive duplicate descriptions, the first valid filled-in
    category wins (deterministic; in practice duplicates shouldn't exist
    because append is deduped on description).
    """
    df = load_history_dataframe(path)
    if df.empty:
        return {}, []

    out: dict[str, str] = {}
    warnings: list[str] = []
    reserved = {"Uncategorised"}

    for idx, row in df.iterrows():
        excel_row = idx + 2  # +1 for 0-index, +1 for header
        desc = row["description"]
        cat = row["category"]

        if pd.isna(desc) or not str(desc).strip():
            continue
        if pd.isna(cat) or not str(cat).strip():
            continue

        cat_clean = str(cat).strip()
        desc_clean = str(desc).strip()

        # Validate against allowed categories if provided
        if valid_categories is not None:
            if cat_clean in reserved:
                warnings.append(
                    f"Row {excel_row} ('{desc_clean}'): "
                    f"category '{cat_clean}' is reserved and cannot be used."
                )
                continue
            if cat_clean not in valid_categories:
                warnings.append(
                    f"Row {excel_row} ('{desc_clean}'): "
                    f"category '{cat_clean}' is not in categories.txt."
                )
                continue

        key = desc_clean.lower()
        if key not in out:
            out[key] = cat_clean

    return out, warnings


def append_to_history(
    new_rows: pd.DataFrame,
    path: Path = DEFAULT_PATH,
) -> tuple[int, int]:
    """
    Append new unmapped rows to the history file, deduped on description
    (case-insensitive) against what's already there.

    Args:
        new_rows: DataFrame with columns date, description, amount.
            Category will be added as blank.
        path: Where to write.

    Returns (n_appended, n_skipped_duplicates).
    """
    expected = {"date", "description", "amount"}
    missing = expected - set(new_rows.columns)
    if missing:
        raise ValueError(f"new_rows missing columns: {sorted(missing)}")

    # Load existing
    existing = load_history_dataframe(path)
    existing_keys = {
        str(d).strip().lower()
        for d in existing["description"]
        if pd.notna(d) and str(d).strip()
    }

    # Filter new rows
    candidates = new_rows[["date", "description", "amount"]].copy()
    candidates["description"] = candidates["description"].astype(str).str.strip()

    # Drop blank descriptions
    candidates = candidates[candidates["description"] != ""]
    n_input = len(candidates)

    # Dedupe within the new batch itself (case-insensitive on description),
    # keeping the first occurrence
    candidates["_key"] = candidates["description"].str.lower()
    candidates = candidates.drop_duplicates(subset="_key", keep="first")

    # Filter out anything already in history
    to_append = candidates[~candidates["_key"].isin(existing_keys)].drop(columns="_key")
    n_skipped = n_input - len(to_append)

    if to_append.empty:
        return 0, n_skipped

    to_append["category"] = ""  # blank — user fills in manually
    to_append = to_append[REQUIRED_COLUMNS]

    combined = pd.concat([existing, to_append], ignore_index=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_excel(path, index=False)

    return len(to_append), n_skipped
