# Spec — Swapping the guess engine to rapidfuzz

> **Status: implemented 2026-09-01** (commit `de0851a`), ahead of the
> original trigger, at owner request. All §5 done-when criteria met:
> `rapidfuzz==3.14.3` wheel install; contract tests pass unchanged plus a
> 300-pair engine/reference equivalence test; 120 real queries verified
> guess-identical to the pure-Python engine; full pass (30 queries × 596
> corpus) = 19.4 ms, ~63× the pure-Python engine. Prefilter deleted;
> `lcs_len` retained as the documented pure-Python reference. This spec
> stays as the record of the design and the C++-in-Python background (§2).

---

## 1. Why rapidfuzz

The guess feature scores an unmapped description against every known
description with a custom edit distance: **substitutions cost 1, deletions
from the query are free**. Pure Python computes this in ~2.2 s per pass at
today's corpus (0.12 s with the prefilter). rapidfuzz computes the *same
metric* in C++ at roughly 100–1000× the per-pair speed, removing the need
for a prefilter entirely.

rapidfuzz is already a known quantity in the stack — Maillard uses it for
fuzzy CLI name lookups.

## 2. How C++ gets inside a Python project (background)

This section is context, not work. Nothing here is Abicus-specific.

**The mechanism.** CPython can import compiled shared libraries — `.so`
files on macOS/Linux, `.pyd` on Windows — as if they were ordinary modules.
A library written in C++ exposes Python-callable functions through a binding
layer (rapidfuzz uses **CPython's C API** directly; other projects use
pybind11 or Cython, which generate that glue for you). When you write
`from rapidfuzz.distance import Levenshtein`, Python loads a compiled
binary and each call crosses from the interpreter into native code — that
crossing has a fixed overhead (~microseconds), which is why batch APIs that
stay inside C++ for thousands of comparisons (§4) beat per-pair calls in a
Python loop.

**Who compiles it.** Almost never you. Package authors pre-compile for
every common platform and upload the results to PyPI as **binary wheels** —
files tagged by OS, CPU and Python version, e.g.
`rapidfuzz-…-cp313-cp313-macosx_11_0_arm64.whl`. `pip`/`uv` pick the wheel
matching your machine and just unzip it: no compiler involved, install
takes seconds. This is the same reason `pandas` and `cryptography` (both
heavy compiled projects already in the stack) install without a toolchain.

**The fallback path.** If no wheel matches (unusual platform, brand-new
Python version before wheels are rebuilt), pip downloads the source
distribution and compiles it on your machine. That requires a C++ compiler
(`xcode-select --install` on the Mac provides clang) plus rapidfuzz's build
tooling (CMake via scikit-build), and takes minutes instead of seconds. If
an install ever starts printing compiler output, that is what is happening —
it is legitimate, just slow. rapidfuzz additionally ships a pure-Python
fallback implementation, so even a failed compile leaves a working (slow)
library rather than a broken install.

**Practical rule:** pin the version, let wheels do the work, and treat "it
tried to compile" as a signal to check that the Python version is not newer
than the package's wheel coverage.

## 3. The metric mapping (the actual spec)

rapidfuzz's Levenshtein accepts per-operation costs. Our metric is exactly:

```python
from rapidfuzz.distance import Levenshtein

# transforms QUERY into CANDIDATE:
#   weights = (insertion, deletion, substitution)
cost = Levenshtein.distance(query, candidate, weights=(1, 0, 1))
```

- `deletion = 0` — dropping query characters (reference numbers, dates) is
  free, matching `guess.py`'s `len(candidate) − LCS(query, candidate)`.
- Argument order matters: the free deletions apply to the **first** string.
  Passing `(candidate, query)` silently computes a different metric.

The relative score used for thresholding stays in our code and is unchanged:
`1 − cost / len(candidate)`.

## 4. Integration steps

1. **Add the dependency.** `rapidfuzz` (pinned, current release at the
   time) to `requirements.txt`; install and confirm the install was a wheel
   (seconds, no compiler output).
2. **Swap the engine inside `guess.py` only.** The public functions keep
   their signatures; `distance()`'s body becomes the three-line rapidfuzz
   call; the multiset prefilter is deleted. No caller changes.
3. **Batch, don't loop.** Score one query against the whole corpus in a
   single call so the work stays in C++:

   ```python
   from rapidfuzz import process
   from rapidfuzz.distance import Levenshtein

   results = process.extract(
       query, corpus_descriptions,
       scorer=Levenshtein.distance,
       scorer_kwargs={"weights": (1, 0, 1)},
       limit=1,
   )
   ```

   For all unmapped rows at once, `process.cdist(queries, corpus, …,
   workers=-1)` computes the full matrix multithreaded.
4. **Keep the tests as the contract.** `guess.py`'s unit tests assert
   specific distances and best-guess picks against fixtures. They must pass
   **unchanged** after the swap — same metric, different engine. Add one
   equivalence test that runs both implementations over a random sample and
   asserts identical costs, then delete the pure-Python path (or keep it as
   the documented no-dependency fallback; decide then).
5. **Measure.** Re-run the timing check from the design discussion
   (30 queries × full corpus). Expect double-digit milliseconds. Record the
   number in the release notes entry.

## 5. Done when

- `pip show rapidfuzz` reports the pinned version; install was wheel-based.
- The guess endpoint returns identical guesses to the pure-Python engine on
  the equivalence sample.
- Full-pass timing is recorded and at least 10× faster than the pure-Python
  figure at the then-current corpus size.
- The prefilter code is gone (or explicitly retained as fallback), and the
  test suite passes without modification.

## 6. Trade-offs accepted by this swap

| | Pure Python (today) | rapidfuzz (this spec) |
|---|---|---|
| Speed (full pass) | 0.12 s with prefilter | ~tens of ms, no prefilter |
| Dependencies | none | one compiled wheel (~2 MB) |
| Code | LCS DP + prefilter (~40 lines) | 3-line call, batch APIs |
| Risk | prefilter bugs are ours | argument-order/weights mistakes (§3) |
| Explainability | every line readable | metric identical, engine opaque |
