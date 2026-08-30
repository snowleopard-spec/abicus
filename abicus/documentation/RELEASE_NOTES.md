# Abicus — Release Notes

Newest release at the top. Versions correspond to git tags on the repo.

---

## Unreleased

*New: sortable transaction panels.* The Unmapped, Excluded, Duplicates
and Refunds panels have clickable column headers: click to sort
ascending (▲), click again to flip (▼). Date, Description, Amount and
Account are sortable (plus Category on Excluded); amounts sort
numerically, text case-insensitively. Each panel keeps its own sort
independently and it persists with the session, like the table filters.
Until a header is clicked, rows keep their natural statement order.

*Naming locked in: Outflows · Assets · Claims · Mortgage.* The four app
names are now canonical everywhere — tabs, page titles, routes, code and
docs. The `loan` app is renamed `mortgage` end to end: directory
(`apps/mortgage/`), routes (`/mortgage`, `/api/mortgage`), template
prefix, `data-active` key, static files (`mortgage.css/js`), test file,
and user-facing labels ("Edit mortgage"). Domain vocabulary inside the
simulator (the `Loan` class, `loan.json` config, `remaining_loan` API
field) deliberately keeps its financial meaning — a mortgage is a loan;
only the app identity was renamed. The frozen build spec and the legacy
migration script's source references are untouched as historical record.

*New: app tabs replace the sidebar (shell-wide).* The sidebar is gone;
a slim topbar carries the Abicus brand and an app-level pill bar —
Outflows · Assets · Claims · Mortgage — in the same "option 4" style,
centred so the brand never shifts it. The pill styling is promoted into
the shell as shared `.pill-tabs` classes used by both tab levels, so the
app bar and the outflows page bar are one implementation. The active app
pill is driven by `body[data-active]` and fills with each app's own
accent colour. Navigation is now fully nested: top level picks the app,
second level (on Outflows) picks the page.

*New: segmented tab bar.* The four outflows pages — Spending Review,
Monthly Breakdown, Transaction History Table, Mapping Table — are now
navigated by a pill tab bar in the page header ("option 4" of the tab
reference in `icons/`): a stadium container with the active page as a
solid filled pill (accent brown), thin dividers between inactive tabs.
Built as one shared `_tabs.html` partial included by all four templates;
it replaces the old back/edit button links, while page-specific actions
(Save changes, Export PDF) remain beside it. The bar is absolutely
centred in the header so those buttons never shift its position between
pages.

*New: saved states.* The whole working session can be saved and reopened
later — across app restarts.

- **Save state** (next to the date range) writes one JSON document to
  `data/states/<name>.json`: the compiled rows (every panel — Categorised,
  Unmapped, Excluded, Duplicates, Refunds — is derived from them, so
  nothing else needs storing), the date range, table filters, all per-row
  ⟲/+/× overrides, and provenance (saved-at, app version, source
  filenames, schema version).
- **Saved states** picker on the upload card lists states newest-first,
  with Load and Delete. Loading rebuilds a fresh server session and puts
  everything back exactly as saved.
- Loaded states are **frozen as of the save** — mapping/history changes
  made since do not silently alter them. A *Re-categorise with current
  rules* button applies today's rules on demand.
- `data/states/` sits under the gitignored per-app data directory:
  state files contain full transaction data and can never reach git.

*Fixes: highlight-to-map and category dropdown.*

- The category dropdown (from `+H` or a highlight) is now scrollable — the
  close-on-scroll guard was also catching scrolls *inside* the menu and
  dismissing it. It also opens on whichever side of the anchor has more
  room and clamps its height to the available space, so the full category
  list is always reachable.
- The highlight bubble no longer includes the trailing space the browser's
  word-snap selection adds: on mouse-lift the selection is shrunk to its
  trimmed edges, so the bubble shows exactly the substring that becomes
  the rule. (Stored rules were never affected — the text was always
  trimmed, and matching is whitespace-insensitive.)

*Fix: whitespace-insensitive matching.* Statement exports pad description
fields with space runs and newlines (e.g. UOB:
`EVERYDAY APP             SINGAPORE    SG` + a `Ref No:` line) that HTML
collapses when rendered — so a rule created with highlight-to-map carried
single spaces and never matched the raw text. Matching is now
whitespace-normalised on both sides everywhere, via a shared
`categorise.normalise_text()` (lowercase + collapse whitespace runs):
substring rules, the history exact-match layer, mapping keys at build and
load (existing `mapping.json`/`mapping.xlsx` files work unchanged),
history dedupe/upsert keys, and both immediate-recategorisation
endpoints. No rule a human writes can depend on invisible padding.

