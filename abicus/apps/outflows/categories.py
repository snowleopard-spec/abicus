"""
categories.py
==============

Loader for config/categories.txt. Two formats are accepted, line by line
(so a half-migrated file still loads):

    <category>                      — legacy: included in dashboard
    <category>,exclude              — legacy: excluded from dashboard view
    <category>,<TYPE>               — typed: TYPE is F/D/V/E/NA
    <category>,<TYPE>,exclude       — typed and excluded

Type codes: F = Fixed, D = Discretionary, V = Variable Essentials,
E = Extraordinary, NA = Not applicable. Legacy lines default to NA.
The type and the exclude flag are independent: NA does not imply excluded.

Lines starting with '#' are comments. Blank lines are ignored.
Used by build_mapping.py (validation) and router.py (dashboard filtering).
"""

from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "config" / "categories.txt"
EXCLUDE_FLAG = "exclude"
TYPE_CODES = {"F", "D", "V", "E", "NA"}
DEFAULT_TYPE = "NA"


def _parse(path: Path) -> dict[str, tuple[str, bool]]:
    """
    Read categories.txt and return {category: (type_code, excluded)}.

    Raises FileNotFoundError if the file is missing,
    ValueError if the file is empty or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Create it with one category per line."
        )

    table: dict[str, tuple[str, bool]] = {}

    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split(",")]
        category = parts[0]

        if not category:
            raise ValueError(f"{path.name} line {lineno}: empty category name")

        if len(parts) > 3:
            raise ValueError(
                f"{path.name} line {lineno}: too many columns. "
                f"Expected '<category>[,<type>][,{EXCLUDE_FLAG}]'"
            )

        type_code: str | None = None
        excluded = False
        for token in parts[1:]:
            if token.lower() == EXCLUDE_FLAG and not excluded:
                excluded = True
            elif token.upper() in TYPE_CODES and type_code is None:
                type_code = token.upper()
            else:
                raise ValueError(
                    f"{path.name} line {lineno}: unknown or duplicate "
                    f"flag '{token}'. Expected one of "
                    f"{sorted(TYPE_CODES)} or '{EXCLUDE_FLAG}'."
                )

        if category in table:
            raise ValueError(
                f"{path.name} line {lineno}: duplicate category '{category}'"
            )

        table[category] = (type_code or DEFAULT_TYPE, excluded)

    if not table:
        raise ValueError(f"{path.name} contains no categories.")

    return table


def load_categories(path: Path = DEFAULT_PATH) -> tuple[set[str], set[str]]:
    """
    Returns (all_categories, excluded_categories).
    excluded_categories is a subset of all_categories.
    """
    table = _parse(path)
    all_cats = set(table)
    excluded = {cat for cat, (_, excl) in table.items() if excl}
    return all_cats, excluded


def load_category_types(path: Path = DEFAULT_PATH) -> dict[str, str]:
    """
    Returns {category: type_code} with type_code in TYPE_CODES.
    Categories from legacy (untyped) lines map to DEFAULT_TYPE.
    """
    return {cat: type_code for cat, (type_code, _) in _parse(path).items()}
