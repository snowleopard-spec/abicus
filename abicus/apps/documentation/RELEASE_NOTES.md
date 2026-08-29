# Abicus — Release Notes

Newest release at the top. Versions correspond to git tags on the repo.

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
