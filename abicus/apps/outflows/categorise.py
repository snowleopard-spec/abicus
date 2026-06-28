"""
categorise.py
==============

Core matching logic: maps a transaction description to a category by finding
the longest partial-string in the mapping that is a substring of the
description (case-insensitive).

Public API:
    categorise(description, mapping) -> (category, matched_pattern)
    categorise_dataframe(df, mapping) -> df with 'category' and 'matched_pattern' columns

Design notes:
    - The mapping is expected to have lowercased keys (build_mapping.py guarantees this).
    - Longest match wins. Ties broken alphabetically for determinism.
    - Naive O(n * m) substring scan. Fast enough for thousands of transactions
      against hundreds of mappings. If profiling ever shows this as a bottleneck,
      replace the body of `categorise` with an Aho-Corasick implementation —
      no other code in the project needs to change.
    - Rows arriving with `pre_categorised=True` (Format F) bypass matching
      entirely: their existing category is preserved and matched_pattern is
      set to "manual" to indicate user-provided categorisation.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

UNCATEGORISED = "Uncategorised"
MANUAL_PATTERN = "manual"


def categorise(
    description: str,
    mapping: dict[str, str],
    history: dict[str, str] | None = None,
) -> tuple[str, str]:
    """
    Return (category, matched_pattern) for a single transaction description.

    Match precedence:
        1. history (exact match, case-insensitive) — wins if present
        2. mapping (substring match, longest wins, case-insensitive)
        3. fallback to ("Uncategorised", "")

    The exact-first precedence means that if you've labelled a transaction in
    your transaction history file, that decision always overrides any general
    substring rule.

    Args:
        description: The transaction description string.
        mapping: Dict of {lowercased_partial_string: category}.
        history: Optional dict of {lowercased_full_description: category}
            built from transaction_history.xlsx (rows with a filled-in
            category only).
    """
    if not description:
        return UNCATEGORISED, ""

    desc_lower = description.lower()

    # 1. Exact match against transaction history wins
    if history and desc_lower in history:
        return history[desc_lower], description.strip()

    # 2. Substring match
    if not mapping:
        return UNCATEGORISED, ""

    matches = [p for p in mapping if p in desc_lower]
    if not matches:
        return UNCATEGORISED, ""

    # Longest wins; ties broken alphabetically (earlier wins) for determinism.
    best = min(matches, key=lambda p: (-len(p), p))
    return mapping[best], best


def categorise_dataframe(
    df: pd.DataFrame,
    mapping: dict[str, str],
    history: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Apply categorise() across a DataFrame's 'description' column.

    Returns a copy of df with two new columns appended (or preserved):
        - category: str
        - matched_pattern: str (empty if Uncategorised; full description for
          history exact matches; the matching substring for substring matches;
          "manual" for pre-categorised rows from Format F)

    If df has a `pre_categorised` boolean column, rows where that is True
    keep their existing `category` value and get matched_pattern="manual".
    Rows where it is False (or where the column is absent) go through normal
    matching.
    """
    if "description" not in df.columns:
        raise ValueError("DataFrame must have a 'description' column.")

    out = df.copy()

    # Default mask: nothing is pre-categorised unless the column says so.
    if "pre_categorised" in out.columns:
        pre_mask = out["pre_categorised"].fillna(False).astype(bool)
    else:
        pre_mask = pd.Series(False, index=out.index)

    # Run categorisation on the rows that need it.
    if pre_mask.any():
        # Pre-categorised rows: keep existing category, set pattern to "manual".
        # Rows that need categorisation: run categorise() as usual.
        out["matched_pattern"] = ""
        out.loc[pre_mask, "matched_pattern"] = MANUAL_PATTERN
        # category should already be set on pre_mask rows; ensure column exists
        if "category" not in out.columns:
            out["category"] = UNCATEGORISED

        non_pre = ~pre_mask
        if non_pre.any():
            results = out.loc[non_pre, "description"].apply(
                lambda d: categorise(d, mapping, history)
            )
            out.loc[non_pre, "category"] = results.apply(lambda r: r[0])
            out.loc[non_pre, "matched_pattern"] = results.apply(lambda r: r[1])
    else:
        # No pre-categorised rows — original simple path.
        results = out["description"].apply(lambda d: categorise(d, mapping, history))
        out["category"] = results.apply(lambda r: r[0])
        out["matched_pattern"] = results.apply(lambda r: r[1])

    return out


def load_mapping(path: str | Path) -> dict[str, str]:
    """Load mapping.json. Raises FileNotFoundError if missing."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run build_mapping.py to generate it from mapping.xlsx."
        )
    with path.open() as f:
        return json.load(f)
