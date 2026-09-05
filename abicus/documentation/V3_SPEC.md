# Spec — Abicus V3: DB commit history + transformer guess engine

> **Status: not started** · Drafted 2026-09-05 · Target version **3.0.0**
> (current: 2.1.2). This is a build contract for a fresh Claude Code
> session, in the house style: resolved decisions up front, then numbered
> verify-before-continue milestones, each sized to one ~15-minute session
> and ending with the app usable. Do not start a milestone before the
> previous one's "Done when" line is verifiably true.

---

## 1. Context & motivation

Two additions, both to **outflows** only.

**Feature A — DB commit history.** `transactions.db` is the rolling source
of truth for categorised spending, and it is fragile in one specific way:
bad data committed *cleanly*. A misparsed statement upserted over good rows
silently overwrites their categories (`upsert`'s ON CONFLICT path keeps no
old values), and `clear()` has no undo at all. The row-level undo in the DB
Edit tab covers single deletes only — batch-level mistakes are currently
unrecoverable. Fix: after every write, dump the table as deterministic text
and commit it into a **nested, local-only git repo** under `data/history/`.
Every write becomes a labelled commit; `git log` is the audit trail,
`git diff` shows exactly which rows an import changed, and any prior state
can be restored — from a CLI script or, first-class, from a **History
panel in the DB Edit tab** (commit list + rollback button in the GUI).
Git here is not a metaphor — it is actual git, used as
what it fundamentally is: a local version-history database. No daemon runs;
each checkpoint is a millisecond subprocess that exits.

**Feature B — transformer guess engine, behind a toggle.** The rapidfuzz
guesser (`guess.py`, per `RAPIDFUZZ_SPEC.md`) matches by *spelling*: a new
description guesses right only if a near-identical string exists in the
corpus. An embedding engine matches by *meaning* — "GRAB 7-ELEVEN" can
land near "CIRCLE K CONVENIENCE" with zero character overlap. Rather than
replace one engine with the other, V3 runs them side by side behind a
three-state toggle (rapidfuzz / transformer / both), so their real-world
precision can be compared live on every review session. This revives the
simplification plan's lapsed D3–D5 design, which its own removal note says
would still be the right shape.

## 2. Resolved decisions — do not re-litigate

- **R1 — History covers outflows only.** `claims/data/mediclaim.db` is out
  of scope for V3, but the checkpoint helper takes the DB path and history
  directory as parameters so extending it later is a two-line change.
- **R2 — The history repo has NO remote, ever.** It is financial data. It
  lives and dies inside `abicus/apps/outflows/data/history/` on the Mac.
  The main repo already gitignores `abicus/apps/*/data/`, and git commands
  resolve to the nearest `.git` upward, so the nested repo is invisible to
  and independent of the Abicus repo. Nothing in the code may add a remote,
  push, or fetch.
- **R3 — Checkpoint AFTER each write.** The history reads as a log of
  operations; each commit's diff matches its label; the pre-operation
  state is simply the previous commit.
- **R4 — Dumps are deterministic text.** Rows ordered by `tx_hash`, stable
  column order, one row per line — so identical DB states produce
  byte-identical dumps and `git diff` is row-per-line readable.
- **R5 — History is stdlib + git only.** No new Python dependencies for
  Feature A. If `git` is unavailable or a checkpoint fails, **warn loudly
  and continue** — a broken history layer must never block or corrupt the
  write it was recording.
- **R6 — Embedding model: `BAAI/bge-small-en-v1.5`** via
  sentence-transformers (~130 MB) — the Pantheon embedding family, sized
  down, exactly as the old D3 resolved. Local, offline, deterministic; no
  description ever leaves the Mac.
- **R7 — The transformer engine is an optional dependency.**
  sentence-transformers drags in torch (~2 GB); Abicus stays
  dependency-light. `[project.optional-dependencies] suggest` in
  `pyproject.toml` (the Pantheon lean-base/heavy-extra pattern). Without
  it, outflows degrades to rapidfuzz-only with a visible
  "install with `pip install -e '.[suggest]'`" hint — never an error.
- **R8 — Suggestions are suggestion-only.** Both engines surface
  click-to-accept pills with the matched description and a confidence
  figure. Nothing is ever auto-applied. Categorisation stays deterministic
  and auditable (old D5, unchanged).
- **R9 — Precision over coverage.** The transformer threshold is
  calibrated leave-one-out on the real corpus, mirroring the rapidfuzz
  calibration (min-score 0.90 → 85% precision at 67% coverage over 693
  descriptions). A wrong guess is worse than no guess.

## 3. Non-goals

- No shared database across sub-apps (standing Abicus rule).
- No remote for the history repo (R2). No cloud, no push, no backup service.
- No auto-apply of guesses (R8).
- assets, claims and mortgage are untouched. `mediclaim.db` gets no history
  layer in V3 (R1).
