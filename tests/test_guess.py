"""Unit tests for the category-guess engine (outflows/guess.py) and its
API endpoint. The scoring assertions double as the contract for a future
rapidfuzz swap (see abicus/documentation/RAPIDFUZZ_SPEC.md) — they must pass
unchanged if the engine is replaced."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from abicus.apps.outflows.guess import (
    GuessConfig,
    best_guess,
    build_corpus,
    distance,
    lcs_len,
    load_guess_config,
    normalise,
    score,
)


def test_normalise():
    assert normalise("NTUC FP-BEDOK S3411 REF 882") == "ntuc fp-bedok s ref"
    assert normalise("  A   B  ") == "a b"
    assert normalise("12345") == ""


def test_distance_free_deletions():
    # Deleting query characters is free: extra junk costs nothing.
    assert distance("ntuc fp-bedok ref", "ntuc fp-bedok") == 0
    assert score("ntuc fp-bedok ref", "ntuc fp-bedok") == 1.0
    # Substitutions cost 1 each.
    assert distance("abc", "abd") == 1
    # Candidate characters absent from the query all cost.
    assert distance("xyz", "abc") == 3
    assert lcs_len("", "abc") == 0


def test_engine_matches_pure_python_reference():
    """RAPIDFUZZ_SPEC.md §4: the rapidfuzz engine must compute costs
    identical to the pure-Python reference (len(candidate) − LCS) over a
    random sample."""
    import random

    rng = random.Random(42)
    alphabet = "abcdefghij -x"
    for _ in range(300):
        q = "".join(rng.choices(alphabet, k=rng.randint(0, 30)))
        c = "".join(rng.choices(alphabet, k=rng.randint(1, 25)))
        assert distance(q, c) == len(c) - lcs_len(q, c), (q, c)


def test_best_guess_threshold_and_min_length():
    corpus = {
        "ntuc fp-bedok": ("Groceries", "NTUC FP-BEDOK"),
        "grab": ("Transport", "GRAB"),
    }
    cfg = GuessConfig(min_score=0.9, min_candidate_length=5)
    # Noisy variant of a known description clears the bar.
    g = best_guess("NTUC FP-BEDOK S3411 REF", corpus, cfg)
    assert g == {"category": "Groceries", "matched": "NTUC FP-BEDOK", "score": 1.0}
    # 'grab' is under min_candidate_length — never offered, even though
    # g-r-a-b appears in order here (the short-candidate trap).
    assert best_guess("GARDEN BAR B", corpus, cfg) is None
    # Nothing similar → no guess.
    assert best_guess("STARBUCKS ORCHARD", corpus, cfg) is None


def test_best_guess_prefers_higher_score_then_longer():
    corpus = {
        "cold storage": ("Groceries", "COLD STORAGE"),
        "cold storage online": ("Durables", "COLD STORAGE ONLINE"),
    }
    cfg = GuessConfig(min_score=0.8, min_candidate_length=5)
    g = best_guess("COLD STORAGE ONLINE 123", corpus, cfg)
    # Both score 1.0; the longer (more specific) candidate wins.
    assert g["category"] == "Durables"


def test_build_corpus_history_wins_and_filters():
    corpus = build_corpus(
        db_pairs=[("SHOP A", "Misc"), ("SHOP B", "Uncategorised"), ("SHOP C", "Ghost")],
        history_pairs=[("shop a", "Groceries")],
        valid_categories={"Misc", "Groceries"},
    )
    # History overrides the DB for the same normalised description.
    assert corpus["shop a"][0] == "Groceries"
    # Uncategorised and invalid categories are dropped.
    assert "shop b" not in corpus and "shop c" not in corpus


def test_load_guess_config(tmp_path):
    # Missing file → defaults.
    cfg = load_guess_config(tmp_path / "nope.yaml")
    assert cfg.min_score == 0.90 and cfg.min_candidate_length == 5
    # Partial file → missing keys default.
    p = tmp_path / "guess.yaml"
    p.write_text("min_score: 0.8\n")
    assert load_guess_config(p) == GuessConfig(min_score=0.8)
    # Invalid values raise.
    p.write_text("min_score: 1.5\n")
    with pytest.raises(ValueError):
        load_guess_config(p)


def test_guess_endpoint(app, monkeypatch):
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(
        outflows.db, "load_description_categories",
        lambda: [("NTUC FP-BEDOK", "Groceries")],
    )
    monkeypatch.setattr(
        outflows, "load_history_mapping",
        lambda path, valid_categories=None: ({"cold storage": "Groceries"}, []),
    )
    monkeypatch.setattr(outflows, "load_categories", lambda: ({"Groceries"}, set()))

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03"]),
        "description": ["NTUC FP-BEDOK S9999", "TOTALLY NEW SHOP", "COLD STORAGE"],
        "amount": [1.0, 2.0, 3.0],
        "account": ["A", "A", "A"],
        "category": ["Uncategorised", "Uncategorised", "Groceries"],
        "matched_pattern": ["", "", "cold storage"],
        "duplicate": [False, False, False],
        "pre_categorised": [False, False, False],
    })
    # Transformer engine off: the rapidfuzz pills must be unaffected and
    # the response must carry the install hint (R7 degradation).
    monkeypatch.setattr(outflows.guess_embed, "available", lambda: False)

    outflows.SESSIONS["test-guess"] = {"df": df}
    try:
        c = TestClient(app)
        r = c.post("/api/outflows/guess/test-guess")
        assert r.status_code == 200, r.text
        body = r.json()
        guesses = body["guesses"]
        # Row 0 matches its noisy variant; row 1 gets no guess; row 2 is
        # already categorised so it is not scored at all.
        assert set(guesses) == {"0"}
        assert guesses["0"]["rapidfuzz"]["category"] == "Groceries"
        assert guesses["0"]["rapidfuzz"]["matched"] == "NTUC FP-BEDOK"
        assert guesses["0"]["rapidfuzz"]["score"] == 1.0
        assert guesses["0"]["transformer"] is None
        assert body["transformer"]["available"] is False
        assert "suggest" in body["transformer"]["hint"]
    finally:
        outflows.SESSIONS.pop("test-guess", None)


def test_guess_endpoint_both_engines(app, monkeypatch):
    """With the transformer engine available (stubbed), each row carries
    per-engine blocks — including a transformer-only guess on a row
    rapidfuzz can't match."""
    from abicus.apps.outflows import router as outflows

    monkeypatch.setattr(
        outflows.db, "load_description_categories",
        lambda: [("NTUC FP-BEDOK", "Groceries")],
    )
    monkeypatch.setattr(
        outflows, "load_history_mapping",
        lambda path, valid_categories=None: ({}, []),
    )
    monkeypatch.setattr(outflows, "load_categories", lambda: ({"Groceries"}, set()))
    monkeypatch.setattr(outflows.guess_embed, "available", lambda: True)

    def fake_batch(descs, corpus, cfg):
        by_meaning = {
            "COLD STORAGE": {
                "category": "Groceries", "matched": "NTUC FP-BEDOK",
                "score": 0.91,
            },
        }
        return [by_meaning.get(d) for d in descs]

    monkeypatch.setattr(outflows.guess_embed, "batch_guess", fake_batch)

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-01", "2026-08-02"]),
        "description": ["NTUC FP-BEDOK S9999", "COLD STORAGE"],
        "amount": [1.0, 2.0],
        "account": ["A", "A"],
        "category": ["Uncategorised", "Uncategorised"],
        "matched_pattern": ["", ""],
        "duplicate": [False, False],
        "pre_categorised": [False, False],
    })
    outflows.SESSIONS["test-guess-both"] = {"df": df}
    try:
        c = TestClient(app)
        body = c.post("/api/outflows/guess/test-guess-both").json()
        assert body["transformer"] == {"available": True, "hint": None}
        g = body["guesses"]
        assert g["0"]["rapidfuzz"]["category"] == "Groceries"
        assert g["0"]["transformer"] is None
        assert g["1"]["rapidfuzz"] is None  # no spelling overlap
        assert g["1"]["transformer"]["score"] == 0.91  # meaning match
    finally:
        outflows.SESSIONS.pop("test-guess-both", None)
