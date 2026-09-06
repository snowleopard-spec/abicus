# Spec — Abicus V3.1: defects + the safety net

> **Status: implemented — released as 3.1.0, 2026-09-06.** One defect
> beyond the planned four was discovered during M5 and fixed in the
> same release: blank mapping values were read back as NaN and slipped
> past the parsers' blank guard (see release notes). Build contract in the house style: resolved
> decisions up front, then numbered verify-before-continue milestones,
> each sized to one ~15-minute session and ending with the app usable.
> Do not start a milestone before the previous one's "Done when" line
> is verifiably true.

---

## 1. Context & motivation

Two external refactoring reviews (2026-09-06) and the writing of
`ARCHITECTURE.md` produced a full audit of the codebase. The
structural recommendations were largely rejected (reasons recorded in
ARCHITECTURE.md); what survived is small and concrete:

- **Four real defects**, one of which can corrupt money figures
  (the `.L` pence double-division).
- **A lopsided test suite**: outflows is well-covered; claims has zero
  logic tests, mortgage three smoke assertions, and the assets parsers
  none. The invariants in ARCHITECTURE.md §§5–7 are the written spec
  for exactly the tests that are missing.

V3.1 fixes the defects and builds the safety net. **No restructuring,
no new features, no behaviour changes beyond the fixes themselves.**

## 2. Resolved decisions — do not re-litigate

- **R1 — Stock-price storage convention: raw quotes, always.** The
  price cache (`fetched_prices`, and `stock_prices` in
  `last_compiled_meta.json`) holds prices **exactly as yfinance quotes
  them** — pence for `.L` tickers. The pence→pounds conversion happens
  at the point of use (balance computation in `parsers/manual.py`) and
  is **never written back to storage**. This makes save → reload →
  recompile idempotent. Existing saved metas may hold pounds for `.L`
  tickers; one recompile-and-save after the fix heals them — no
  migration code.
- **R2 — Pre-origin `as_of` is a 400, not a clamp.** `simulate_state`
  raises `ValueError` when `as_of < origin_date`; the router maps it
  to 400 with a human-readable detail. Guessing what a pre-origin
  query "means" would be silent invention. `simulate_state` also gains
  the same 2×-tenor iteration cap `generate_schedule` already has.
- **R3 — Claims is SGD-only, enforced.** `create`/`update` reject any
  `currency != "SGD"` with a 400. The column stays (schema untouched)
  and the frontend keeps its hard-prefixed "SGD" — which is now honest
  rather than silently wrong. Multi-currency claims are a non-goal.
- **R4 — Excel export: full master is the contract.** The Excel
  download deliberately ignores view options — make that explicit by
  removing the unused `DownloadOptions` body from the Excel endpoint
  (the PDF endpoint keeps it; it uses them). Not feature work to
  "honor" options nobody asked for.
- **R5 — The version chip gets plumbed, not deleted.** `base.html`
  renders `{{ version }}` in the existing `.version-chip` style. One
  line each side; closes the wired-up-but-unplumbed loose end.
- **R6 — Fixture files are fabricated, never real.** Parser fixtures
  are synthetic files hand-built to each format's shape (Broker A's
  sheet/date structure, Broker C's positional columns, the manual
  template). No real statement, balance, or holding ever enters the
  repo — same rule as the rest of the suite: no network, no real
  model, no real data.
- **R7 — The invariants are the test spec.** Each new test names the
  ARCHITECTURE.md invariant it pins (e.g. `# C-1`, `# M-3`, `# A-6`
  style comments). A test that fails because an invariant changed on
  purpose means updating ARCHITECTURE.md in the same commit.

## 3. Non-goals

- No restructuring: no service classes, no sessions abstraction, no
  app registry, no `pipeline.py` split, no docs moves. (Rejected with
  reasons; see ARCHITECTURE.md and the 2026-09-06 review discussion.)
- No multi-currency claims (R3). No Excel view options (R4).
- No packaging consolidation or ruff adoption — fine ideas, separate
  chore, not this spec.
- No CDN vendoring for assets/mortgage pages — noted in
  ARCHITECTURE.md as a known inconsistency; do it opportunistically.
- No holiday calendar, no leap-aware day count (mortgage stays
  Actual/365, weekend-shift-only — documented invariants).

## 4. Milestones

- **M1 — Assets: `.L` price round-trip.** Apply R1: the manual parser
  computes balances from the converted price but stores the raw quote;
  `_cached_stock_prices` semantics unchanged. **Done when:** a test
  drives compile → save → reload → recompile with a `.L` ticker
  through a fake resolver and asserts the price is divided exactly
  once end-to-end (the existing single-pass test stays green), and the
  full suite passes.
- **M2 — Mortgage: guards.** Apply R2: pre-origin `ValueError` → 400
  at all three endpoints that take dates where relevant; iteration cap
  in `simulate_state`. **Done when:** tests cover the 400 (message
  names the origin date) and a negative-amortisation loan state call
  returns rather than hanging; suite green.
- **M3 — Claims SGD enforcement + Excel/version tidy.** Apply R3, R4,
  R5. **Done when:** a non-SGD create/update 400s with a clear detail;
  the Excel endpoint takes no body and still downloads; the version
  chip renders on every page (`data-active` test extended to assert
  it); suite green.
- **M4 — Claims + mortgage logic tests.** Pin the invariants:
  `compute_status` cascade order and exact strings (C-1), the
  `outstanding` three-branch clamp (C-2), the `toggle_flag` whitelist
  as injection guard (C-9), invoice filename building + collision
  suffixes + missing-date sentinel (C-15/16), archive-vs-permanent
  delete semantics (C-13/14); mortgage weekend forward-shift (M-3),
  first-payment month (M-4), final-payment trim (M-6), paid-off shape
  (M-7), Actual/365 accrual arithmetic on a hand-computed example
  (M-1/M-2). **Done when:** each named invariant has at least one
  test that fails if its rule is changed; suite green.
- **M5 — Assets parser fixtures.** Synthetic fixture files (R6) under
  `tests/fixtures/assets/`, one per parser, plus targeted tests:
  Broker A latest-date-wins and Cash/Position-Values filter (A-4),
  hard-coded-class-beats-CSV and blank-mapping→UNMAPPED (A-1/A-2),
  Broker C positional columns and forex no-reconvert (A-5/A-6),
  manual Auto-Calc `"TRUE"` matching and missing-resolver degradation
  (A-14/A-15). **Done when:** all parsers have fixture-driven tests;
  deliberately corrupting a fixture's column order fails the Broker C
  test; suite green.
- **M6 — Release 3.1.0.** Version bump, release-notes entry (defects
  fixed, tests added, invariant references), this spec's status line
  flipped, tag pushed. **Done when:** notes and tag match the shipped
  state.

## 5. Acceptance checklist (V3.1 done)

- [ ] `.L` save/reload/recompile round-trip divides by 100 exactly
      once; stored prices are raw quotes (R1).
- [ ] Pre-origin `as_of` → 400; `simulate_state` cannot loop forever.
- [ ] Non-SGD claims rejected; Excel endpoint takes no options; the
      version chip renders on every page.
- [ ] Claims and mortgage invariants from ARCHITECTURE.md §§6–7 each
      pinned by a failing-if-changed test.
- [ ] Every assets parser has a fabricated fixture file and tests for
      its ARCHITECTURE.md invariants; no real data in the repo.
- [ ] Full suite green; version 3.1.0 tagged; release notes written;
      ARCHITECTURE.md updated wherever a rule intentionally changed.
