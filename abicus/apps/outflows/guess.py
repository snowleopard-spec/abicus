"""
guess.py
=========

Category guessing for unmapped transactions.

Scores an unmapped description against every known description → category
pair (from transactions.db and transaction_history.xlsx) using a
free-deletion edit distance:

    cost(query → candidate) = len(candidate) − LCS(query, candidate)

i.e. deleting query characters is free (reference numbers, dates, prefixes
cost nothing) and every candidate character that cannot be lined up costs 1.
The relative score is 1 − cost/len(candidate) = LCS/len(candidate).

Free deletions are generous — any short candidate whose characters appear
somewhere in order inside the query scores perfectly — so guessing is
guarded by a minimum candidate length and a score threshold, both
configurable via config/guess.yaml (defaults below; see GuessConfig).

Threshold calibration (2026-08-29, leave-one-out over the 693 distinct DB
descriptions): min_score 0.90 → 85% precision at 67% coverage; 0.85 → 79%
precision at 89% coverage; 0.75–0.80 → ~74–75% precision. Default 0.90,
favouring precision (a wrong guess is worse than no guess). Note the
measurement is pessimistic: descriptions with no true near-neighbour can
only ever produce a "wrong" guess in leave-one-out.

The scoring core is pure and I/O-free (Maillard similarity.py discipline);
corpus assembly takes plain data structures so callers own all I/O.

Engine: rapidfuzz (C++), per RAPIDFUZZ_SPEC.md. The metric is expressed as
a weighted Levenshtein — weights=(insertion, deletion, substitution) =
(1, 0, 1) with the QUERY as the first argument, so deletions from the query
are free — which equals len(candidate) − LCS(query, candidate) exactly.
`lcs_len` is retained as the pure-Python reference implementation; the test
suite asserts engine/reference equivalence over a random sample. The old
character-multiset prefilter is gone — rapidfuzz makes it unnecessary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import process
from rapidfuzz.distance import Levenshtein

_WEIGHTS = (1, 0, 1)  # (insertion, deletion, substitution): query deletions free

CONFIG_PATH = Path(__file__).parent / "config" / "guess.yaml"

DEFAULT_MIN_SCORE = 0.90
DEFAULT_MIN_CANDIDATE_LENGTH = 5


@dataclass(frozen=True)
class GuessConfig:
    min_score: float = DEFAULT_MIN_SCORE
    min_candidate_length: int = DEFAULT_MIN_CANDIDATE_LENGTH


def load_guess_config(path: Path = CONFIG_PATH) -> GuessConfig:
    """Read config/guess.yaml; missing file or missing keys fall back to
    defaults. Malformed values raise ValueError so typos surface loudly."""
    if not path.exists():
        return GuessConfig()
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping of options.")

    cfg = GuessConfig(
        min_score=float(data.get("min_score", DEFAULT_MIN_SCORE)),
        min_candidate_length=int(
            data.get("min_candidate_length", DEFAULT_MIN_CANDIDATE_LENGTH)
        ),
    )
    if not (0.0 < cfg.min_score <= 1.0):
        raise ValueError(f"{path.name}: min_score must be in (0, 1].")
    if cfg.min_candidate_length < 1:
        raise ValueError(f"{path.name}: min_candidate_length must be >= 1.")
    return cfg


# ---- Pure scoring core ----

_NORMALISE_RE = re.compile(r"[0-9]+")
_WS_RE = re.compile(r"\s+")


def normalise(description: str) -> str:
    """Lowercase, drop digits (reference numbers differ per transaction on
    both sides of a comparison), collapse whitespace."""
    s = _NORMALISE_RE.sub("", str(description).lower())
    return _WS_RE.sub(" ", s).strip()


def lcs_len(a: str, b: str) -> int:
    """Longest-common-subsequence length, O(len(a)·len(b)) DP.

    Pure-Python REFERENCE implementation only — the engine below runs on
    rapidfuzz. Kept so the test suite can assert engine equivalence."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, bj in enumerate(b, start=1):
            cur[j] = prev[j - 1] + 1 if ch == bj else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def distance(query: str, candidate: str) -> int:
    """Free-deletion edit distance: substitutions/insertions cost 1,
    deletions from the query are free. Equals len(candidate) − LCS.

    Argument order matters: free deletions apply to the FIRST string."""
    return Levenshtein.distance(query, candidate, weights=_WEIGHTS)


def score(query: str, candidate: str) -> float:
    """Relative score in [0, 1]: fraction of the candidate's characters
    that line up with the query. 1.0 = candidate is a subsequence of query."""
    if not candidate:
        return 0.0
    n = len(candidate)
    return (n - distance(query, candidate)) / n


def best_guess(
    query: str,
    corpus: dict[str, tuple[str, str]],
    cfg: GuessConfig = GuessConfig(),
) -> dict | None:
    """Return the best-scoring corpus entry for a raw description, or None
    if nothing clears the configured threshold.

    Args:
        query: raw transaction description (normalised internally).
        corpus: {normalised_description: (category, display_description)}.
        cfg: thresholds.

    Returns {"category", "matched", "score"} or None. Deterministic
    tie-break: higher score, then longer candidate, then alphabetical.
    """
    q = normalise(query)
    if not q:
        return None

    cands = [c for c in corpus if len(c) >= cfg.min_candidate_length]
    if not cands:
        return None
    # One batch call so all pairwise scoring stays inside C++; the relative
    # score depends on each candidate's length, so thresholding and ranking
    # happen here on the returned costs.
    results = process.extract(
        q, cands,
        scorer=Levenshtein.distance,
        scorer_kwargs={"weights": _WEIGHTS},
        limit=None,
    )

    best: tuple[float, int, str] | None = None  # (score, len, cand) for ranking
    best_entry: dict | None = None
    for cand, cost, _idx in results:
        n = len(cand)
        s = (n - cost) / n  # == LCS/len(candidate)
        if s < cfg.min_score:
            continue
        if best is None or (s, n) > best[:2] or ((s, n) == best[:2] and cand < best[2]):
            best = (s, n, cand)
            category, display = corpus[cand]
            best_entry = {"category": category, "matched": display, "score": round(s, 3)}
    return best_entry


# ---- Corpus assembly (pure: caller supplies the rows) ----

def build_corpus(
    db_pairs: list[tuple[str, str]],
    history_pairs: list[tuple[str, str]],
    valid_categories: set[str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Merge (description, category) pairs from the database and the
    transaction-history file into {normalised: (category, display)}.

    History is applied last so the hand-curated layer wins on conflict.
    Pairs whose category is not in valid_categories (when given) are
    dropped — a guess must be acceptable to the accept endpoint.
    """
    corpus: dict[str, tuple[str, str]] = {}
    for desc, category in list(db_pairs) + list(history_pairs):
        category = str(category).strip()
        if not category or category == "Uncategorised":
            continue
        if valid_categories is not None and category not in valid_categories:
            continue
        display = str(desc).strip()
        key = normalise(display)
        if key:
            corpus[key] = (category, display)
    return corpus