*New: Refund transactions panel.* Refunds/credits (amount ≤ 0) are no
longer silently dropped at compile: they are kept, hidden from the
dashboard by default, and listed in a new *Refund transactions* panel
under Duplicates. Each row has the same light-green **+** as the excluded
panel to include it in the dashboard (its negative amount then counts in
the totals and is committed to the DB); downloads and history append
still exclude refunds. The "Refunds dropped" metric is unchanged.

*Outflows polish after v2.1.2:*

- Header: breadcrumb ("Tools / My Outflows") and the version chip
  removed; "Edit history" / "Edit mapping" renamed to
  "Transaction History Table" / "Mapping Table".
- The Downloads / Database / Unmapped Help headers now match the card
  titles (same size and font as "Categorised Transactions").
- The description search box is wider.
- "Show matched pattern" is now a checkbox pill, matching the
  Hide-balances control in Assets.
- Download/database captions trimmed to one line each.
- The page background is the shell grey top to bottom (cards, panels and
  sidebar stay light).

- The explainer paragraphs on the *Unmapped transactions* and *Excluded
  transactions* panels are removed — tables start right under the summary
  line. The empty-state messages ("Every transaction was mapped. Nice.")
  remain.
- The two per-file dropdowns on upload have fixed widths (account 8rem,
  label 14rem) so they align as columns across file rows.
- `accounts.yaml` reworked (local config, not in git): account names are
  now bank-level groupings — Amex, OCBC, UOB, HSBC, Revolut, Manual — each
  carrying an explicit `labels:` list of its cards.

*Documentation:*

- `abicus/documentation/` started: this release-notes file, plus
  `RAPIDFUZZ_SPEC.md` — a ready-to-run spec for swapping the planned
  description-guess engine from pure-Python LCS to rapidfuzz (C++ binary
  wheels), including background on how compiled extensions integrate into
  a Python project. Not scheduled; triggers when the corpus outgrows pure
  Python.

*New feature:*

- **Category guesser for unmapped rows** (`guess.py`). Each unmapped row
  gets a best-guess category in a new Guess column (after Amount), shown
  as a clickable blue pill — `≈ Groceries`, with the matched historical
  description and score in the tooltip. Clicking accepts: the row is filed
  to `transaction_history.xlsx` with the guessed category via the same
  endpoint as `+H`, with the same immediate recategorisation.
  - Metric: free-deletion edit distance — substitutions cost 1, deletions
    from the query are free (equivalently `len(candidate) − LCS`), so
    reference numbers and prefixes cost nothing. Score = fraction of the
    known description matched.
  - Corpus: description → category pairs from `transactions.db`
    (most-recent commit wins per description) and the filled-in rows of
    `transaction_history.xlsx` (history wins on conflict). Categories not
    in `categories.txt` are never suggested.
  - Guardrails in `config/guess.yaml` (optional; defaults in code):
    `min_score` and `min_candidate_length`. Calibrated leave-one-out on
    the real 693-description corpus: min_score **0.90** (default) → 85%
    precision at 67% coverage; 0.85 → 79%/89%. Precision favoured — a
    wrong guess is worse than no guess.
  - Guessing runs server-side as a best-effort async pass after Compile /
    restore; pills appear when ready and refresh after history or mapping
    changes. No guess clears the bar → the cell is simply empty.

---

## v2.1.2 — Statement format auto-detection (2026-08-29)

*Outflows.* Dropping a file onto the upload zone now auto-detects its
format and pre-selects the account dropdown.

- **Detection is try-parsing**: a new `/detect` endpoint runs the file
  through every registered parser; the parsers' own strict header
  validation is the format fingerprint. Detection therefore can never
  disagree with what Compile would accept, and it stays correct
  automatically when a parser evolves.
- **No new config**: the format → account mapping is derived by inverting
  `accounts.yaml` at request time.
- Each file row shows a small badge with the outcome:
  - **✓ \<account\>** (green) — exactly one format matched, mapping to
    exactly one account: the dropdown snaps to it.
  - **? not recognised** (amber) — no parser accepted the file (new or
    unknown format): nothing is auto-set; pick manually.
  - **~ ambiguous** (amber) — the file parses under more than one format:
    no guess is made; the tooltip lists the candidates.
  - **✓ \<format\> — pick account** (amber) — format detected but several
    accounts share it: the account choice stays yours.
