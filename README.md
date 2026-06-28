# Abicus

A local-only personal-finance dashboard. Combines four sub-apps — **My Outflows**, **My Assets**, **My Claims**, **My Loan** — under one FastAPI server with a single Cloudflare-style sidebar UI.

Localhost only, single-user, no auth. The build spec lives in [`SPEC.md`](SPEC.md).

```
http://127.0.0.1:8765/
├── /outflows  — statement parser + categoriser (xlsx/csv → categorised xlsx + HTML snapshot)
├── /assets    — portfolio compiler (broker statements → holdings + allocation charts + PDF)
├── /claims    — medical-claims tracker (SQLite + invoice file storage)
└── /loan      — mortgage snapshot + amortisation schedule
```

---

## Install

Requires Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For running tests:

```sh
pip install -r requirements-dev.txt
```

---

## Backfill from existing local installs (first run)

The four sub-apps ship empty `config/` and `data/` folders. The migration script copies real user data from the legacy repos.

```sh
bash scripts/migrate_from_legacy.sh
```

Defaults assume the legacy repos live at:
- `~/Projects/Tools/spending_review/`
- `~/Projects/Tools/Portfolio-Ag/`
- `~/Projects/Tools/mediclaim/`
- `~/Projects/Tools/mortgage-tracker/`

Override with env vars: `OUTFLOWS_SRC=… ASSETS_SRC=… CLAIMS_SRC=… LOAN_SRC=… bash scripts/migrate_from_legacy.sh`.

The script is idempotent — re-running it prints `SKIP …` lines for files that already exist. Pass `--force` to overwrite.

---

## Run

```sh
python -m abicus            # opens http://127.0.0.1:8765/ in your browser
python -m abicus --no-browser
python -m abicus --port 9000 --reload    # dev mode
```

Or use the wrapper script: `./run.sh`.

`/` redirects to `/outflows`.

---

## Per-sub-app data layout

Each sub-app keeps its own folder; `config/` and `data/` are gitignored.

| Sub-app | `config/` | `data/` |
|---|---|---|
| outflows | `categories.txt`, `accounts.yaml`, `mapping.xlsx`, `mapping.json`, `transaction_history.xlsx` | — |
| assets   | `sources.yaml`, `asset_class_labels.csv`, `mapping_asset_class.csv`, `mapping_broad_asset_class.csv`, `mapping_us_situs.csv`, `currency_lookthrough.csv`, `fx_rates_cache.json` | `last_compiled.parquet`, `last_compiled_meta.json` |
| claims   | `claimants.json`, `institutions.json` | `mediclaim.db`, `invoices/*` |
| loan     | `loan.json` | — |

To seed a fresh install without the migration script, copy your own files into the corresponding `apps/<name>/config/` and `apps/<name>/data/` paths.

---

## Tests

```sh
pytest -q
```

Smoke tests verify that the server boots, every sub-app renders, every legacy route is reachable, and the loan endpoint preserves Decimal precision in its JSON payload. No integration tests against real statement files.

---

## Tech notes

- One FastAPI app at `127.0.0.1:8765`. Each sub-app exposes two routers (`views_router`, `api_router`) wired under `/<name>` and `/api/<name>` respectively.
- Templates resolved via a `ChoiceLoader[shell, PrefixLoader{outflows,assets,claims,loan}]` — each per-app `page.html` references shell partials with `{% extends "base.html" %}`.
- Vanilla HTML / CSS / JS — no bundler. Plotly + Tabulator load from CDN on the pages that need them.
- Each sub-app keeps its own persistence (SQLite, parquet, xlsx, json). No shared database.
- SESSIONS dicts are per-process and in-memory — re-Compile after a restart.

---

## Build history

See `git log feat/initial-build --oneline` for the per-milestone commits (M0–M7) — each follows the §19 milestone plan in the spec.
