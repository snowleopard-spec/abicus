"""
breakdown_config.py
===================

Loader for config/breakdown.json — display knobs for the Monthly
Breakdown page. Mirrors html_export.py's config pattern: missing file,
unreadable JSON, or a wrong-typed value falls back to the default, so a
bad edit never breaks the page.

Keys:
    show_exclude_toggle (bool, default true) — show the
        "Excl. Rent · Education · Holidays · Exceptional" header toggle.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config" / "breakdown.json"

_DEFAULTS = {"show_exclude_toggle": True}


def load_breakdown_config() -> dict:
    """Return the breakdown display config, defaults filled in."""
    cfg = dict(_DEFAULTS)
    try:
        with _CONFIG_PATH.open() as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return cfg
    val = raw.get("show_exclude_toggle") if isinstance(raw, dict) else None
    if isinstance(val, bool):
        cfg["show_exclude_toggle"] = val
    return cfg
