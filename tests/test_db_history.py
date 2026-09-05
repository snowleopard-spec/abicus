"""Unit tests for the outflows DB commit history (V3 Feature A, M1/M3).

Everything runs against tmp_path DBs and history repos — the real
data/ folder is never touched (history defaults to a sibling of the DB
path, which every test points into tmp_path).
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from abicus.apps.outflows import db, db_history


def _seed(monkeypatch, tmp_path, rows=None):
    """Point db.DB_PATH into tmp_path and optionally seed rows."""
    db_path = tmp_path / "transactions.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    if rows:
        # Seed WITHOUT the checkpoint hook firing twice mattering — the
        # hook is exercised in the route tests; here we drive checkpoints
        # explicitly, so seed via raw SQL.
        conn = sqlite3.connect(db_path)
        conn.executescript(db.SCHEMA)
        for i, r in enumerate(rows):
            conn.execute(
                f"INSERT INTO transactions ({', '.join(db.ROW_COLS)}) "
                f"VALUES ({', '.join('?' * len(db.ROW_COLS))})",
                tuple(r.get(c) for c in db.ROW_COLS),
            )
        conn.commit()
        conn.close()
    return db_path, tmp_path / "history"


ROW_A = {
    "tx_hash": "a" * 64, "date": "2026-08-01", "description": "NTUC",
    "amount": 12.5, "category": "Groceries", "account": "A",
    "matched_pattern": None, "source_file": "f.xlsx",
    "committed_at": "2026-08-01T00:00:00",
}
ROW_B = {
    "tx_hash": "b" * 64, "date": "2026-08-02", "description": "KFC — O'Chicken",
    "amount": 8.0, "category": "Dining", "account": "A",
    "matched_pattern": None, "source_file": "f.xlsx",
    "committed_at": "2026-08-02T00:00:00",
}


def test_checkpoint_initialises_and_commits(monkeypatch, tmp_path):
    db_path, hist = _seed(monkeypatch, tmp_path, [ROW_A])
    assert db_history.checkpoint("upsert: +1 inserted, 0 updated (total 1)")
    assert (hist / ".git").exists()
    entries = db_history.log()
    assert [e["label"] for e in entries] == [
        "upsert: +1 inserted, 0 updated (total 1)"
    ]
    # No remote, ever (R2).
    import subprocess
    remotes = subprocess.run(
        ["git", "-C", str(hist), "remote", "-v"],
        capture_output=True, text=True,
    ).stdout
    assert remotes.strip() == ""


def test_identical_state_commits_nothing(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, [ROW_A])
    assert db_history.checkpoint("first") is True
    assert db_history.checkpoint("second, same state") is False
    assert [e["label"] for e in db_history.log()] == ["first"]


def test_dump_is_deterministic_and_ordered(monkeypatch, tmp_path):
    db_path, _ = _seed(monkeypatch, tmp_path, [ROW_B, ROW_A])
    dump1 = db_history._dump_sql(db_path)
    dump2 = db_history._dump_sql(db_path)
    assert dump1 == dump2
    lines = [l for l in dump1.splitlines() if l.startswith("INSERT")]
    assert len(lines) == 2
    assert "a" * 64 in lines[0] and "b" * 64 in lines[1]  # tx_hash order
    # Quote-escaping survives a round trip through executescript.
    assert "O''Chicken" in dump1


def test_git_missing_warns_and_stands(monkeypatch, tmp_path, caplog):
    _seed(monkeypatch, tmp_path, [ROW_A])
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with caplog.at_level(logging.WARNING, logger="abicus.outflows.db_history"):
        assert db_history.checkpoint("doomed") is False
    assert "CHECKPOINT FAILED" in caplog.text
    assert db_history.log() == []  # no repo was created


def test_log_show_diff(monkeypatch, tmp_path):
    db_path, hist = _seed(monkeypatch, tmp_path, [ROW_A])
    db_history.checkpoint("one row")
    # Mutate: add B, change A's category.
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"INSERT INTO transactions ({', '.join(db.ROW_COLS)}) "
        f"VALUES ({', '.join('?' * len(db.ROW_COLS))})",
        tuple(ROW_B.get(c) for c in db.ROW_COLS),
    )
    conn.execute(
        "UPDATE transactions SET category = 'Dining' WHERE tx_hash = ?",
        (ROW_A["tx_hash"],),
    )
    conn.commit()
    conn.close()
    db_history.checkpoint("mutate")

    entries = db_history.log()
    assert [e["label"] for e in entries] == ["mutate", "one row"]

    first = entries[1]
    assert "INSERT INTO transactions" in db_history.show(first["sha8"])

    d = db_history.diff(entries[0]["sha"])
    assert [r["description"] for r in d["added"]] == ["KFC — O'Chicken"]
    assert d["removed"] == []
    assert len(d["changed"]) == 1
    assert d["changed"][0]["before"]["category"] == "Groceries"
    assert d["changed"][0]["after"]["category"] == "Dining"
    # First commit diffs against an empty state.
    d0 = db_history.diff(first["sha"])
    assert [r["tx_hash"] for r in d0["added"]] == [ROW_A["tx_hash"]]


def test_bad_ref_rejected(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path, [ROW_A])
    db_history.checkpoint("x")
    for bad in ("HEAD", "HEAD^", "--help", "main", "x" * 41, ""):
        with pytest.raises(ValueError):
            db_history.show(bad)


def test_restore_round_trips(monkeypatch, tmp_path):
    """M3 done-when: clear() then restore round-trips byte-identically,
    with a pre-restore snapshot and a `restore → <sha8>` commit."""
    db_path, _ = _seed(monkeypatch, tmp_path, [ROW_A, ROW_B])
    db_history.checkpoint("good state")
    good_dump = db_history._dump_sql(db_path)
    good_sha = db_history.log()[0]["sha8"]

    db.clear()  # the checkpoint hook records this too (M2)

    result = db_history.restore(good_sha)
    assert result == {"restored_to": good_sha, "rows": 2}
    assert db_history._dump_sql(db_path) == good_dump
    assert len(db.list_rows()) == 2

    labels = [e["label"] for e in db_history.log()]
    assert labels[0] == f"restore → {good_sha}"
    assert "pre-restore snapshot" in labels

    # Restoring a restore works: go back to the empty state.
    empty_sha = next(
        e["sha8"] for e in db_history.log() if e["label"].startswith("clear")
    )
    result = db_history.restore(empty_sha)
    assert result["rows"] == 0
    assert db.list_rows() == []