- No fine-tuning required for "done" — Milestone 10 is stretch only. (The
  DB Edit History panel is NOT stretch — GUI rollback is a required V3
  deliverable, M4.)
- No re-engineering of the rapidfuzz engine; it is the incumbent and the
  baseline.

## 4. Feature A design — DB commit history

**Write surface (verified):** every mutation of `transactions.db` flows
through exactly five functions in `abicus/apps/outflows/db.py` —
`upsert`, `clear`, `update_category`, `delete_row`, `restore_row`. There
is no other write path. Each already computes the counts its commit label
needs (`upsert` returns inserted/updated/total; `clear` returns deleted;
the row-level three identify their `tx_hash`).

**New module `abicus/apps/outflows/db_history.py`:**

- `checkpoint(label: str)` — dump the transactions table ordered by
  `tx_hash` to `data/history/transactions.sql` (deterministic INSERT
  statements, R4), then `git -C <history_dir> add … && git commit -m
  <label>` via `subprocess`. First call initialises: `mkdir`, `git init`,
  identity config local to the repo (`user.name "abicus"`), an initial
  commit. A no-op write (dump unchanged) commits nothing.
- Failure handling per R5: any `FileNotFoundError` (no git) or non-zero
  subprocess exit logs a loud warning with the reason; the caller's write
  has already succeeded and stands.
- `log()` / `show(ref)` helpers reading `git log --format=…` — needed by
  the restore script now and the stretch History panel later.
- Parameterised on `(db_path, history_dir)` with outflows defaults (R1).

**Hook points:** one `checkpoint(...)` call at the end of each of the five
mutating functions, labels like `upsert: +12 inserted, 3 updated (total
215)`, `clear: 215 deleted`, `update_category <hash8>: → Groceries`,
`delete_row <hash8>`, `restore_row <hash8>`.

**Restore path:** `scripts/outflows_history.py` (repo `scripts/` folder) —
`list` prints the commit log (short sha, date, label); `diff <ref>` shows
what a commit changed; `restore <ref>` rebuilds `transactions.db` from that
commit's dump into a fresh file and swaps it in — **after first
checkpointing the current state** with label `pre-restore snapshot`, so a
restore is itself always reversible. The restored state then commits as
`restore → <sha8>`, so history stays linear (never `git reset`; a rollback
is a new commit, and rolling back a rollback is just another restore). The
list/diff/restore operations live in `db_history.py` so the CLI and the
GUI panel below are thin wrappers over one implementation.

**History panel (DB Edit tab) — required, not stretch:** a History section
on the DB Edit page listing the commit log newest-first (short sha, date,
label, and a per-commit change summary — rows added/changed/removed,
countable directly from the row-per-line diff). Each commit gets **View
changes** (diff summary) and **Roll back** actions; Roll back shows an
explicit confirm dialog stating the target commit's label and date, then
calls a new `POST /history/restore` route running the exact M3 restore
(pre-restore snapshot first), and the page reloads showing the restored
rows plus the new `restore → <sha8>` commit at the top of the log. Served
the vanilla-HTML/JS way like the rest of the tab; no new frontend
dependencies.

## 5. Feature B design — transformer guess engine

**New module `abicus/apps/outflows/guess_embed.py`**, mirroring
`guess.py`'s discipline: a pure, I/O-free scoring core; callers own I/O.

- Corpus: the same description→category pairs `router.py`'s `api_guess`
  already assembles via `build_corpus(db.load_description_categories(),
  history_pairs)` — one corpus, two engines.
- Engine: embed all corpus descriptions (normalised with `guess.normalise`
  so both engines see the same strings) with bge-small, L2-normalised;
  embed the query; cosine nearest neighbour; cosine similarity is the
  confidence score; threshold from `config/guess.yaml` (new key
  `embed_min_score`, same loud-validation style as `load_guess_config`).
- **Embedding cache:** corpus embeddings persist to
  `data/guess_embed_cache.npz` keyed by a hash of the sorted corpus
  descriptions + model name, so the corpus is re-embedded only when it
  changes, not per session. The model itself loads lazily on first guess
  request (seconds, once per server run).
- **Availability probe:** `try: import sentence_transformers` at call
  time; on ImportError the API reports the engine unavailable with the
  R7 hint and the UI greys the toggle position out.

**API & UI:** `api_guess` (`router.py`, `POST /guess/{session_id}`) gains
an `engine` parameter (`rapidfuzz` | `transformer` | `both`, default
`rapidfuzz`). Response per row carries per-engine
`{category, matched, score}` blocks. The review page gets a three-state
toggle; in `both` mode each unmapped row shows two pills side by side
(engine-tagged, each with its confidence), either one click-to-accept —
same accept flow as today (R8).

## 6. Milestones

Verify each "Done when" before continuing. One milestone per session.

