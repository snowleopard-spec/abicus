# Abicus — Release Notes

Newest release at the top. Versions correspond to git tags on the repo.

---

## Unreleased

*Outflows polish after v2.1.2:*

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

- `apps/documentation/` started: this release-notes file, plus
  `RAPIDFUZZ_SPEC.md` — a ready-to-run spec for swapping the planned
  description-guess engine from pure-Python LCS to rapidfuzz (C++ binary
  wheels), including background on how compiled extensions integrate into
  a Python project. Not scheduled; triggers when the corpus outgrows pure
  Python.

*In design (not yet built):*

- **Category guesser for unmapped rows** — a free-deletion edit distance
  (substitutions cost 1, deletions from the query free — equivalently
  `len(candidate) − LCS`) scored against the description → category pairs
  in `transactions.db` and `transaction_history.xlsx`; best guess shown as
  a clickable blue pill after Amount, accepting it files the row to
  history via the existing `+H` endpoint.

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
