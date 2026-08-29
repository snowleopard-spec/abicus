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
