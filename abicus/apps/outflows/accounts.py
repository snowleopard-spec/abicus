"""
accounts.py
============

Loader for config/accounts.yaml. Maps human-friendly account names to parser
format keys.

Used by app.py to populate the per-file dropdown with account names instead of
generic "Format A" / "Format B" labels, and to resolve which parser to use for
each uploaded file.

The format keys referenced here must exist in app.PARSERS — otherwise the
loader raises ValueError at startup so typos surface immediately.
"""

from pathlib import Path
import yaml

DEFAULT_PATH = Path(__file__).parent / "config" / "accounts.yaml"


def load_accounts(
    path: Path = DEFAULT_PATH,
    valid_formats: set[str] | None = None,
) -> dict[str, str]:
    """
    Read accounts.yaml.

    Returns an ordered dict mapping account_name → format_key. Order
    follows the YAML file (so the user controls dropdown ordering).

    Args:
        path: Path to the YAML file.
        valid_formats: If provided, every referenced format must be in this
            set, otherwise ValueError. Pass list(PARSERS.keys()) from app.py.

    Raises:
        FileNotFoundError if the file is missing.
        ValueError on malformed structure, duplicate names, or unknown formats.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Create it with an 'accounts:' list "
            f"mapping account names to format keys."
        )

    with path.open() as f:
        data = yaml.safe_load(f) or {}

    accounts_list = data.get("accounts")
    if not accounts_list:
        raise ValueError(
            f"{path.name} must contain a non-empty 'accounts:' list."
        )
    if not isinstance(accounts_list, list):
        raise ValueError(f"{path.name}: 'accounts' must be a list.")

    result: dict[str, str] = {}
    for i, entry in enumerate(accounts_list, start=1):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{path.name} entry {i}: must be a mapping with 'name' and 'format'."
            )

        name = entry.get("name")
        fmt = entry.get("format")

        if not name or not isinstance(name, str):
            raise ValueError(f"{path.name} entry {i}: missing or invalid 'name'.")
        if not fmt or not isinstance(fmt, str):
            raise ValueError(f"{path.name} entry {i}: missing or invalid 'format'.")

        name = name.strip()
        fmt = fmt.strip()

        if name in result:
            raise ValueError(
                f"{path.name} entry {i}: duplicate account name '{name}'."
            )

        if valid_formats is not None and fmt not in valid_formats:
            raise ValueError(
                f"{path.name} entry {i} ('{name}'): format '{fmt}' is not "
                f"a registered parser. Known formats: {sorted(valid_formats)}"
            )

        result[name] = fmt

    return result
