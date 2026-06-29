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


def load_history_table(path: Path = DEFAULT_PATH) -> list[dict]:
    """Return history rows as a list of plain dicts:
    {date: 'YYYY-MM-DD' | '', description: str, amount: float | None, category: str}."""
    df = load_history_dataframe(path)
    if df.empty:
        return []
    out: list[dict] = []
    for _, row in df.iterrows():
        d = row["date"]
        if pd.isna(d):
            date_str = ""
        elif hasattr(d, "isoformat"):
            date_str = d.isoformat()[:10]
        else:
            date_str = str(d)[:10]
        desc = "" if pd.isna(row["description"]) else str(row["description"])
        amt = row["amount"]
        amt_val = None if pd.isna(amt) else float(amt)
        cat = "" if pd.isna(row["category"]) else str(row["category"]).strip()
        out.append(
            {"date": date_str, "description": desc, "amount": amt_val, "category": cat}
        )
    return out


def save_history_table(
    rows: list[dict],
    valid_categories: set[str] | None = None,
    path: Path = DEFAULT_PATH,
) -> tuple[int, list[str]]:
    """Persist a freshly edited history table to disk.

    Rules:
    - Drops fully-empty rows silently (lets the UI keep a trailing blank row).
    - Date + description required on any non-empty row.
    - Amount defaults to 0 if blank/missing.
    - Category may be blank (means "no exact-match yet, fall through").
    - If category is filled and `valid_categories` is provided, an unknown
      category is allowed but reported as a non-fatal warning (matches
      load_history_mapping's tolerance — those rows get ignored at runtime).
    - Duplicate descriptions (case-insensitive) keep the first occurrence;
      drops are reported as warnings.

    Returns (n_rows, warnings). Raises ValueError with row-level detail on
    validation failure.
    """
    errors: list[str] = []
    warnings: list[str] = []
    clean: list[dict] = []

    for i, r in enumerate(rows):
        ui_row = i + 1
        date_str = (r.get("date") or "").strip() if isinstance(r.get("date"), str) else (r.get("date") or "")
        description = (r.get("description") or "").strip()
        amount_raw = r.get("amount")
        category = (r.get("category") or "").strip()

        # Fully-empty → silent drop (UI can leave trailing blank rows).
        if not (date_str or description or amount_raw or category):
            continue

        if not description:
            errors.append(f"Row {ui_row}: description is required.")
            continue
        if not date_str:
            errors.append(f"Row {ui_row}: date is required.")
            continue

        try:
            date_parsed = pd.to_datetime(date_str)
        except Exception:
            errors.append(f"Row {ui_row}: invalid date '{date_str}'.")
            continue

        if amount_raw in (None, ""):
            amount_float = 0.0
        else:
            try:
                amount_float = float(amount_raw)
            except (TypeError, ValueError):
                errors.append(f"Row {ui_row}: invalid amount '{amount_raw}'.")
                continue

        if category and category == "Uncategorised":
            warnings.append(
                f"Row {ui_row} ('{description}'): 'Uncategorised' is reserved — "
                "this row will be ignored at categorisation time."
            )
        elif category and valid_categories is not None and category not in valid_categories:
            warnings.append(
                f"Row {ui_row} ('{description}'): category '{category}' is not in "
                "categories.txt — this row will be ignored at categorisation time."
            )

        clean.append(
            {
                "date": date_parsed,
                "description": description,
                "amount": amount_float,
                "category": category,
            }
        )

    if errors:
        raise ValueError("History table errors:\n  - " + "\n  - ".join(errors))

    # Dedupe on description (case-insensitive), keep first.
    seen: set[str] = set()
    deduped: list[dict] = []
    n_dupe = 0
    for r in clean:
        key = r["description"].lower()
        if key in seen:
            n_dupe += 1
            continue
        seen.add(key)
        deduped.append(r)
    if n_dupe:
        warnings.append(f"Dropped {n_dupe} duplicate description(s) (case-insensitive match).")

    df = pd.DataFrame(deduped, columns=REQUIRED_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)

    return len(df), warnings


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
