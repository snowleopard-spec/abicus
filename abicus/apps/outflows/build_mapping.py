"""
build_mapping.py
=================

Converts the curated Excel mapping table into a JSON config for runtime use.

Usage:
    python build_mapping.py

Inputs:
    config/mapping.xlsx       Two columns: partial_string, category
    config/categories.txt     One category per line (authoritative list)

Output:
    config/mapping.json       Flat dict {partial_string_lowercased: category}

Validations:
    - Both columns present, no blank cells
    - All partial_strings unique (after lowercasing and stripping)
    - Every category exists in categories.txt
    - "Uncategorised" is reserved and cannot be used in the mapping table

Warnings (non-fatal):
    - Very short partial_strings (<3 chars) — high false-match risk
    - Whitespace at the edges of partial_strings (silently stripped)
"""

import json
import sys
from pathlib import Path

import pandas as pd

from .categories import load_categories

CONFIG_DIR = Path(__file__).parent / "config"
MAPPING_XLSX = CONFIG_DIR / "mapping.xlsx"
MAPPING_JSON = CONFIG_DIR / "mapping.json"

RESERVED_CATEGORIES = {"Uncategorised"}
MIN_PARTIAL_STRING_LENGTH = 3


def load_mapping_xlsx() -> pd.DataFrame:
    """Read mapping.xlsx; validate column structure."""
    if not MAPPING_XLSX.exists():
        raise FileNotFoundError(
            f"Missing {MAPPING_XLSX}. Create it with columns: partial_string, category."
        )
    df = pd.read_excel(MAPPING_XLSX, dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"partial_string", "category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{MAPPING_XLSX.name} is missing required columns: {sorted(missing)}. "
            f"Found columns: {list(df.columns)}"
        )

    return df[["partial_string", "category"]]


def validate_and_build(df: pd.DataFrame, valid_categories: set[str]) -> tuple[dict, list[str]]:
    """
    Validate the mapping table and build the JSON dict.

    Returns (mapping_dict, warnings).
    Raises ValueError on fatal issues.
    """
    errors: list[str] = []
    warnings: list[str] = []

    df = df.dropna(how="all").reset_index(drop=True)

    blank_partial = df[df["partial_string"].isna() | (df["partial_string"].astype(str).str.strip() == "")]
    blank_category = df[df["category"].isna() | (df["category"].astype(str).str.strip() == "")]
    if not blank_partial.empty:
        rows = [str(i + 2) for i in blank_partial.index]
        errors.append(f"Blank partial_string in row(s): {', '.join(rows)}")
    if not blank_category.empty:
        rows = [str(i + 2) for i in blank_category.index]
        errors.append(f"Blank category in row(s): {', '.join(rows)}")

    if errors:
        raise ValueError("Mapping table errors:\n  - " + "\n  - ".join(errors))

    mapping: dict[str, str] = {}
    seen_originals: dict[str, str] = {}

    for idx, row in df.iterrows():
        excel_row = idx + 2

        original = str(row["partial_string"])
        stripped = original.strip()
        partial = stripped.lower()
        category = str(row["category"]).strip()

        if original != stripped:
            warnings.append(
                f"Row {excel_row}: leading/trailing whitespace in partial_string '{original}' (stripped)"
            )

        if len(partial) < MIN_PARTIAL_STRING_LENGTH:
            warnings.append(
                f"Row {excel_row}: partial_string '{stripped}' is very short ({len(partial)} chars) — high false-match risk"
            )

        if category in RESERVED_CATEGORIES:
            errors.append(
                f"Row {excel_row}: '{category}' is reserved and cannot be used in the mapping table"
            )
            continue

        if category not in valid_categories:
            errors.append(
                f"Row {excel_row}: category '{category}' is not in categories.txt"
            )
            continue

        if partial in mapping:
            errors.append(
                f"Row {excel_row}: duplicate partial_string '{stripped}' "
                f"(already mapped from '{seen_originals[partial]}')"
            )
            continue

        mapping[partial] = category
        seen_originals[partial] = stripped

    if errors:
        raise ValueError("Mapping table errors:\n  - " + "\n  - ".join(errors))

    return mapping, warnings


