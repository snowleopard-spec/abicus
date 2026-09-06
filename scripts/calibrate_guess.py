#!/usr/bin/env python3
"""Leave-one-out calibration of the guess engines (V3 M7).

For every distinct description in the live corpus (transactions.db +
transaction_history.xlsx), hide it, guess it from all the others with
BOTH engines, and compare the guessed category to the real one. Sweeping
the threshold gives precision/coverage per candidate value; the chosen
embed_min_score favours precision (spec R9: a wrong guess is worse than
no guess).

Reads the real data; writes nothing. Run from the repo root with the
`.[suggest]` extra installed:

    .venv/bin/python scripts/calibrate_guess.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from abicus.apps.outflows import db, guess_embed  # noqa: E402
from abicus.apps.outflows.categories import load_categories  # noqa: E402
from abicus.apps.outflows.guess import (  # noqa: E402
    GuessConfig, best_guess, build_corpus,
)
from abicus.apps.outflows.router import HISTORY_PATH  # noqa: E402
from abicus.apps.outflows.transaction_history import (  # noqa: E402
    load_history_mapping,
)


def load_real_corpus() -> dict[str, tuple[str, str]]:
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = None
    try:
        history_map, _ = load_history_mapping(
            HISTORY_PATH, valid_categories=valid_cats
        )
    except (FileNotFoundError, ValueError):
        history_map = {}
    return build_corpus(
        db.load_description_categories(),
        list(history_map.items()),
        valid_categories=valid_cats,
    )


def sweep_rapidfuzz(corpus, thresholds):
    """Leave-one-out: guess each display description against the corpus
    minus itself. best_guess normalises the query, and the held-out key is
    removed, so the query can never match itself."""
    results = {t: [0, 0] for t in thresholds}  # t -> [right, offered]
    n = len(corpus)
    for key, (category, display) in corpus.items():
        rest = {k: v for k, v in corpus.items() if k != key}
        g = best_guess(display, rest, GuessConfig(min_score=min(thresholds)))
        for t in thresholds:
            if g is not None and g["score"] >= t:
                results[t][1] += 1
                results[t][0] += g["category"] == category
    return {
        t: (right / offered if offered else 0.0, offered / n)
        for t, (right, offered) in results.items()
    }


def sweep_embed(corpus, thresholds):
    """Leave-one-out on the embedding engine: embed everything once, then
    for each row take the best OTHER row by cosine."""
    keys = sorted(corpus)
    encode = guess_embed.get_encoder()
    emb = encode(keys)
    sims = emb @ emb.T
    np.fill_diagonal(sims, -1.0)  # exclude self
    nn = sims.argmax(axis=1)
    nn_sim = sims[np.arange(len(keys)), nn]

    cats = [corpus[k][0] for k in keys]
    right_mask = np.array([cats[i] == cats[j] for i, j in enumerate(nn)])

    out = {}
    n = len(keys)
    for t in thresholds:
        offered = nn_sim >= t
        n_off = int(offered.sum())
        precision = float(right_mask[offered].mean()) if n_off else 0.0
        out[t] = (precision, n_off / n)
    return out


def show(name, table):
    print(f"\n{name}  (threshold → precision / coverage)")
    for t in sorted(table):
        p, c = table[t]
        print(f"  {t:.2f} → {p * 100:5.1f}% / {c * 100:5.1f}%")


def main():
    corpus = load_real_corpus()
    print(f"corpus: {len(corpus)} distinct descriptions")

    rf = sweep_rapidfuzz(corpus, [0.75, 0.80, 0.85, 0.90, 0.95])
    show("rapidfuzz (free-deletion edit distance)", rf)

    emb = sweep_embed(
        corpus, [0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95, 0.97]
    )
    show("transformer (bge-small cosine)", emb)


if __name__ == "__main__":
    main()
