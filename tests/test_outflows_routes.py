import pandas as pd
from fastapi.testclient import TestClient

EXPECTED = {
    "/api/outflows/config",
    "/api/outflows/compile",
    "/api/outflows/download/categorised/{session_id}",
    "/api/outflows/download/unmapped/{session_id}",
    "/api/outflows/download/html/{session_id}",
    "/api/outflows/history/append/{session_id}",
    "/api/outflows/history/categorise/{session_id}",
    "/api/outflows/mapping/add-rule/{session_id}",
}


def test_outflows_has_all_legacy_routes(all_paths):
    missing = EXPECTED - all_paths
    assert not missing, f"missing routes: {missing}"


def test_history_categorise(app, tmp_path, monkeypatch):
    """+H flow: upserts the row into transaction_history.xlsx and
    recategorises every matching unmapped row in the live session."""
    from abicus.apps.outflows import router as outflows
    from abicus.apps.outflows.transaction_history import load_history_dataframe

    hist = tmp_path / "transaction_history.xlsx"
    monkeypatch.setattr(outflows, "HISTORY_PATH", hist)
    monkeypatch.setattr(
        outflows, "load_categories", lambda: ({"Groceries", "Misc"}, set())
    )

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03"]),
        "description": ["NTUC FP-BEDOK", "ntuc fp-bedok ", "COLD STORAGE"],
        "amount": [12.5, 8.0, 20.0],
        "account": ["A", "A", "A"],
        "category": ["Uncategorised", "Uncategorised", "Groceries"],
        "matched_pattern": ["", "", "cold storage"],
        "duplicate": [False, False, False],
        "pre_categorised": [False, False, False],
    })
    session = {"df": df, "payload": {"rows": outflows._df_to_records(df)}}
    outflows.SESSIONS["test-hist-cat"] = session
    try:
        c = TestClient(app)
        url = "/api/outflows/history/categorise/test-hist-cat"

        r = c.post(url, json={"row_idx": 0, "category": "Groceries"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "added"
        # Both unmapped rows share the description (case/space-insensitive).
        assert sorted(body["updated_idx"]) == [0, 1]
        assert list(df["category"]) == ["Groceries"] * 3
        assert df.loc[0, "matched_pattern"] == "NTUC FP-BEDOK"
        # Cached session payload rebuilt so restore-after-refresh sees it.
        assert session["payload"]["rows"][1]["category"] == "Groceries"
        # One history row, categorised.
        h = load_history_dataframe(hist)
        assert len(h) == 1
        assert h.iloc[0]["category"] == "Groceries"

        # Unknown category → 400, nothing written.
        r = c.post(url, json={"row_idx": 2, "category": "Nope"})
        assert r.status_code == 400

        # Row no longer unmapped → 400.
        r = c.post(url, json={"row_idx": 2, "category": "Misc"})
        assert r.status_code == 400

        # Out-of-range index → 400.
        r = c.post(url, json={"row_idx": 99, "category": "Misc"})
        assert r.status_code == 400
    finally:
        outflows.SESSIONS.pop("test-hist-cat", None)


def test_mapping_add_rule(app, tmp_path, monkeypatch):
    """Highlight-to-map flow: upserts a substring rule into mapping.xlsx +
    mapping.json and recategorises matching unmapped session rows."""
    import json

    from abicus.apps.outflows import build_mapping, router as outflows

    monkeypatch.setattr(build_mapping, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(build_mapping, "MAPPING_XLSX", tmp_path / "mapping.xlsx")
    monkeypatch.setattr(build_mapping, "MAPPING_JSON", tmp_path / "mapping.json")
    monkeypatch.setattr(
        outflows, "load_categories", lambda: ({"Groceries", "Misc"}, set())
    )

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03"]),
        "description": ["NTUC FP-BEDOK", "FAIRPRICE NTUC MALL", "COLD STORAGE"],
        "amount": [12.5, 8.0, 20.0],
        "account": ["A", "A", "A"],
        "category": ["Uncategorised", "Uncategorised", "Groceries"],
        "matched_pattern": ["", "", "cold storage"],
        "duplicate": [False, False, False],
        "pre_categorised": [False, False, False],
    })
    session = {"df": df, "payload": {"rows": outflows._df_to_records(df)}}
    outflows.SESSIONS["test-map-rule"] = session
    try:
        c = TestClient(app)
        url = "/api/outflows/mapping/add-rule/test-map-rule"

        r = c.post(url, json={"substring": " NTUC ", "category": "Groceries"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "added"
        assert body["substring"] == "ntuc"
        assert sorted(body["updated_idx"]) == [0, 1]
        assert list(df["category"]) == ["Groceries"] * 3
        assert df.loc[0, "matched_pattern"] == "ntuc"
        assert session["payload"]["rows"][1]["category"] == "Groceries"
        # Rule written to both files, lowercased in the JSON.
        assert (tmp_path / "mapping.xlsx").exists()
        mapping = json.loads((tmp_path / "mapping.json").read_text())
        assert mapping == {"ntuc": "Groceries"}

        # Same substring, different category → rule re-pointed, no rows left
        # to recategorise.
        r = c.post(url, json={"substring": "ntuc", "category": "Misc"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "updated"
        assert body["updated_idx"] == []
        mapping = json.loads((tmp_path / "mapping.json").read_text())
        assert mapping == {"ntuc": "Misc"}

        # Same substring, same category → no-op.
        r = c.post(url, json={"substring": "NTUC", "category": "Misc"})
        assert r.status_code == 200 and r.json()["status"] == "unchanged"

        # Too short / unknown category → 400.
        r = c.post(url, json={"substring": "x", "category": "Misc"})
        assert r.status_code == 400
        r = c.post(url, json={"substring": "storage", "category": "Nope"})
        assert r.status_code == 400
    finally:
        outflows.SESSIONS.pop("test-map-rule", None)


def test_categorise_is_whitespace_insensitive():
    """Statement exports pad fields with space runs and newlines that
    collapse when rendered; a rule highlighted from the rendered text
    (single spaces) must still match the raw description."""
    from abicus.apps.outflows.categorise import categorise

    raw = "EVERYDAY APP             SINGAPORE    SG\nRef No: 74143256232100043940260"
    cat, pattern = categorise(raw, {"everyday app singapore": "School Fees"})
    assert cat == "School Fees"
    assert pattern == "everyday app singapore"
    # History exact-match layer normalises the same way.
    cat, _ = categorise(
        "EVERYDAY  APP  SINGAPORE  SG", {}, {"everyday app singapore sg": "Misc"}
    )
    assert cat == "Misc"


def test_config_accounts_carry_labels(app):
    """Every account entry exposes a non-empty labels list. (Names need
    not appear in their own labels — an account name may be a grouping
    like 'UOB' whose labels are the individual cards.)"""
    c = TestClient(app)
    r = c.get("/api/outflows/config")
    assert r.status_code == 200
    accounts = r.json()["accounts"]
    assert accounts, "expected at least one account"
    for a in accounts:
        assert a["labels"], a


def test_load_accounts_labels_default_to_name(tmp_path):
    """An entry without a 'labels' key defaults to [name]."""
    from abicus.apps.outflows.accounts import load_accounts

    p = tmp_path / "accounts.yaml"
    p.write_text(
        'accounts:\n  - name: "Solo Card"\n    format: "Format A"\n'
    )
    m = load_accounts(p)
    assert m == {"Solo Card": {"format": "Format A", "labels": ["Solo Card"]}}


def test_compile_rejects_label_not_allowed_for_account(app, monkeypatch):
    """A label may only be used if it is in the account's permissible
    labels list from accounts.yaml."""
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(
        outflows, "load_accounts",
        lambda valid_formats=None: {
            "Amex PPS": {"format": "Format A", "labels": ["Amex PPS"]},
            "UOB One Card": {
                "format": "Format C",
                "labels": ["UOB One Card", "UOB One (household)"],
            },
        },
    )
    monkeypatch.setattr(
        outflows, "build_mapping_if_changed", lambda: (False, 0, [])
    )

    c = TestClient(app)
    r = c.post(
        "/api/outflows/compile",
        files=[("files", ("stmt.csv", b"dummy", "text/csv"))],
        data={"accounts": ["UOB One Card"], "labels": ["Amex PPS"]},
    )
    assert r.status_code == 400
    assert "not an allowed label for account 'UOB One Card'" in r.json()["detail"]
    assert "UOB One (household)" in r.json()["detail"]

    r = c.post(
        "/api/outflows/compile",
        files=[("files", ("stmt.csv", b"dummy", "text/csv"))],
        data={"accounts": ["Nope"], "labels": ["Nope"]},
    )
    assert r.status_code == 400
    assert "Unknown account" in r.json()["detail"]


def test_detect_endpoint(app, monkeypatch):
    """/detect try-parses against every registered parser and only commits
    to an answer when exactly one format (and one account) matches."""
    from abicus.apps.outflows import router as outflows

    def ok(file_bytes, filename):
        return "parsed"

    def fail(file_bytes, filename):
        raise ValueError("wrong headers")

    def crash(file_bytes, filename):
        raise RuntimeError("unreadable bytes")

    accounts = {
        "UOB": {"format": "Format C", "labels": ["UOB One Card"]},
        "Amex": {"format": "Format A", "labels": ["Amex PPS"]},
    }
    monkeypatch.setattr(
        outflows, "load_accounts", lambda valid_formats=None: accounts
    )
    c = TestClient(app)
    post = lambda: c.post(
        "/api/outflows/detect",
        files={"file": ("stmt.csv", b"dummy", "text/csv")},
    )

    # Exactly one parser accepts → format + account.
    monkeypatch.setattr(
        outflows, "PARSERS",
        {"Format A": fail, "Format C": ok, "Format D": crash},
    )
    body = post().json()
    assert body == {
        "format": "Format C", "account": "UOB", "candidates": ["Format C"],
    }

    # Nothing accepts (new/unknown format) → all null.
    monkeypatch.setattr(
        outflows, "PARSERS", {"Format A": fail, "Format C": crash}
    )
    body = post().json()
    assert body == {"format": None, "account": None, "candidates": []}

    # Two accept → ambiguous, no auto-pick.
    monkeypatch.setattr(
        outflows, "PARSERS", {"Format A": ok, "Format C": ok}
    )
    body = post().json()
    assert body["format"] is None and body["account"] is None
    assert body["candidates"] == ["Format A", "Format C"]

    # One format, but two accounts share it → format reported, account null.
    monkeypatch.setattr(outflows, "PARSERS", {"Format C": ok})
    monkeypatch.setattr(
        outflows, "load_accounts",
        lambda valid_formats=None: {
            "UOB": {"format": "Format C", "labels": ["UOB One Card"]},
            "UOB2": {"format": "Format C", "labels": ["UOB Black Card"]},
        },
    )
    body = post().json()
    assert body["format"] == "Format C" and body["account"] is None


def test_detect_manual_template_wins_over_format_a(app):
    """Regression, with the REAL parsers (the stubbed test above can't see
    parser overlap): a manual-template xlsx is accepted by both Format A's
    30-row header scan and Format F's row-0 header, and the precedence
    tie-break must resolve it to Format F instead of reporting ambiguous."""
    import io

    buf = io.BytesIO()
    pd.DataFrame({
        "date": ["2026-08-01", "2026-08-02"],
        "description": ["NTUC", "KFC"],
        "amount": [12.5, 8.0],
        "category": ["Groceries", "Dining"],
        "account": ["Manual", "Manual"],
    }).to_excel(buf, index=False)

    c = TestClient(app)
    body = c.post(
        "/api/outflows/detect",
        files={"file": (
            "manual.xlsx", buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    ).json()
    assert set(body["candidates"]) == {"Format A", "Format F"}
    assert body["format"] == "Format F"


def test_state_save_load_roundtrip(app, tmp_path, monkeypatch):
    """Save a session as a state file, list it, load it into a fresh
    session with df and UI state intact; delete it; reject traversal."""
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(outflows, "STATES_DIR", tmp_path)

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02"]),
        "description": ["SHOP A", "REFUND B"],
        "amount": [10.0, -3.0],
        "account": ["A", "A"],
        "category": ["Groceries", "Groceries"],
        "matched_pattern": ["shop a", "refund"],
        "source_file": ["aug.xls", "aug.xls"],
        "duplicate": [False, False],
        "refund": [False, True],
        "pre_categorised": [False, False],
    })
    payload = {
        "session_id": "orig",
        "rows": outflows._df_to_records(df),
        "duplicates_count": 0,
        "dropped_negatives": 1,
    }
    outflows.SESSIONS["test-state"] = {"df": df, "payload": payload}
    ui = {
        "dateRange": {"from": "2026-08-01", "to": "2026-08-31"},
        "tableFilter": {"category": "All", "account": "A", "search": "x", "matched": True},
        "reincludedRef": [1],
    }
    try:
        c = TestClient(app)
        r = c.post("/api/outflows/state/save/test-state",
                   json={"label": "Aug close", "ui": ui})
        assert r.status_code == 200, r.text
        assert r.json() == {"file": "Aug close.json", "label": "Aug close", "n_rows": 2}

        r = c.get("/api/outflows/state/list")
        states = r.json()["states"]
        assert len(states) == 1 and states[0]["label"] == "Aug close"

        r = c.post("/api/outflows/state/load", json={"file": "Aug close.json"})
        assert r.status_code == 200, r.text
        body = r.json()
        sid = body["session"]["session_id"]
        assert sid != "orig" and sid in outflows.SESSIONS
        # UI round-trips (defaults filled for unsent fields).
        assert body["ui"]["reincludedRef"] == [1]
        assert body["ui"]["tableFilter"]["search"] == "x"
        assert body["meta"]["source_files"] == ["aug.xls"]
        # The rebuilt df has proper dtypes.
        df2 = outflows.SESSIONS[sid]["df"]
        assert list(df2["refund"]) == [False, True]
        assert str(df2["date"].dtype).startswith("datetime64")
        outflows.SESSIONS.pop(sid, None)

        # Traversal / bad names rejected.
        r = c.post("/api/outflows/state/load", json={"file": "../evil.json"})
        assert r.status_code == 400
        r = c.post("/api/outflows/state/delete", json={"file": "nope.json"})
        assert r.status_code == 404

        r = c.post("/api/outflows/state/delete", json={"file": "Aug close.json"})
        assert r.status_code == 200
        assert c.get("/api/outflows/state/list").json()["states"] == []
    finally:
        outflows.SESSIONS.pop("test-state", None)


def test_db_commit_honours_manual_exclusions(app, monkeypatch):
    """Rows excluded by hand via the × button (excluded_row_idx) are
    dropped from the committed view."""
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(outflows, "load_categories", lambda: ({"Groceries"}, set()))
    captured = {}

    def fake_upsert(payload):
        captured["payload"] = payload
        return {"inserted": len(payload), "updated": 0, "total_in_db": len(payload)}

    monkeypatch.setattr(outflows.db, "upsert", fake_upsert)

    df = pd.DataFrame({
        "date": pd.to_datetime(
            ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
        ),
        "description": ["KEEP ME", "EXCLUDE ME", "KEEP ME TOO", "REFUND"],
        "amount": [1.0, 2.0, 3.0, -4.0],
        "account": ["A", "A", "A", "A"],
        "category": ["Groceries"] * 4,
        "matched_pattern": ["x"] * 4,
        "source_file": ["f"] * 4,
        "duplicate": [False] * 4,
        "refund": [False, False, False, True],
        "pre_categorised": [False] * 4,
    })
    outflows.SESSIONS["test-commit-excl"] = {"df": df}
    try:
        c = TestClient(app)
        # Refunds are hidden by default; row 1 excluded by hand.
        r = c.post("/api/outflows/db/commit/test-commit-excl", json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "excluded_row_idx": [1],
        })
        assert r.status_code == 200, r.text
        assert r.json()["inserted"] == 2
        descs = [row["description"] for row in captured["payload"]]
        assert descs == ["KEEP ME", "KEEP ME TOO"]

        # A re-included refund is committed.
        r = c.post("/api/outflows/db/commit/test-commit-excl", json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "reincluded_refund_idx": [3],
        })
        assert r.status_code == 200, r.text
        descs = [row["description"] for row in captured["payload"]]
        assert descs == ["KEEP ME", "EXCLUDE ME", "KEEP ME TOO", "REFUND"]
    finally:
        outflows.SESSIONS.pop("test-commit-excl", None)


def test_db_edit_endpoints(app, tmp_path, monkeypatch):
    """DB Edit flow: list rows, edit a category in place, delete a row and
    restore it verbatim via the undo payload."""
    from abicus.apps.outflows import db
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    monkeypatch.setattr(
        outflows, "load_categories", lambda: ({"Groceries", "Dining"}, set())
    )

    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
        {"date": "2026-08-02", "description": "KFC", "amount": 8.0,
         "category": "Dining", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])

    c = TestClient(app)

    r = c.get("/api/outflows/db/rows")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["description"] for row in body["rows"]] == ["KFC", "NTUC"]
    assert body["categories"] == ["Dining", "Groceries"]
    ntuc = body["rows"][1]

    # Edit a category in place.
    r = c.post("/api/outflows/db/update-category",
               json={"tx_hash": ntuc["tx_hash"], "category": "Dining"})
    assert r.status_code == 200, r.text
    rows = c.get("/api/outflows/db/rows").json()["rows"]
    assert all(row["category"] == "Dining" for row in rows)

    # Unknown category → 400; unknown hash → 404.
    r = c.post("/api/outflows/db/update-category",
               json={"tx_hash": ntuc["tx_hash"], "category": "Nope"})
    assert r.status_code == 400
    r = c.post("/api/outflows/db/update-category",
               json={"tx_hash": "deadbeef", "category": "Dining"})
    assert r.status_code == 404

    # Delete returns the full row for undo.
    r = c.post("/api/outflows/db/delete-row", json={"tx_hash": ntuc["tx_hash"]})
    assert r.status_code == 200, r.text
    deleted = r.json()["deleted"]
    assert deleted["description"] == "NTUC"
    assert deleted["category"] == "Dining"
    assert len(c.get("/api/outflows/db/rows").json()["rows"]) == 1

    # Deleting the same hash again → 404.
    r = c.post("/api/outflows/db/delete-row", json={"tx_hash": ntuc["tx_hash"]})
    assert r.status_code == 404

    # Restore re-inserts it verbatim — same tx_hash, same committed_at.
    r = c.post("/api/outflows/db/restore-row", json={"row": deleted})
    assert r.status_code == 200, r.text
    rows = c.get("/api/outflows/db/rows").json()["rows"]
    assert len(rows) == 2
    restored = next(row for row in rows if row["tx_hash"] == ntuc["tx_hash"])
    assert restored["committed_at"] == deleted["committed_at"]

    # Restore with a gutted payload → 400.
    r = c.post("/api/outflows/db/restore-row", json={"row": {"tx_hash": "x"}})
    assert r.status_code == 400

    # Every write above landed one labelled commit in the history repo,
    # in operation order (newest first); the failed edits committed nothing.
    from abicus.apps.outflows import db_history

    h8 = ntuc["tx_hash"][:8]
    labels = [e["label"] for e in db_history.log()]
    assert labels == [
        f"restore_row {h8}",
        f"delete_row {h8}",
        f"update_category {h8}: → Dining",
        "upsert: +2 inserted, 0 updated (total 2)",
    ]
    assert (tmp_path / "history" / ".git").exists()


def test_db_backup_endpoint(app, tmp_path, monkeypatch):
    """POST /db/backup writes a readable snapshot into data/backups/."""
    import sqlite3

    from abicus.apps.outflows import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])

    c = TestClient(app)
    r = c.post("/api/outflows/db/backup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == 1 and body["bytes"] > 0
    snap = tmp_path / "backups" / body["file"]
    assert snap.exists()
    assert body["path"] == str(snap.resolve())
    rows = sqlite3.connect(snap).execute(
        "SELECT description FROM transactions"
    ).fetchall()
    assert rows == [("NTUC",)]


def test_db_history_endpoints(app, tmp_path, monkeypatch):
    """History panel flow: list commits with change summaries, view a
    commit's diff, roll back from the GUI route (rows revert, a
    `restore → <sha8>` commit tops the log), and restore a restore."""
    from abicus.apps.outflows import db, db_history

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])
    good_sha = db_history.log()[0]["sha8"]
    db.update_category(db.list_rows()[0]["tx_hash"], "Dining")

    c = TestClient(app)

    # List: newest first, with per-commit change summaries.
    r = c.get("/api/outflows/db/history")
    assert r.status_code == 200, r.text
    commits = r.json()["commits"]
    assert [x["label"].split(" ")[0] for x in commits] == [
        "update_category", "upsert:"
    ]
    assert commits[0]["summary"] == {"added": 0, "removed": 0, "changed": 1}
    assert commits[1]["summary"] == {"added": 1, "removed": 0, "changed": 0}
    assert [x["rows"] for x in commits] == [1, 1]  # DB size at each commit

    # Diff: the category edit shows before/after rows.
    r = c.get(f"/api/outflows/db/history/diff/{commits[0]['sha8']}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["changed"][0]["before"]["category"] == "Groceries"
    assert d["changed"][0]["after"]["category"] == "Dining"

    # Bad ref syntax → 400; unknown commit → 404.
    assert c.get("/api/outflows/db/history/diff/HEAD").status_code == 400
    assert c.get("/api/outflows/db/history/diff/deadbeef").status_code == 404

    # Roll back the edit from the GUI route.
    r = c.post("/api/outflows/db/history/restore", json={"ref": good_sha})
    assert r.status_code == 200, r.text
    assert r.json() == {"restored_to": good_sha, "rows": 1}
    assert db.list_rows()[0]["category"] == "Groceries"
    latest = db_history.log()[0]
    assert latest["label"] == f"restore → {good_sha}"

    # Restoring a restore: go forward again to the edited state.
    edited_sha = next(
        e["sha8"] for e in db_history.log()
        if e["label"].startswith("update_category")
    )
    r = c.post("/api/outflows/db/history/restore", json={"ref": edited_sha})
    assert r.status_code == 200, r.text
    assert db.list_rows()[0]["category"] == "Dining"
    assert db_history.log()[0]["label"] == f"restore → {edited_sha}"


def test_breakdown_transactions(app, tmp_path, monkeypatch):
    """Per-bar drill-down: a month+category query returns just that bar's
    rows; omitting category returns the whole month; bad months 400."""
    from abicus.apps.outflows import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
        {"date": "2026-08-02", "description": "KFC", "amount": 8.0,
         "category": "Dining", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
        {"date": "2026-07-15", "description": "NTUC", "amount": 20.0,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])

    c = TestClient(app)

    # One bar: month + category.
    r = c.get("/api/outflows/breakdown/transactions",
              params={"month": "2026-08", "category": "Groceries"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert [row["description"] for row in rows] == ["NTUC"]
    assert rows[0]["amount"] == 12.5

    # Monthly-total bar: month only, all categories, date-ascending.
    r = c.get("/api/outflows/breakdown/transactions",
              params={"month": "2026-08"})
    assert [row["description"] for row in r.json()["rows"]] == ["NTUC", "KFC"]

    # Empty result for a month with no rows.
    r = c.get("/api/outflows/breakdown/transactions",
              params={"month": "2025-01"})
    assert r.json()["rows"] == []

    # Malformed month → 400.
    r = c.get("/api/outflows/breakdown/transactions",
              params={"month": "Aug 2026"})
    assert r.status_code == 400


def test_breakdown_includes_category_types(app, tmp_path, monkeypatch):
    """The breakdown payload carries the category→type map (F/D/V/E/NA)
    alongside the per-month totals, for tile shading and type filters."""
    from abicus.apps.outflows import db
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])
    monkeypatch.setattr(
        outflows, "load_category_types", lambda: {"Groceries": "V", "Rent": "F"}
    )
    monkeypatch.setattr(
        outflows, "load_breakdown_config", lambda: {"show_exclude_toggle": False}
    )

    c = TestClient(app)
    r = c.get("/api/outflows/breakdown")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_types"] == {"Groceries": "V", "Rent": "F"}
    assert body["by_category"]["Groceries"]["2026-08"] == 12.5
    assert body["config"] == {"show_exclude_toggle": False}


def test_breakdown_config_loader(tmp_path, monkeypatch):
    """Missing file, bad JSON, or a wrong-typed value all fall back to the
    default; a valid false is honoured."""
    import json as _json

    from abicus.apps.outflows import breakdown_config

    cfg_path = tmp_path / "breakdown.json"
    monkeypatch.setattr(breakdown_config, "_CONFIG_PATH", cfg_path)

    assert breakdown_config.load_breakdown_config() == {"show_exclude_toggle": True}

    cfg_path.write_text("not json {")
    assert breakdown_config.load_breakdown_config() == {"show_exclude_toggle": True}

    cfg_path.write_text(_json.dumps({"show_exclude_toggle": "no"}))
    assert breakdown_config.load_breakdown_config() == {"show_exclude_toggle": True}

    cfg_path.write_text(_json.dumps({"show_exclude_toggle": False}))
    assert breakdown_config.load_breakdown_config() == {"show_exclude_toggle": False}


def test_breakdown_html_export(app, tmp_path, monkeypatch):
    """The self-contained export embeds the DB rows and vendored libs and
    references no external scripts or stylesheets."""
    import re as _re

    from abicus.apps.outflows import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "transactions.db")
    db.upsert([
        {"date": "2026-08-01", "description": "NTUC", "amount": 12.5,
         "category": "Groceries", "account": "A", "matched_pattern": None,
         "source_file": "f.xlsx"},
    ])

    c = TestClient(app)
    r = c.get("/api/outflows/breakdown/html")
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    html = r.text
    assert "window.__ABICUS_EXPORT__" in html
    assert "NTUC" in html
    # The embedded payload mirrors the live endpoint, types included.
    assert '"category_types"' in html
    assert "plotly.js v2.35.2" in html
    assert "Tabulator v6.3.1" in html
    # Self-contained: no external script/link tags at all.
    assert not _re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', html)