def report_substring_overlaps(mapping: dict) -> list[str]:
    """
    Find pairs where one partial_string is a substring of another but maps
    to a different category. Not an error — longest-match handles it — but
    worth surfacing so the user can confirm intent.
    """
    notes = []
    keys = sorted(mapping.keys(), key=len)
    for i, short in enumerate(keys):
        for long in keys[i + 1:]:
            if short == long:
                continue
            if short in long and mapping[short] != mapping[long]:
                notes.append(
                    f"'{short}' ({mapping[short]}) is contained in "
                    f"'{long}' ({mapping[long]}) — longest match wins, confirm this is intended"
                )
    return notes


def build_mapping_if_changed() -> tuple[bool, int, list[str]]:
    """
    Rebuild mapping.json from mapping.xlsx only if the source is newer than
    the output (or the output doesn't exist). Used by the dashboard to skip
    redundant work on Compile.

    Returns:
        (rebuilt, n_rules, warnings)
        rebuilt: True if the JSON was regenerated this call.
        n_rules: number of rules in the (current) mapping.json.
        warnings: list of human-readable warning strings (overlaps + per-row
                  warnings from the build). Empty if the build was skipped.

    Raises:
        FileNotFoundError if mapping.xlsx is missing.
        ValueError on validation errors (with clear per-row detail).
    """
    if not MAPPING_XLSX.exists():
        raise FileNotFoundError(
            f"Missing {MAPPING_XLSX}. Create it with columns: partial_string, category."
        )

    needs_rebuild = (
        not MAPPING_JSON.exists()
        or MAPPING_XLSX.stat().st_mtime > MAPPING_JSON.stat().st_mtime
    )

    if not needs_rebuild:
        # Just count rules in the existing JSON; no warnings.
        with MAPPING_JSON.open() as f:
            existing = json.load(f)
        return False, len(existing), []

    # Rebuild
    valid_categories, _ = load_categories()
    df = load_mapping_xlsx()
    mapping, build_warnings = validate_and_build(df, valid_categories)

    CONFIG_DIR.mkdir(exist_ok=True)
    with MAPPING_JSON.open("w") as f:
        json.dump(mapping, f, indent=2, sort_keys=True, ensure_ascii=False)

    overlap_warnings = report_substring_overlaps(mapping)
    all_warnings = build_warnings + [
        f"Substring overlap: {note}" for note in overlap_warnings
    ]

    return True, len(mapping), all_warnings


def main() -> int:
    print(f"Reading {MAPPING_XLSX.name}...")
    try:
        valid_categories, excluded_categories = load_categories()
        df = load_mapping_xlsx()
        mapping, warnings = validate_and_build(df, valid_categories)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌ {e}", file=sys.stderr)
        return 1

    CONFIG_DIR.mkdir(exist_ok=True)
    with MAPPING_JSON.open("w") as f:
        json.dump(mapping, f, indent=2, sort_keys=True, ensure_ascii=False)

    print(f"\n✅ Wrote {MAPPING_JSON.name}: {len(mapping)} mappings")

    categories_used = sorted(set(mapping.values()))
    print(f"   Categories used ({len(categories_used)}): {', '.join(categories_used)}")

    unused = sorted(valid_categories - set(mapping.values()) - RESERVED_CATEGORIES)
    if unused:
        print(f"   Categories with no mappings yet: {', '.join(unused)}")

    if excluded_categories:
        print(f"   Excluded from dashboard: {', '.join(sorted(excluded_categories))}")

    if warnings:
        print(f"\n⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"   - {w}")

    overlaps = report_substring_overlaps(mapping)
    if overlaps:
        print(f"\nℹ️  Substring overlaps (longest match wins, confirm intent):")
        for note in overlaps:
            print(f"  {note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
