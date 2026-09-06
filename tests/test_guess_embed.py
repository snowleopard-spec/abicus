"""Unit tests for the transformer guess engine (outflows/guess_embed.py).

No model, no network: a fake encoder maps known strings to fixed unit
vectors, so nearest-neighbour behaviour and thresholds are exact. The
cache tests use a counting encoder to prove a second call with an
unchanged corpus does zero embedding work (M6 done-when).
"""

from __future__ import annotations

import builtins

import numpy as np
import pytest

from abicus.apps.outflows import guess_embed
from abicus.apps.outflows.guess import GuessConfig


# Unit vectors: ntuc/cold storage point the same way-ish; kfc is far away.
_VECS = {
    "ntuc fairprice": np.array([1.0, 0.0, 0.0]),
    "cold storage": np.array([0.9, 0.435889894354, 0.0]),  # cos vs ntuc ≈ 0.9
    "kfc": np.array([0.0, 0.0, 1.0]),
    "grab -eleven": np.array([0.95, 0.312249899919, 0.0]),  # cos vs ntuc ≈ 0.95
}


def fake_encode(texts):
    return np.stack([_VECS[t].astype(np.float32) for t in texts])


CORPUS = {
    "ntuc fairprice": ("Groceries", "NTUC FAIRPRICE"),
    "kfc": ("Dining", "KFC"),
}


def test_batch_guess_nearest_and_threshold(tmp_path):
    cfg = GuessConfig(embed_min_score=0.92)
    out = guess_embed.batch_guess(
        # "GRAB 7-ELEVEN" normalises to "grab -eleven" (digits dropped):
        # cosine 0.95 vs ntuc → clears 0.92. "COLD STORAGE" is 0.90 → below.
        ["GRAB 7-ELEVEN", "COLD STORAGE", "KFC 123"],
        CORPUS, cfg,
        encode=fake_encode, cache_path=tmp_path / "cache.npz",
    )
    assert out[0] == {
        "category": "Groceries", "matched": "NTUC FAIRPRICE", "score": 0.95,
    }
    assert out[1] is None
    assert out[2]["category"] == "Dining" and out[2]["score"] == 1.0


def test_empty_inputs(tmp_path):
    cfg = GuessConfig()
    assert guess_embed.batch_guess([], CORPUS, cfg, encode=fake_encode) == []
    assert guess_embed.batch_guess(
        ["x"], {}, cfg, encode=fake_encode,
    ) == [None]
    # Queries that normalise to nothing (pure digits) get no guess and
    # never reach the encoder.
    out = guess_embed.batch_guess(
        ["12345"], CORPUS, cfg,
        encode=lambda t: (_ for _ in ()).throw(AssertionError("encoded!")),
        cache_path=tmp_path / "cache.npz",
    )
    assert out == [None]


def test_corpus_cache_hit_and_invalidation(tmp_path):
    """Second call with an unchanged corpus embeds only the query; a
    changed corpus re-embeds it (cache keyed on content + model name)."""
    cache = tmp_path / "cache.npz"
    calls = []

    def counting_encode(texts):
        calls.append(list(texts))
        return fake_encode(texts)

    cfg = GuessConfig(embed_min_score=0.5)
    args = dict(encode=counting_encode, cache_path=cache)

    guess_embed.batch_guess(["KFC"], CORPUS, cfg, **args)
    assert calls == [["kfc", "ntuc fairprice"], ["kfc"]]  # corpus + query

    calls.clear()
    guess_embed.batch_guess(["KFC"], CORPUS, cfg, **args)
    assert calls == [["kfc"]]  # corpus served from cache — zero embed work

    calls.clear()
    grown = dict(CORPUS)
    grown["cold storage"] = ("Groceries", "COLD STORAGE")
    guess_embed.batch_guess(["KFC"], grown, cfg, **args)
    assert calls[0] == ["cold storage", "kfc", "ntuc fairprice"]  # re-embedded


def test_available_reflects_import(monkeypatch):
    assert isinstance(guess_embed.available(), bool)
    real_import = builtins.__import__

    def no_st(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_st)
    monkeypatch.delitem(
        __import__("sys").modules, "sentence_transformers", raising=False
    )
    assert guess_embed.available() is False


def test_embed_min_score_config_validation(tmp_path):
    from abicus.apps.outflows.guess import load_guess_config

    p = tmp_path / "guess.yaml"
    p.write_text("embed_min_score: 0.7\n")
    assert load_guess_config(p).embed_min_score == 0.7
    p.write_text("embed_min_score: 1.5\n")
    with pytest.raises(ValueError):
        load_guess_config(p)
