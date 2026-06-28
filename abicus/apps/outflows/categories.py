"""
categories.py
==============

Loader for config/categories.txt. Supports two columns per line:

    <category>           — included in dashboard
    <category>,exclude   — excluded from dashboard view (still in downloads)

Lines starting with '#' are comments. Blank lines are ignored.
Used by both build_mapping.py (validation) and app.py (dashboard filtering).
"""

from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "config" / "categories.txt"
EXCLUDE_FLAG = "exclude"


def load_categories(path: Path = DEFAULT_PATH) -> tuple[set[str], set[str]]:
    """
    Read categories.txt.

    Returns (all_categories, excluded_categories).
    excluded_categories is a subset of all_categories.

    Raises FileNotFoundError if the file is missing,
    ValueError if the file is empty or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Create it with one category per line."
        )

    all_cats: set[str] = set()
    excluded: set[str] = set()

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split(",")]
        category = parts[0]

        if not category:
            raise ValueError(f"{path.name} line {lineno}: empty category name")

        if len(parts) > 2:
            raise ValueError(
                f"{path.name} line {lineno}: too many columns. "
                f"Expected '<category>' or '<category>,exclude'"
            )

        if len(parts) == 2:
            flag = parts[1].lower()
            if flag != EXCLUDE_FLAG:
                raise ValueError(
                    f"{path.name} line {lineno}: unknown flag '{parts[1]}'. "
                    f"Only '{EXCLUDE_FLAG}' is supported."
                )
            excluded.add(category)

        all_cats.add(category)

    if not all_cats:
        raise ValueError(f"{path.name} contains no categories.")

    return all_cats, excluded