- **M1 — History core.** Build `db_history.py` (checkpoint, init-on-first-
  use, deterministic dump, loud-warn degradation, log/show helpers) with
  unit tests against `tmp_path` DBs — including the git-missing path
  (patched PATH) and the identical-state no-op. **Done when:** tests pass;
  two checkpoints of the same state produce one commit.
- **M2 — Hook the writes.** Call `checkpoint` from the five mutating
  functions with count-bearing labels. Extend `tests/test_outflows_routes.py`
  so the route-level fixtures assert a commit lands per write. **Done
  when:** a manual session (upload → commit → edit a category → delete a
  row) leaves a `git log` in `data/history/` reading as that operation
  sequence, and the full test suite is green.
- **M3 — Restore path.** Build the list / diff / restore operations in
  `db_history.py` plus the `scripts/outflows_history.py` CLI wrapper
  (restore = pre-restore snapshot, rebuild, swap, `restore → <sha8>`
  commit). **Done when:** on a copy of the real DB: `clear()`, then
  `restore` to the prior commit, round-trips the DB byte-identically
  (row-count + content check), and both the pre-restore snapshot and the
  restore commit exist in the log.
- **M4 — History panel in the DB Edit tab.** Commit list (sha, date,
  label, change summary), View-changes, and Roll back with confirm dialog,
  backed by `POST /history/restore` over the M3 operations. **Done when:**
  in a manual session, a bad edit is rolled back entirely from the GUI —
  the rows visibly revert, the log shows the `restore → <sha8>` commit —
  and route tests cover restore (including restoring a restore).
- **M5 — Optional-dependency profile.** Add
  `[project.optional-dependencies] suggest = ["sentence-transformers", "numpy"]`
  (pinned), the availability probe, and the degradation hint end-to-end
  (API + UI). **Done when:** without the extra installed, outflows behaves
  exactly as v2.1.2 plus a visible hint; with it, the probe reports
  available.
- **M6 — Embedding engine.** Build `guess_embed.py` (pure core, cosine NN,
  `.npz` cache keyed by corpus hash, lazy model load) with unit tests on a
  tiny fixture corpus (cache-hit behaviour included). **Done when:** tests
  pass and a second call with an unchanged corpus does zero embedding work
  (assert via a counting stub).
- **M7 — Calibration.** Leave-one-out over the real corpus (the rapidfuzz
  calibration's method) to choose `embed_min_score`, precision favoured
  (R9). Record precision/coverage at the chosen threshold — and the
  rapidfuzz numbers on the same day's corpus — in this file and the
  release notes. **Done when:** the numbers are written here and the
  threshold is in `guess.yaml`'s documented defaults.
  *Calibration results (fill at M7): embed_min_score = __ → __% precision
  at __% coverage, corpus n = __; rapidfuzz same-corpus: __% / __%.*
- **M8 — Toggle UI.** `engine` parameter on `api_guess`; three-state
  toggle on the review page; `both` mode renders side-by-side engine-
  tagged pills, either click-to-accept. **Done when:** all three states
  work in a manual session against real data; `both` visibly shows the
  engines agreeing and disagreeing; suite green.
- **M9 — Release.** Version bump to 3.0.0, release-notes entry
  (Feature A + B, calibration numbers, M3 restore drill note), this spec's
  status line flipped to implemented. **Done when:** notes and tag match
  the shipped state.
- **M10 — STRETCH (optional, may be deferred indefinitely without failing
  V3).** Fine-tune `bert-base-uncased` with a classification head
  (`BertForSequenceClassification`, categories as labels) over the corpus
  — the canonical BERT fine-tune, and the PyTorch training warm-up for
  Kiln; minutes on the Mac (MPS/CPU) at this data size. Compare
  leave-one-out against both shipped engines. **Done when (if
  attempted):** the comparison table is recorded here.

## 7. Acceptance checklist (V3 done)

- [ ] Every outflows write produces a labelled commit in
      `data/history/`; a no-op write produces none.
- [ ] The history repo has no remote (`git -C … remote -v` prints
      nothing) and the Abicus repo's `git status` is untouched by it.
- [ ] With git absent, writes still succeed and a loud warning is logged.
- [ ] `outflows_history.py restore` round-trips a cleared DB, and takes a
      pre-restore snapshot first; every restore lands as a
      `restore → <sha8>` commit.
- [ ] The DB Edit tab's History panel lists commits with change summaries
      and rolls back entirely from the GUI (confirm dialog → rows revert →
      restore commit tops the log).
- [ ] Without the `suggest` extra: v2.1.2 behaviour + install hint, no
      errors. With it: transformer guesses flow.
- [ ] Calibration numbers for both engines recorded in §6 and the release
      notes; `embed_min_score` favours precision.
- [ ] Three-state toggle works; `both` shows side-by-side pills; no path
      auto-applies a guess.
- [ ] Full pytest suite green; version 3.0.0; release notes written.
