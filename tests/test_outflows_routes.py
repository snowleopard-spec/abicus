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
