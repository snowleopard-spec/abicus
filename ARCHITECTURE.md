# Abicus — Architecture & Invariants

> **Purpose of this document.** The map a maintainer (human or LLM
> session) reads before touching code. It records how the system fits
> together and — most importantly — the **invariants**: business rules
> that live inside the implementation and must not be "cleaned up".
> When behaviour looks strange, check here before fixing it.
> Companion documents: `README.md` (install/run), per-feature specs and
> release notes in `abicus/documentation/`.

---

## 1. What Abicus is

A **local-only, single-user, no-auth** personal-finance dashboard:
four self-contained sub-apps (Outflows, Assets, Claims, Mortgage)
mounted under one FastAPI server on `127.0.0.1:8765`. Each sub-app was
once a standalone legacy tool; the 2025 consolidation deliberately kept
their persistence separate.

**Security/privacy model:** the trust boundary is the machine. The
server binds to localhost; there are no accounts, no tokens, no public
surface. Financial data lives only in per-app gitignored `config/` and
`data/` folders — the repo never carries real data. The one ML model
(bge-small, Outflows guessing) runs locally; no description, amount, or
category ever leaves the Mac. Two deliberate, narrow network egress
points exist, both **off by default** and env-gated: live FX rates
(`ABICUS_LIVE_FX`) and live stock prices (`ABICUS_LIVE_PRICES`, one
batched request so holdings aren't enumerable in logs). Known
inconsistency: Assets and Mortgage pages still load Plotly/Tabulator
and Google Fonts from CDNs, while Outflows vendors the same libraries
locally — those two pages are the only part of the app broken offline.

## 2. Runtime architecture

```
Browser (vanilla HTML/CSS/JS, no bundler)
   │  fetch JSON
   ▼
FastAPI (abicus/server.py)
   ├── /<app>          → apps/<app>/router.py  views_router (pages)
   ├── /api/<app>      → apps/<app>/router.py  api_router   (JSON)
   ├── /<app>/static   → apps/<app>/static/
   └── /shell/static   → shell/static/  (api.js, toasts, shared CSS)
   ▼
Per-app modules (parsing, categorisation, compilation, simulation)
   ▼
Per-app persistence (SQLite / parquet / xlsx / json — never shared)
```

- Launched with `python -m abicus` (`__main__.py`: binds
  `127.0.0.1:8765`, auto-picks a free port upward if busy, opens the
  browser). `/` redirects to `/outflows`.
- Templates resolve through a `ChoiceLoader[shell,
  PrefixLoader{outflows,assets,claims,mortgage}]` (`templating.py`);
  every page `{% extends "base.html" %}` from the shell.
- The shell provides the tab bar, toast system, and `api.js` — a fetch
  wrapper that **automatically toasts every API failure**; app code
  that catches an api.js error must not toast again.

### Shell invariants

- **Adding a sub-app touches four places, no registry:** the name
  tuple in `server.py` (static mounts — `StaticFiles` raises at import
  if the folder is missing), both `include_router` blocks, the
  `PrefixLoader` map in `templating.py`, and the hardcoded nav in
  `base.html`. This is deliberate explicitness, not an oversight.
- **Template resolution is shell-first, then prefixed.** `"base.html"`
  comes from the shell; app templates must be addressed as
  `"<app>/page.html"`. In `templating.py` the `Jinja2Templates(directory=…)`
  ctor argument is dead (the loader is replaced on the next line) but
  required — don't "clean up" either line.
- **Every views router declares both `""` and `"/"`** so `/assets` and
  `/assets/` both work. Dropping either breaks bookmarks.
- **The static cache-buster (`?v={{ asset_v }}`) is per-process** —
  `int(time.time())` at import. Browsers cache while the server runs;
  a code change without a restart will NOT invalidate. This is why
  "restart + hard refresh" is the standing advice after JS/CSS edits.
- `version.py::get_version()` (`v<version> · <git sha>`, best-effort)
  is computed and injected as a Jinja global but currently rendered
  nowhere — the `.version-chip` CSS exists unplumbed. Known loose end.

## 3. Repository map

```
abicus/                     repo root
├── ARCHITECTURE.md         this file
├── README.md               install / run / data layout
├── pyproject.toml          package metadata; [suggest] optional extra
├── scripts/
│   ├── outflows_history.py   CLI over the DB commit history (list/diff/restore)
│   ├── calibrate_guess.py    leave-one-out calibration of both guess engines
│   └── migrate_from_legacy.sh  one-time data backfill from the legacy repos
├── abicus/
│   ├── server.py           mounts everything (see §2)
│   ├── shell/              shared chrome: base template, api.js, toasts, CSS
│   ├── documentation/      specs (V3_SPEC.md, RAPIDFUZZ_SPEC.md), RELEASE_NOTES.md
│   └── apps/{outflows,assets,claims,mortgage}/
│       ├── router.py       HTTP layer (views + api routers)
│       ├── templates/ static/ config/ data/   (config+data gitignored)
│       └── <feature modules — see per-app sections>
└── tests/                  pytest; route-level per app + unit suites
```

**House pattern (the template for new work):** a feature is a module
with a **pure, I/O-free core**; callers (router, CLI script, tests) own
all I/O. Where a feature has two consumers, both wrap one
implementation — `db_history.py` (HTTP route + CLI script) is the
canonical example. Config precedence: explicit arg > config file >
hardcoded default; config loaders validate loudly on malformed values.

## 4. Outflows — statement parsing, categorisation, spending DB

The most actively developed sub-app: bank/card statements in,
categorised spending out, with a rolling SQLite store behind a
git-backed history.

| Module | Role |
|---|---|
| `router.py` | all HTTP endpoints (largest file; review/mapping/dbedit/breakdown) |
| `parsers/format_a..f.py` | one parser per statement format; the parsers ARE the format fingerprints |
| `accounts.py` | `accounts.yaml` loader (account → format/labels), validated loudly |
| `categorise.py` | mapping-rule engine (longest-substring match) |
| `build_mapping.py` | mapping.xlsx → mapping.json compiler |
| `transaction_history.py` | hand-curated exact-match description→category layer (xlsx) |
| `guess.py` | rapidfuzz spelling-match guesser: pure scoring core + corpus assembly |
| `guess_embed.py` | bge-small meaning-match guesser: cosine NN + on-disk embedding cache |
| `db.py` | SQLite persistence for committed transactions (`data/transactions.db`) |
| `db_history.py` | git-backed commit history of every DB write (`data/history/`) |
| `html_export.py`, `pdf_export.py`, `breakdown_html_export.py` | exporters |

**Data flow (a review session):** upload → `/detect` try-parses against
every parser → `/compile` parses chosen formats into a session
DataFrame → `categorise_dataframe` applies mapping rules + transaction
history → unmapped rows get guess pills (both engines, `/guess`) →
user accepts/edits → `/db/commit` upserts the visible rows into
`transactions.db` → every write checkpoints into `data/history/`.
The Breakdown and DB Edit tabs read the DB directly.

### Outflows invariants

**Identity & the DB**
- `tx_hash` is a **content hash** of `(date, amount, description,
  account, source_file, occurrence)`. The `occurrence` counter makes an
  un-suppressed duplicate a distinct row instead of overwriting its
  twin (`db.py::_row_hash`). Do not change the key composition — it is
  what makes re-commits idempotent.
- `upsert` ON CONFLICT **keeps the row's identity but replaces its
  category** (`category`, `matched_pattern`, `committed_at`). This is
  deliberate: re-committing a period re-applies that session's
  categories, which can overwrite a hand-edit made in DB Edit. The
  history layer exists precisely because of this.
- All writes to `transactions.db` flow through exactly five functions
  in `db.py`: `upsert`, `clear`, `update_category`, `delete_row`,
  `restore_row`. **Any new write path must checkpoint the same way.**

**DB commit history (`data/history/`)**
- It is a real nested git repo, **local-only, no remote, ever** — it
  holds financial data. Nothing in code may add a remote, push, or
  fetch (V3 spec R2).
- Checkpoints run **after** each write; a pre-existing DB gets a
  `baseline:` commit **before** its first hooked write; an identical
  state commits nothing.
- History is **linear and append-only**: a rollback is a new
  `restore → <sha>` commit, never `git reset`. Restore snapshots the
  live state first only when it isn't already committed.
- The history layer **fails open**: if git is missing or a checkpoint
  errors, the DB write stands and a loud warning is logged. A broken
  history layer must never block or corrupt the write it records.
- Dumps are deterministic (rows ordered by `tx_hash`, one INSERT per
  line) so identical states are byte-identical and diffs read
  row-per-line. Restore rebuilds from the dump and swaps atomically.

**Categorisation & guessing**
- Precedence: **mapping rules run first; guessing only sees rows the
  rules could not categorise.** Transaction history (the hand-curated
  layer) wins over DB pairs when building the guess corpus.
- The guess corpus is **distinct normalised descriptions**, not
  transactions: lowercased, digits stripped (reference numbers differ
  per transaction), whitespace collapsed. Both engines see the same
  corpus and the same normalisation (`guess.normalise`).
- `Uncategorised` rows never enter the corpus; a guess must name a
  category that the accept endpoint would take.
- **Suggestions are suggestion-only.** Both engines render
  click-to-accept pills; no code path may auto-apply a guess.
- **Precision over coverage** — a wrong guess is worse than no guess.
  Thresholds are calibrated leave-one-out on the real corpus
  (`scripts/calibrate_guess.py`; numbers in V3_SPEC §6 M7:
  rapidfuzz `min_score`, transformer `embed_min_score` 0.90 → 97.7%
  precision / 78.9% coverage at n=983). Re-run the script before
  changing a threshold, and record the numbers.
- The transformer stack is an **optional extra** (`pip install -e
  '.[suggest]'`, pinned in `pyproject.toml`). Without it — or if the
  model fails at runtime — guessing degrades to rapidfuzz-only with a
  visible hint, never an error. The embedding cache
  (`data/guess_embed_cache.npz`) is keyed on corpus content + model
  name; deleting it is always safe (one ~20s re-embed).

**Format detection**
- `/detect` try-parses the upload against every registered parser; a
  bare `except Exception: continue` is correct there (any failure just
  means "not this format").
- Detection commits to an answer only for a **single** candidate — with
  one deliberate exception: Format A's 30-row header scan is a strict
  superset of Format F's row-0 manual-template header, so the pair
  {A, F} resolves to F via `DETECT_PRECEDENCE`. Any other collision
  stays ambiguous on purpose. Real Format A files carry preamble rows;
  that asymmetry is why only this pair ties.
- Compile never trusts detection: the parser is looked up from the
  account the user chose.

**Review semantics**
- Refunds (negative amounts) are hidden from the commit view by
  default and must be explicitly re-included per row.
- Client-side overrides (un-suppressed duplicates, excluded rows,
  re-included refunds) are applied at commit time so **what the user
  sees is what gets committed**.

## 5. Assets — portfolio compiler

Multi-broker holdings exports in, one USD-normalised portfolio master
out, with allocation charts, PDF and Excel exports.

| Module | Role |
|---|---|
| `router.py` | HTTP surface + the in-memory `SESSIONS` store |
| `pipeline.py` | config loading, parser dispatch, price resolution, allocations, PDF/Excel, parquet save/load (the known grab-bag — split when next touched) |
| `fx_rates.py` | cache-first FX loader + `convert_to_usd` |
| `parsers/broker_a.py`, `broker_c.py`, `manual.py` | one parser per source; manual supports Auto-Calc ticker pricing |

**Data flow:** `/compile` (files + source assignments) → `load_config`
→ FX rates → per-file parse via `PARSERS[source]` → `pd.concat` →
`convert_to_usd` → broad-asset-class map → session → allocation charts.
`/save` persists ONE compilation (`data/last_compiled.parquet` + meta
JSON with fx_rates and stock_prices), overwritten in place — no
history. `/load` restores it into a fresh session.

### Assets invariants

**Classification & mapping**
- `"UNMAPPED"` is a **sentinel, not an error** — mapping lookups fall
  through to it, and a present-but-blank mapping value counts as
  unmapped. `append_unmapped_to_mappings` deliberately writes
  blank-valued CSV rows for the user to fill in; never coerce blank →
  NaN or that round-trip breaks (`parsers/broker_a.py`, `pipeline.py`).
  Since V3.1, `load_config` reads the two mapping CSVs with
  `na_filter=False` precisely to keep blanks as `""` — a default read
  turned them into NaN, whose `str()` is the truthy `"nan"`, producing
  the literal asset class "nan" instead of UNMAPPED (regression-tested
  in `test_assets_parsers.py`).
- **Hard-coded classification beats the CSV mapping**: cash/forex →
  `"Cash"`, stock rows → `"Single Stock"`, only then the CSV, then
  `UNMAPPED`. A CSV row cannot override cash or single-stock. Cash is
  unconditionally non-US-situs.
- The literal string `"Cash"` is the join key between that rule and
  the "Cash by institution" chart. Unknown broad asset class collapses
  to sentinel `"Other"`.
- Broker A keeps only the **most recent date** in the file and only
  `Cash`/`Position Values` rows. Broker C's column *indices* (3,4,5,6,
  8,12) are positional and load-bearing; CSVs are read with
  `names=range(30), on_bad_lines="skip"` because header rows are
  narrower than data rows.
