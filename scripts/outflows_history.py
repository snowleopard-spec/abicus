#!/usr/bin/env python3
"""CLI over the outflows DB commit history (V3 Feature A, M3).

Thin wrapper over abicus.apps.outflows.db_history — the same operations
the DB Edit tab's History panel uses.

    python scripts/outflows_history.py list
    python scripts/outflows_history.py diff <sha>
    python scripts/outflows_history.py restore <sha>

Run from the repo root (or anywhere with abicus importable).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from abicus.apps.outflows import db_history  # noqa: E402


def _fmt_row(r: dict) -> str:
    return (
        f"{r['date']}  {r['description']}  {r['amount']:.2f}"
        f"  [{r['category']}]  {r['account']}"
    )


def cmd_list(_args) -> int:
    entries = db_history.log()
    if not entries:
        print("No history yet — the repo is created on the first DB write.")
        return 0
    for e in entries:
        print(f"{e['sha8']}  {e['date'][:19]}  {e['label']}")
    return 0


def cmd_diff(args) -> int:
    d = db_history.diff(args.ref)
    for r in d["added"]:
        print(f"+ {_fmt_row(r)}")
    for r in d["removed"]:
        print(f"- {_fmt_row(r)}")
    for c in d["changed"]:
        print(f"~ {_fmt_row(c['before'])}")
        print(f"  → {_fmt_row(c['after'])}")
    if not any(d.values()):
        print("No row changes in this commit.")
    return 0


def cmd_restore(args) -> int:
    result = db_history.restore(args.ref)
    print(
        f"Restored transactions.db to {result['restored_to']}"
        f" ({result['rows']} rows). The previous state was snapshotted"
        " first — a restore is itself reversible via `list` + `restore`."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="print the commit log, newest first")
    d = sub.add_parser("diff", help="show what a commit changed")
    d.add_argument("ref", help="commit sha (from `list`)")
    r = sub.add_parser("restore", help="rebuild the DB from a commit")
    r.add_argument("ref", help="commit sha (from `list`)")
    args = p.parse_args()
    try:
        return {"list": cmd_list, "diff": cmd_diff, "restore": cmd_restore}[
            args.cmd
        ](args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
