"""
guess_embed.py
==============

Transformer guess engine for unmapped transactions (V3 Feature B).

Where guess.py matches by *spelling* (free-deletion edit distance), this
engine matches by *meaning*: every known description is embedded with
`BAAI/bge-small-en-v1.5` (sentence-transformers, local, offline), the
query is embedded the same way, and the nearest corpus neighbour by
cosine similarity becomes the guess — its similarity is the confidence
score, thresholded by `embed_min_score` in config/guess.yaml.

Discipline mirrors guess.py: the scoring core is pure and I/O-free;
descriptions are normalised with guess.normalise so both engines see the
same strings; corpus assembly is the caller's job (one corpus, two
engines). Threshold calibration lives in scripts/calibrate_guess.py and
its results are recorded in documentation/V3_SPEC.md §6 (M7).

Heavy-dependency rules (spec R7):
- sentence-transformers is an OPTIONAL dependency (`.[suggest]` extra —
  it drags in torch). `available()` probes for it at call time; without
  it the caller degrades to rapidfuzz-only with an install hint, never
  an error. This module imports only numpy at the top level (already a
  base dependency via pandas).
- The model loads lazily on the first guess request (seconds, once per
  server run).
- Corpus embeddings persist to data/guess_embed_cache.npz keyed by a
  hash of the model name + the sorted corpus descriptions, so the corpus
  is re-embedded only when it changes, not per session.

Tests monkeypatch `get_encoder` to inject a fake encoder — no model, no
network, and cache-hit behaviour is asserted with a counting stub.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

from .guess import GuessConfig, normalise

logger = logging.getLogger("abicus.outflows.guess_embed")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE_PATH = Path(__file__).parent / "data" / "guess_embed_cache.npz"

INSTALL_HINT = (
    "Transformer guesses are off — the optional ML stack is not "
    "installed. Enable with: pip install -e '.[suggest]'"
)

_model = None


def available() -> bool:
    """True when the optional ML stack is importable. Cheap after the
    first call (module import is cached by Python)."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def get_encoder():
    """Lazy singleton encoder: list[str] -> float32 array of L2-normalised
    embeddings. Tests monkeypatch this function to inject a fake."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("loading %s (first guess request this run)", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)

    def encode(texts: list[str]) -> np.ndarray:
        return np.asarray(
            _model.encode(list(texts), normalize_embeddings=True),
            dtype=np.float32,
        )

    return encode


def _corpus_key(descs: list[str]) -> str:
    h = hashlib.sha256(MODEL_NAME.encode("utf-8"))
    for d in descs:
        h.update(b"\x1f" + d.encode("utf-8"))
    return h.hexdigest()


def corpus_embeddings(
    descs: list[str],
    encode,
    cache_path: Path = CACHE_PATH,
) -> np.ndarray:
    """Embeddings for the (already sorted) corpus descriptions, served
    from the .npz cache when the corpus and model are unchanged."""
    key = _corpus_key(descs)
    if cache_path.exists():
        try:
            with np.load(cache_path, allow_pickle=False) as data:
                if str(data["key"]) == key:
                    return data["embeddings"]
        except Exception as e:  # unreadable cache — rebuild it
            logger.warning("guess_embed cache unreadable (%s); rebuilding", e)
    emb = encode(descs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache_path, key=np.array(key), embeddings=emb)
    return emb


# ---- Pure scoring core ----

def nearest(
    query_emb: np.ndarray, corpus_emb: np.ndarray
) -> tuple[int, float]:
    """Index and cosine similarity of the nearest corpus row. Both inputs
    are L2-normalised, so the dot product IS the cosine similarity."""
    sims = corpus_emb @ query_emb
    idx = int(np.argmax(sims))
    return idx, float(sims[idx])


def batch_guess(
    queries: list[str],
    corpus: dict[str, tuple[str, str]],
    cfg: GuessConfig,
    encode=None,
    cache_path: Path = CACHE_PATH,
) -> list[dict | None]:
    """Best embedding guess per raw query description, aligned with the
    input list. None where nothing clears cfg.embed_min_score.

    corpus is guess.build_corpus's shape: {normalised: (category, display)}.
    All distinct queries are embedded in ONE encode call; the corpus comes
    from the cache when unchanged.
    """
    if not queries:
        return []
    keys = sorted(corpus)
    if not keys:
        return [None] * len(queries)

    normed = [normalise(q) for q in queries]
    distinct = sorted({n for n in normed if n})
    if not distinct:
        return [None] * len(queries)

    encode = encode or get_encoder()
    corpus_emb = corpus_embeddings(keys, encode, cache_path)
    query_embs = encode(distinct)

    best: dict[str, dict | None] = {}
    for q, q_emb in zip(distinct, query_embs):
        idx, sim = nearest(q_emb, corpus_emb)
        if sim >= cfg.embed_min_score:
            category, display = corpus[keys[idx]]
            best[q] = {
                "category": category,
                "matched": display,
                "score": round(sim, 3),
            }
        else:
            best[q] = None
    return [best.get(n) for n in normed]