- **Broker C forex rows carry a pre-computed `Balance (USD)` that must
  never be re-converted** — `convert_to_usd` skips rows where it is
  already present. For non-forex rows the "Market Value" column holds
  the *local* balance (documented inversion in `broker_c.py`).

**FX & prices**
- FX rates are **USD-based; conversion divides** (`local / rate`);
  display inverts per-currency for a fixed list.
- FX precedence: live (only when explicitly enabled via flag or
  `ABICUS_LIVE_FX`) → cache file → bundled snapshot → `{USD: 1.0}` +
  `fx_error`. A fetched payload must contain the full expected currency
  set or the cache is NOT written (anti-poisoning). Only a fresh live
  fetch counts as non-stale. FX failures are swallowed at three
  deliberate layers — FX must never fail a compile.
- When rates are unusable the conversion step is skipped entirely and
  `Balance (USD)` stays None (total renders 0) — degraded, not wrong.
- Live stock prices are fetched in **exactly one batched
  `yf.download` call** so holdings aren't individually enumerable in
  request logs — a privacy invariant, enforced by
  `test_pipeline_privacy.py`. Never refactor to a per-ticker loop.
  Offline is the default (`ABICUS_LIVE_PRICES` gates live); missing
  tickers surface as `price_errors`, never a raise.