- A manual dropdown change supersedes detection and clears the badge.
  Server-side validation on Compile is unchanged, so detection can help
  but never silently mislead.

---

## v2.1.1 — Parser / label separation (2026-08-29)

*Outflows.* The per-file selection on upload is now two dropdowns instead of
one, separating **which parser reads the file** from **which label the rows
carry** in the Account column.

- **Account dropdown (first)** — unchanged from legacy: the friendly account
  names from `accounts.yaml`, each mapped to its parser format
  (e.g. UOB → Format C).
- **Label dropdown (second)** — the value written to the Account column,
  constrained to the account's permissible set. Each `accounts.yaml` entry
  carries a `labels:` list; when omitted it defaults to the account name
  itself, which reproduces the old behaviour exactly.
- Account names can act as **groupings**: one `UOB` entry whose labels are
  the individual cards (One Card, Supplementary, Black Card) replaces
  separate per-card entries.
- The label constraint is **enforced server-side**: `/compile` rejects a
  label outside the chosen account's set, listing what is allowed.
- The "unfamiliar accounts" warning for pre-labelled files (Format F) now
  checks values against the union of all labels, not the account names.
- `pyproject.toml` version bumped to 2.1.1.

**Config example:**

```yaml
accounts:
  - name: "UOB"
    format: "Format C"
    labels:
      - "UOB One Card"
      - "UOB Supplementary Card"
      - "UOB Black Card"
```

---

## v2.1 — Unmapped-transaction workflow & dashboard quality of life (2026-08-29)

All changes are to the **Outflows** app.

### +H — categorise an unmapped row into transaction history

Each row in the *Unmapped transactions* panel has a circular **+H** button
(soft blue). Clicking it opens a dropdown of the categories from
`categories.txt`; picking one:

- upserts the row into `config/transaction_history.xlsx` as an exact-match
  rule — filling in the category of an existing blank-category row (from an
  earlier bulk append) rather than duplicating it;
- immediately recategorises every matching row in the live session — charts,
  metrics, table, downloads and DB commits all see the new category with no
  re-upload.

### Highlight-to-map — turn a selected substring into a mapping rule

Selecting text inside a description cell in the *Unmapped transactions*
panel draws a raised, rounded, translucent **orange bubble** over the
selection (a custom overlay — the string stays readable underneath).
Releasing the mouse opens the same category dropdown; picking a category:

- adds the highlighted substring as a rule via the mapping table layer —
  written to **both** `mapping.xlsx` and `mapping.json`, so the next rebuild
  cannot clobber it; an existing rule for the same substring is re-pointed,
  not duplicated;
- immediately recategorises every unmapped session row whose description
  contains the substring. Rows already matched by another rule are left to
  the next Compile's full longest-match pass.

### Search box on Categorised Transactions

A search field next to the Category/Account filters. Case-insensitive
substring match on description; stacks with the other filters and persists
across navigation like they do.

### × — exclude a single transaction by hand

Each row of the Categorised Transactions table ends in a circular **×**
button (filled in the table-header tone). Clicking it hides the transaction
from the dashboard:

- it moves to the *Excluded transactions* panel, where the light-green **+**
  button (previously ⟲) brings it back;
- metrics, chart and table update immediately; the "Hidden from dashboard"
  caption reports hand-excluded rows separately;
- **DB commits skip it** — what you see is what gets committed;
- downloads still include everything, matching category-exclusion semantics;
- exclusions persist for the session (survive refresh), like the other
  per-row overrides.

### Matched pattern column hidden by default

The Categorised Transactions table starts without the *Matched pattern*
column; a small **Show/Hide matched pattern** button at the right of the
filter row toggles it. The preference persists with the other table filters.

### Bottom box regrouped

The flat tile grid is now three headed columns:

| Downloads | Database | Unmapped Help |
|---|---|---|
| Download categorised (Excel) | Commit to database | Download unmapped (Excel) |
| Download HTML snapshot | Clear database | Append unmapped to history |

### Colour-coded row actions

- **+** (re-include excluded) — light green
- **+H** (add to history) — soft blue
- **×** (exclude) — beige fill matching the table header
- **⟲** (un-suppress duplicate) — unchanged neutral
