"""SQLite persistence for outflows — a rolling source of truth for
categorised transactions across compile sessions.

Rows are keyed by a stable content hash (`tx_hash`) so re-committing a
period with the same rows updates existing categories in place instead
of creating duplicates. Path lives under the app's `data/` folder, which
is gitignored.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).parent / "data" / "transactions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    tx_hash         TEXT PRIMARY KEY,
    date            TEXT NOT NULL,
    description     TEXT NOT NULL,
    amount          REAL NOT NULL,
    category        TEXT NOT NULL,
    account         TEXT NOT NULL,
    matched_pattern TEXT,
    source_file     TEXT,
    committed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tx_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_tx_category ON transactions(category);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _row_hash(
    date: str, amount: float, description: str,
    account: str, source_file: str, occurrence: int,
) -> str:
    # `occurrence` disambiguates same-content rows within a batch. First
    # occurrence gets 1 (matches "regular" rows in the DB); an un-suppressed
    # duplicate becomes 2, 3, ... so it lands as a distinct DB row instead of
    # collapsing onto its twin.
    key = f"{date}|{amount:.4f}|{description}|{account}|{source_file}|{occurrence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upsert(rows: Iterable[dict]) -> dict:
    """Upsert rows into the DB. Each row must have all CATEGORISED_COLS.

    Assigns each row a stable per-batch occurrence counter within its
    (date, amount, description, account, source_file) group so an
    un-suppressed duplicate becomes its own DB row rather than overwriting
    the original.

    Returns {"inserted": N, "updated": M, "total_in_db": T}.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = updated = 0
    occ_seen: dict[tuple, int] = {}
    with _connect() as conn:
        for r in rows:
            group = (
                str(r["date"]), float(r["amount"]),
                str(r["description"]), str(r["account"]),
                str(r.get("source_file") or ""),
            )
            occ_seen[group] = occ_seen.get(group, 0) + 1
            tx_hash = _row_hash(*group, occ_seen[group])
            existing = conn.execute(
                "SELECT category FROM transactions WHERE tx_hash = ?",
                (tx_hash,),
            ).fetchone()
            conn.execute(
                """INSERT INTO transactions
                    (tx_hash, date, description, amount, category, account,
                     matched_pattern, source_file, committed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tx_hash) DO UPDATE SET
                    category        = excluded.category,
                    matched_pattern = excluded.matched_pattern,
                    committed_at    = excluded.committed_at""",
                (
                    tx_hash, str(r["date"]), str(r["description"]),
                    float(r["amount"]), str(r["category"]), str(r["account"]),
                    r.get("matched_pattern") or None,
                    r.get("source_file") or None,
                    now,
                ),
            )
            if existing is None:
                inserted += 1
            else:
                updated += 1
        total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    return {"inserted": inserted, "updated": updated, "total_in_db": int(total)}


def clear() -> dict:
    """Delete every row from the transactions table. Schema stays so the
    next commit doesn't need to re-init. Returns {"deleted": N}."""
    if not DB_PATH.exists():
        return {"deleted": 0}
    with _connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.execute("DELETE FROM transactions")
    return {"deleted": int(n)}


def load_monthly_breakdown(selected_months: list[str] | None = None) -> dict:
    """Aggregate the DB into per-category, per-month totals for the
    breakdown page.

    If `selected_months` is given, restrict to that set (used by the PDF
    export so the report matches what's currently on-screen). Categories
    with zero spend in the selection drop out.

    Returns:
        {
          "months": ["2026-01", "2026-02", ...],           # sorted asc
          "by_category": {cat: {month: total, ...}, ...},  # sparse
          "lifetime_totals": {cat: total, ...},            # sorted desc
        }
    """
    if not DB_PATH.exists():
        return {"months": [], "by_category": {}, "lifetime_totals": {}}
    with _connect() as conn:
        rows = conn.execute(
            """SELECT substr(date, 1, 7) AS month,
                      category,
                      SUM(amount)        AS total
               FROM transactions
               GROUP BY month, category
               ORDER BY month ASC"""
        ).fetchall()

    filter_set = set(selected_months) if selected_months is not None else None

    months: list[str] = []
    seen_months: set[str] = set()
    by_category: dict[str, dict[str, float]] = {}
    lifetime: dict[str, float] = {}
    for r in rows:
        m, cat, total = r["month"], r["category"], float(r["total"])
        if filter_set is not None and m not in filter_set:
            continue
        if m not in seen_months:
            seen_months.add(m)
            months.append(m)
        by_category.setdefault(cat, {})[m] = total
        lifetime[cat] = lifetime.get(cat, 0.0) + total
    lifetime = dict(sorted(lifetime.items(), key=lambda kv: kv[1], reverse=True))
    # Drop categories that have no rows in the selection.
    by_category = {k: v for k, v in by_category.items() if k in lifetime}
    return {"months": months, "by_category": by_category, "lifetime_totals": lifetime}