- `.L` (London) tickers are quoted in pence: the manual parser divides
  by 100. ⚠ **Known hazard:** the converted (pounds) value is written
  back into `fetched_prices`, which `/save` persists and the next
  compile treats as pence again — a save/reload can double-divide.
  Documented here deliberately; fix it as its own change with a test,
  don't patch it in passing.

**Compilation & output**
- **Per-file failures are captured, not raised** — a partial master
  with `compile_errors` is a valid result. Unknown source and
  unimplemented parser degrade the same way.
- Currency lookthrough explodes rows and re-weights both balances;
  weights are warned about outside [0.999, 1.001] but never enforced;
  lookthrough affects **only** the currency chart.
- Chart rows sort by value descending and colours are assigned by
  **rank, not category** (frontend palette mirrors the PDF's) — a
  category can change colour between compiles; deliberate.
- `DISPLAY_COLS` is the response contract: the session response
  `reindex`es (missing columns become NaN) while the Excel export
  intersects (missing columns dropped) — two policies on purpose. The
  Excel download currently ignores its `hide_balances`/`lookthrough`
  options and always exports the full master.
- `/load` prefers the **saved** FX rates over fresh ones so a reloaded
  compile reproduces its original valuation.

## 6. Claims — medical-claims tracker

Family medical invoices from *incurred* → *claimed* → *rebated*, with
attached files. The thin-router ideal: `router.py` delegates nearly
everything to `db.py` (SQLite, schema-in-module), `files.py`
(sanitised on-disk invoice storage) and `status.py` (one pure
derived-status function).

**Persistence:** `data/mediclaim.db` (tables `claims`, `claim_files`),
`data/invoices/` for uploads, two JSON config arrays (claimants,
institutions) that self-seed and never raise.

### Claims invariants

- **`compute_status` is a strict cascade — the order of the `if`s IS
  the business rule** (`status.py`): Excluded ▸ "Check: rebated but
  not claimed" (a data-integrity warning, not an error) ▸ Complete ▸
  Claim submitted ▸ Ready to claim ▸ Awaiting invoice. The frontend
  pattern-matches these **exact strings** (and the status filter
  hardcodes them in `page.html`); renaming one silently breaks
  filtering and row styling.
- `outstanding`: excluded → 0; rebated → `max(amount − rebated, 0)`
  (an over-rebate never goes negative); otherwise the **full amount**
  — a submitted-but-unrebated claim is still fully outstanding.
- `GET /claims/archived` is declared **before** the `/{claim_id}`
  routes — FastAPI matches in registration order; moving it breaks it.
- The `excluded` column arrives via a guarded `ALTER TABLE` migration;
  the `CREATE TABLE` deliberately omits it so old and fresh DBs keep
  identical column order. Don't "tidy" it into the CREATE.
- `PRAGMA foreign_keys = ON` per connection is what makes
  `ON DELETE CASCADE` work — SQLite defaults it off. The connection
  context manager commits only on the happy path; no function calls
  `commit()` itself. Schema init runs once per process (`_init_done`).
- `toggle_flag`'s field whitelist is a **SQL-injection guard** — the
  field name is f-string-interpolated; the whitelist is the only thing
  making that safe.
- `DELETE /claims/{id}` **archives**; only `/permanent` deletes — and
  then DB row first, file unlinks after, best-effort (an orphan file
  beats a 500 with the row already gone).
- `update_claim` deliberately does NOT touch `invoice_file` or
  `archived` — invoice replacement and archiving have their own paths;
  adding those columns to the UPDATE would let a stale form wipe an
  uploaded invoice.
- Invoice filenames encode identity (`YYYYMMDD_Claimant_Institution.ext`,
  sanitised, `_2/_3…` collision suffixes, `00000000` = missing date);
  other-docs use a different scheme and keep the original name in the
  DB for downloads. Path safety relies on sanitisation at **write**
  time; `resolve()` is the only path-construction point.
- Currency is stored (default `"SGD"` in four places) but the frontend
  hard-prefixes "SGD" and sums across all rows regardless — a non-SGD
  claim yields a silently wrong headline total. Known limitation.
- Summary tiles are scoped to the **date window only** (table filters
  don't change them), and the client-side shortfall (incurred −
  rebate) is a different figure from the server's `outstanding` — two
  "amount owed" definitions coexist on purpose.

## 7. Mortgage — amortisation simulator

One fixed-rate loan in `config/loan.json`; three endpoints (state,
schedule, config) recompute everything **from origination on every
request** — completely stateless, no cache, no DB. `simulate.py` is
the house's cleanest pure module: frozen `Loan` dataclass in,
deterministic result out.

### Mortgage invariants

- **All money is `Decimal`, quantised to 2dp `ROUND_HALF_UP` at every
  step** — each period's interest, principal portion, and running
  balance. Rounding compounds into the next period's accrual: that is
  the reference behaviour, not drift to clean up.
- **Money crosses the wire as strings** (never JSON numbers) to
  preserve precision — asserted by `test_mortgage_routes.py`.
- Day count is **Actual/365, hardcoded, not leap-aware**. Payment
  dates shift **forward over weekends only** (no holiday calendar),
  and the next accrual window tracks the *adjusted* dates.
- The first payment falls in the month **after** origination; the
  final payment is trimmed to exactly principal + accrued interest;
  a paid-off loan returns explicit zeros and `next_payment_date: None`
  (the frontend keys off that null).
- `payment_day_of_month` is capped at 28 **on the write path only**
  (pydantic); `load_loan` revalidates nothing, so a hand-edited 31
  produces a 500 on Feb dates. The cap is the guard — don't relax it.
- `remaining_loan` = principal + accrued interest, while the equity
  panel uses principal alone as debt — two distinct figures by design.
  The equity diagram clamps equity at 0 when underwater and does its
  arithmetic in JS Number (visual proportion only — acceptable).
- `generate_schedule` caps iterations at 2× tenor (360 fallback) so
  negative amortisation truncates instead of hanging; a truncated
  schedule correctly reports `payoff_date: None`; `payoff_date`
  otherwise equals the last row's payment date (tested).
- `property_value` is optional for backward compatibility and is
  **omitted** from `loan.json` when unset (not written as null).
- ⚠ **Known hazard:** an `as_of` before `origin_date` produces
  negative accrued interest (no guard), and `simulate_state`'s loop
  has no iteration cap. Harmless in normal use; fix as its own change.

## 8. Sessions & state

- Outflows and Assets keep multi-request state in an in-memory
  `SESSIONS: dict[str, dict]` in their routers. **The process is the
  session store, by design** — single user, single process; a restart
  clears sessions and the frontend re-compiles. Sessions are never
  evicted (each compile parks a DataFrame for the process lifetime) —
  accepted for a tool restarted daily. Do not wrap this in a
  repository abstraction; it is not a bug.
- Claims has no sessions — **SQLite is the state**, one connection per
  request. Mortgage is fully stateless — every request re-reads
  `loan.json` and re-simulates from origination.
- Durable state is per-app files only (see README's data-layout table).
  **No shared database across sub-apps** — a standing rule from the
  consolidation.

## 9. Backend/frontend ownership

**Backend owns:** parsing, categorisation, dedup rules, all financial
calculation, guessing, validation, persistence, history/rollback.
**Frontend owns:** selection, sorting, filtering, presentation, and
temporary UI state (`sessionStorage` for filters and session ids).
If a rule affects what lands in a file or DB, it lives in Python.

## 10. Error-handling philosophy

Three deliberate modes — when adding code, pick one explicitly:
- **Fail loudly** (default): config loaders raise `ValueError` on
  malformed values; routers map to 4xx/5xx with a human-readable
  `detail`.
- **Best-effort, visibly degraded**: guessing, detection, the history
  layer, version badge — failures log a loud warning or surface a hint,
  and the primary operation stands.
- **Silent `except: pass`** is reserved for genuinely cosmetic
  operations (e.g. sessionStorage writes in JS). If you find one
  guarding anything financial, that is a bug.

## 11. Testing

```
tests/
├── conftest.py            session app fixture + autouse guard that points
│                          outflows' DB_PATH into tmp_path for EVERY test —
│                          no test may ever touch real data/ or its history
├── test_outflows_routes.py  route-level flows incl. history + backup + detect
├── test_db_history.py       history unit tests (tmp repos, git-missing path)
├── test_guess.py            rapidfuzz core + guess endpoints (engine stubbed)
├── test_guess_embed.py      embedding engine with fake encoder (no model/network)
├── test_assets_routes.py / test_claims_routes.py / test_mortgage_routes.py
├── test_fx_rates.py / test_pipeline_privacy.py / test_server_boots.py
```

Rules of the suite: **no network, no real model, no real data**. The
transformer engine is exercised via injected fake encoders; the
git-missing path is covered by PATH manipulation. One gap learned the
hard way: `test_detect_endpoint` stubs the parsers, so it cannot see
parser *overlap* — real-file regression tests
(`test_detect_manual_template_wins_over_format_a`) exist for that; add
one whenever a detection bug is fixed.

**Coverage is lopsided** (know this before trusting green): outflows is
well-covered; assets is tested only on the FX-precedence and
price-privacy paths (the parsers and the UNMAPPED/lookthrough rules
have no tests); claims has route-existence checks but **zero logic
tests** (`compute_status`, `outstanding`, filename building, the
`toggle_flag` whitelist); mortgage has three smoke assertions (no test
of weekend shifting, final-payment trimming, or Actual/365 accrual).
The invariants in §§5–7 are the spec for the tests those apps lack.

## 12. How to extend

**A new statement format (outflows):** write
`parsers/format_g.py::parse(file_bytes, filename)` that raises on
anything that isn't its format (the parser IS the fingerprint);
register it in `PARSERS`; map an account to it in `accounts.yaml`; add
a real-file fixture test; check `/detect` doesn't now tie with an
existing parser — if it legitimately does, extend
`DETECT_PRECEDENCE` with the stricter fingerprint.

**A new DB write path (outflows):** don't. Route it through the five
functions in `db.py` so the history checkpoint fires.

**A new sub-app:** copy the folder shape (`router.py` with
`views_router`/`api_router`, own `templates/static/config/data`),
mount it in `server.py`, give it its own persistence. Use
`db_history.py`/`guess.py` as the style template: pure core, callers
own I/O, config validated loudly.
