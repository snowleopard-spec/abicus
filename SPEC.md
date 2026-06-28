# Abicus — Build Spec

> ### Starter prompt (paste into a fresh Claude Code session)
>
> Read `ABICUS_BUILD_SPEC.md` end-to-end before doing anything else.
>
> Start at **§18 (Resolved decisions)** to see the locked-in choices, then **§19 (Milestones)** to see the eight checkpoints you must stop at — at the end of each milestone, commit, post a short status, and wait for me to verify before starting the next one.
>
> Follow the **§14 build order**. The four legacy repos listed in **§17.1** are already present locally — run `scripts/migrate_from_legacy.sh` (per §17.2) after M1 to backfill real user data into the new layout.
>
> Reference `Image.png` (in the repo root) for the sidebar visual target.
>
> Drill into §§ 6–11 for per-component detail as each milestone needs them. Do not deviate from §18's resolved decisions without confirming with me first.

---

A local-only personal-finance dashboard that unifies four pre-existing Python apps behind a single FastAPI server and a Cloudflare-style sidebar UI.

This document is the contract for the build. It is meant to be opened in a fresh Claude Code session with no prior context and followed end-to-end.

---

## 1. High-level goals

- Combine four existing sub-apps under one FastAPI process at `127.0.0.1:8765`.
- One sidebar (Cloudflare-style) navigates between sub-apps; no functionality from any sub-app is dropped.
- Sub-apps are renamed in the UI as **My Outflows**, **My Assets**, **My Claims**, **My Loan**.
- All four sub-apps share a single, unified visual design (CSS variables, components, typography).
- Each sub-app keeps its own folder with its own Python modules, templates, static assets, and config.
- One combined `requirements.txt` at the repo root.
- Localhost-only, single-user. No auth.

### Non-goals
- No cross-app dashboard / homepage. `/` redirects straight to the first sub-app.
- No shared database. Each sub-app keeps its existing persistence (SQLite, parquet, xlsx, json).
- No cloud deploy, no Docker, no CI. Run locally via `python -m abicus` (or equivalent).
- No build pipeline (no React/Vite/webpack). Vanilla HTML + CSS + JS only, matching all four originals.
- No multi-user/auth/sessions beyond the existing in-memory `SESSIONS` dicts.

---

## 2. Source material

Four reference repos have already been cloned to `/tmp/abicus-research/` during the spec phase. If they are no longer present, re-clone:

| Sub-app folder | Source repo | Branch |
|---|---|---|
| `apps/outflows/` | `https://github.com/snowleopard-spec/spending_review` | `feat/fastapi-ui` |
| `apps/assets/`   | `https://github.com/snowleopard-spec/folio-allocation` | `feat/fastapi-ui` |
| `apps/claims/`   | `https://github.com/snowleopard-spec/mediclaim` | `main` |
| `apps/loan/`     | `https://github.com/snowleopard-spec/MortgageMonitor` | `main` |

Treat the source Python modules (parsers, categorisers, simulators, DB code) as **black-box, copy-as-is**. Only the FastAPI entry point becomes an `APIRouter`, and each `static/index.html` is replaced with the unified design.

---

## 3. Repository layout

```
abicus/
├── pyproject.toml                 # Optional; keep minimal — single requirements.txt is canonical
├── requirements.txt               # Combined deps for all sub-apps + shell
├── README.md                      # How to install + run
├── run.sh                         # convenience: uvicorn abicus.server:app --host 127.0.0.1 --port 8765
│
├── abicus/                        # Top-level umbrella package
│   ├── __init__.py
│   ├── __main__.py                # `python -m abicus` → boots uvicorn
│   ├── server.py                  # FastAPI app, mounts each sub-app's router
│   ├── shell/                     # Shared shell (sidebar, header, base template)
│   │   ├── templates/
│   │   │   ├── base.html          # Jinja2 base: sidebar + header + {% block content %}
│   │   │   └── _sidebar.html      # Included by base
│   │   └── static/
│   │       ├── css/
│   │       │   ├── tokens.css     # CSS custom properties (colors, spacing, type)
│   │       │   ├── shell.css      # Sidebar, header, layout
│   │       │   └── components.css # Buttons, tables, cards, forms, dropzones, etc.
│   │       ├── js/
│   │       │   ├── shell.js       # Sidebar collapse, active-link, search box
│   │       │   └── api.js         # Tiny fetch wrapper (handles JSON, file uploads, errors)
│   │       └── img/
│   │           └── logo.svg
│   │
│   └── apps/
│       ├── __init__.py
│       │
│       ├── outflows/              # was: spending_review
│       │   ├── __init__.py
│       │   ├── router.py          # APIRouter — replaces app.py
│       │   ├── views.py           # HTML routes (renders templates/page.html)
│       │   ├── categorise.py      # ← copied from source
│       │   ├── categories.py      # ← copied
│       │   ├── accounts.py        # ← copied
│       │   ├── transaction_history.py
│       │   ├── build_mapping.py
│       │   ├── html_export.py
│       │   ├── parsers/           # ← copied as-is
│       │   │   ├── __init__.py
│       │   │   ├── format_a.py … format_f.py
│       │   ├── templates/
│       │   │   └── page.html      # extends shell/base.html
│       │   ├── static/
│       │   │   ├── outflows.js    # vanilla JS + Plotly + Tabulator (CDN)
│       │   │   └── outflows.css
│       │   └── config/            # gitignored — runtime user data
│       │       ├── categories.txt
│       │       ├── accounts.yaml
│       │       ├── mapping.xlsx
│       │       ├── mapping.json
│       │       └── transaction_history.xlsx
│       │
│       ├── assets/                # was: folio-allocation
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── views.py
│       │   ├── fx_rates.py        # ← copied
│       │   ├── parsers/           # ← copied
│       │   │   ├── broker_a.py
│       │   │   ├── broker_c.py
│       │   │   └── manual.py
│       │   ├── templates/
│       │   │   └── page.html
│       │   ├── static/
│       │   │   ├── assets.js
│       │   │   └── assets.css
│       │   ├── config/
│       │   │   ├── sources.yaml
│       │   │   ├── asset_class_labels.csv
│       │   │   ├── mapping_asset_class.csv
│       │   │   ├── mapping_broad_asset_class.csv
│       │   │   ├── mapping_us_situs.csv
│       │   │   ├── currency_lookthrough.csv
│       │   │   └── fx_rates_cache.json
│       │   └── data/              # gitignored — session persistence
│       │       ├── last_compiled.parquet
│       │       └── last_compiled_meta.json
│       │
│       ├── claims/                # was: mediclaim
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── views.py
│       │   ├── db.py              # SQLite init + helpers (extracted from app.py)
│       │   ├── files.py           # invoice/other-doc filename safety + paths
│       │   ├── status.py          # compute_status() pure function
│       │   ├── templates/
│       │   │   └── page.html
│       │   ├── static/
│       │   │   ├── claims.js
│       │   │   └── claims.css
│       │   ├── config/
│       │   │   ├── claimants.json
│       │   │   └── institutions.json
│       │   └── data/              # gitignored
│       │       ├── mediclaim.db
│       │       └── invoices/      # invoice files + other docs
│       │
│       └── loan/                  # was: MortgageMonitor — NEW api + ui
│           ├── __init__.py
│           ├── router.py
│           ├── views.py
│           ├── simulate.py        # extracted from cli.py: simulate_state, helpers
│           ├── templates/
│           │   └── page.html
│           ├── static/
│           │   ├── loan.js
│           │   └── loan.css
│           └── config/
│               └── loan.json
│
└── tests/                         # smoke tests only (see §13)
    ├── test_server_boots.py
    ├── test_outflows_routes.py
    ├── test_assets_routes.py
    ├── test_claims_routes.py
    └── test_loan_routes.py
```

### Folder conventions
- **`config/`** within each sub-app: user-curated inputs (mappings, lists). Gitignored. Committed `*.example` files where helpful.
- **`data/`** within each sub-app: machine-generated state (SQLite, parquet, file uploads). Gitignored.
- **`static/`** + **`templates/`**: shipped with the code; not user-edited.
- Top-level `.gitignore` lines:
  ```
  apps/*/config/
  apps/*/data/
  !apps/*/config/*.example
  __pycache__/
  *.pyc
  .venv/
  ```

---

## 4. Tech stack & dependencies

### Runtime
- Python ≥ 3.11
- FastAPI ≥ 0.115
- Uvicorn ≥ 0.30 (standard extras)
- Jinja2 (for the shared shell template + per-app `page.html` extension)

### Combined `requirements.txt` (root)
Resolved by taking the highest version requested across the four source repos:

```
fastapi>=0.136.1
uvicorn[standard]>=0.47.0
python-multipart>=0.0.29
jinja2>=3.1
pandas==2.3.3
numpy==2.4.2
pyarrow==23.0.1
openpyxl==3.1.5
xlrd==2.0.2
PyYAML==6.0.3
requests==2.32.5
yfinance==1.2.0
reportlab==4.4.10
plotly                  # outflows uses for compile-time chart in HTML export
```

**Note**: drop `streamlit` (the my-loan dashboard is replaced by a FastAPI page). Drop `python-dotenv` if it appears anywhere — no env-driven config in any sub-app.

### Frontend (CDN, no bundler)
- Plotly.js — outflows + assets charts
- Tabulator — outflows + assets tables
- No frameworks (no React/Vue/Svelte). Vanilla JS modules.

---

## 5. Naming & routing convention

| Sub-app | Display name | URL prefix | API prefix | Static prefix |
|---|---|---|---|---|
| outflows | My Outflows | `/outflows` | `/api/outflows` | `/outflows/static` |
| assets   | My Assets   | `/assets`   | `/api/assets`   | `/assets/static`   |
| claims   | My Claims   | `/claims`   | `/api/claims`   | `/claims/static`   |
| loan     | My Loan     | `/loan`     | `/api/loan`     | `/loan/static`     |

- `GET /` → 307 redirect to `/outflows`
- Shared shell static at `/shell/static` (mounted by the umbrella server).

---

## 6. Combined FastAPI server (`abicus/server.py`)

Responsibilities:
1. Create one `FastAPI(title="Abicus")` instance.
2. Mount the shared shell static dir at `/shell/static`.
3. For each sub-app:
   - Mount its `static/` directory at `/<name>/static`.
   - Include its `router.py` APIRouter twice: once with prefix `/<name>` (HTML views), once with prefix `/api/<name>` (JSON API). Recommended: each sub-app exposes two routers — `views_router` and `api_router` — and `server.py` includes them with their respective prefixes.
4. Add `GET /` → `RedirectResponse("/outflows", status_code=307)`.
5. Configure Jinja2 environment with `loader=ChoiceLoader([FileSystemLoader("abicus/shell/templates"), FileSystemLoader("abicus/apps/outflows/templates"), …])` so `extends "base.html"` resolves from any per-app template.

Skeleton:

```python
# abicus/server.py
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from abicus.apps.outflows.router import api_router as outflows_api, views_router as outflows_views
from abicus.apps.assets.router   import api_router as assets_api,   views_router as assets_views
from abicus.apps.claims.router   import api_router as claims_api,   views_router as claims_views
from abicus.apps.loan.router     import api_router as loan_api,     views_router as loan_views

ROOT = Path(__file__).parent

app = FastAPI(title="Abicus")

app.mount("/shell/static", StaticFiles(directory=ROOT / "shell" / "static"), name="shell-static")

for name in ("outflows", "assets", "claims", "loan"):
    app.mount(
        f"/{name}/static",
        StaticFiles(directory=ROOT / "apps" / name / "static"),
        name=f"{name}-static",
    )

# HTML views
app.include_router(outflows_views, prefix="/outflows")
app.include_router(assets_views,   prefix="/assets")
app.include_router(claims_views,   prefix="/claims")
app.include_router(loan_views,     prefix="/loan")

# JSON APIs
app.include_router(outflows_api, prefix="/api/outflows")
app.include_router(assets_api,   prefix="/api/assets")
app.include_router(claims_api,   prefix="/api/claims")
app.include_router(loan_api,     prefix="/api/loan")

@app.get("/")
def root():
    return RedirectResponse("/outflows", status_code=307)
```

### `abicus/__main__.py`
Opens the browser on boot unless `--no-browser` is passed.

```python
import argparse, threading, time, webbrowser, uvicorn

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", default=8765, type=int)
    p.add_argument("--reload", action="store_true", help="Uvicorn auto-reload (dev only)")
    p.add_argument("--no-browser", action="store_true", help="Don't open the browser on boot")
    args = p.parse_args()

    if not args.no_browser:
        url = f"http://{args.host}:{args.port}/"
        def _open():
            time.sleep(0.8)  # give uvicorn a moment to bind
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run("abicus.server:app", host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
```

### `run.sh`
```sh
#!/usr/bin/env bash
set -e
[ -d .venv ] && source .venv/bin/activate
exec python -m abicus "$@"
```

---

## 7. Shared shell (sidebar + header + layout)

### 7.1 Visual reference
Match the Cloudflare-dashboard reference (`Image.png`): white-ish background, left sidebar ~240 px, search box at top of sidebar, grouped link sections with section labels, account header with logo + email at top, sub-app content fills the right pane.

### 7.2 `shell/templates/base.html` (Jinja2)
The header right-hand area shows a small monospace **version chip** (`v0.1.0 · <short-sha>` or just `v0.1.0` if not in a git checkout). The implementer adds an `abicus.version.get_version()` helper that reads `abicus/__init__.py`'s `__version__` and optionally appends `subprocess.check_output(["git","rev-parse","--short","HEAD"])` when available — failures degrade silently to version-only.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Abicus{% endblock %}</title>
  <link rel="icon" href="/shell/static/img/favicon.svg">
  <link rel="stylesheet" href="/shell/static/css/tokens.css">
  <link rel="stylesheet" href="/shell/static/css/shell.css">
  <link rel="stylesheet" href="/shell/static/css/components.css">
  {% block head %}{% endblock %}
</head>
<body data-active="{{ active }}">
  {% include "_sidebar.html" %}
  <main class="content">
    <header class="page-header">
      <h1>{% block page_title %}{% endblock %}</h1>
      <div class="page-actions">
        {% block page_actions %}{% endblock %}
        <span class="version-chip" title="Abicus build">{{ version }}</span>
      </div>
    </header>
    <section class="page-body">
      {% block content %}{% endblock %}
    </section>
  </main>
  <script src="/shell/static/js/api.js"></script>
  <script src="/shell/static/js/shell.js"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

Every `views.py` must inject `version=get_version()` into the template context. The `.version-chip` class lives in `components.css`: small, monospace, muted text colour, subtle border.

Each per-app `page.html` does:
```html
{% extends "base.html" %}
{% block title %}My Outflows · Abicus{% endblock %}
{% block page_title %}My Outflows{% endblock %}
{% block content %} … app-specific markup … {% endblock %}
{% block scripts %}<script src="/outflows/static/outflows.js"></script>{% endblock %}
```

### 7.3 `shell/templates/_sidebar.html`
- **Wordmark** at top: text-only "Abicus" in a slightly heavier weight than body. No icon, no logo asset. Use `--text-primary` colour.
- Search box (placeholder, no behaviour required v1 — keep the input so layout matches the Cloudflare reference).
- Section heading "Tools" with four links:
  - My Outflows → `/outflows`
  - My Assets → `/assets`
  - My Claims → `/claims`
  - My Loan → `/loan`
- Use `data-active` on `<body>` to highlight the matching link: `body[data-active="outflows"] .nav-outflows { … }`.
- Each `views.py` passes `active="outflows"` (etc.) into the template context.

Favicon is a tiny SVG "A" generated inline (no asset to source). Drop the file at `shell/static/img/favicon.svg`.

### 7.4 `tokens.css` (CSS custom properties)
Define a single palette and type scale so all four sub-apps render consistently. Suggested tokens:

```css
:root {
  --bg-app: #f6f7fa;
  --bg-sidebar: #ffffff;
  --bg-card: #ffffff;
  --border: #e6e8ec;
  --text-primary: #1a1f2c;
  --text-secondary: #5b6273;
  --text-muted: #8a90a0;
  --accent: #0b66ff;
  --accent-hover: #0852cc;
  --success: #18794e;
  --warning: #b54708;
  --danger:  #b42318;

  --radius-sm: 4px;
  --radius-md: 8px;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-8: 48px;

  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace;
  --text-xs: 12px; --text-sm: 13px; --text-md: 14px;
  --text-lg: 16px; --text-xl: 20px; --text-2xl: 28px;

  --sidebar-w: 240px;
  --header-h: 56px;
  --shadow-card: 0 1px 2px rgba(16,24,40,.06), 0 1px 1px rgba(16,24,40,.04);
}
```

### 7.5 `shell.css` layout
- Body: `display: grid; grid-template-columns: var(--sidebar-w) 1fr;`
- Sidebar: fixed-position column, scrolls independently.
- `.content`: flex column, header sticky at top.
- All padding/typography uses the tokens above.

### 7.6 `components.css`
Reusable classes for: `.btn`, `.btn-primary`, `.btn-ghost`, `.card`, `.tile`, `.dropzone`, `.input`, `.select`, `.table`, `.tag`, `.status-dot`, `.empty-state`. Each sub-app must use these classes instead of inline-styled equivalents.

### 7.7 `api.js`
A tiny fetch wrapper. All four sub-apps' JS must call it (no raw fetch). Surface a uniform error toast.

```js
const api = {
  async get(url) { return wrap(fetch(url)); },
  async postJson(url, body) {
    return wrap(fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)}));
  },
  async postForm(url, formData) { return wrap(fetch(url, {method:"POST", body: formData})); },
  async putForm(url, formData)  { return wrap(fetch(url, {method:"PUT",  body: formData})); },
  async del(url) { return wrap(fetch(url, {method:"DELETE"})); },
  async download(url, opts={}) { /* returns a Blob; triggers browser save */ },
};
async function wrap(p) {
  const r = await p; if (!r.ok) { throw new Error(await r.text()); } return r;
}
window.api = api;
```

---

## 8. Sub-app spec — **My Outflows** (`apps/outflows/`)

### 8.1 Source mapping
Copy these files from `spending_review` (branch `feat/fastapi-ui`) into `apps/outflows/`, unchanged:
- `categorise.py`, `categories.py`, `accounts.py`, `transaction_history.py`, `build_mapping.py`, `html_export.py`
- `parsers/format_a.py`…`format_f.py`

Replace `app.py` and `static/` with the rewrites below.

### 8.2 `router.py`
Expose two routers:
- `views_router` — GET `/` returns the rendered `page.html` (with `active="outflows"`).
- `api_router` — all `/api/...` endpoints from the original, with paths flattened (drop the `/api` prefix since it's added at mount time):

| Original path | New path under `api_router` |
|---|---|
| `GET  /api/config`                          | `GET  /config` |
| `POST /api/compile`                         | `POST /compile` |
| `POST /api/download/categorised/{sid}`      | `POST /download/categorised/{sid}` |
| `POST /api/download/unmapped/{sid}`         | `POST /download/unmapped/{sid}` |
| `POST /api/download/html/{sid}`             | `POST /download/html/{sid}` |
| `POST /api/history/append/{sid}`            | `POST /history/append/{sid}` |

Request/response shapes are unchanged (see source).

### 8.3 Config folder
Move existing user files into `apps/outflows/config/`:
- `categories.txt`, `accounts.yaml`, `mapping.xlsx`, `mapping.json`, `transaction_history.xlsx`

Module loaders must read from this folder. Where the source code uses relative paths like `"config/mapping.json"`, change them to `Path(__file__).parent / "config" / "mapping.json"`.

### 8.4 Frontend (`page.html` + `outflows.js` + `outflows.css`)
Rebuild the existing dashboard to the unified design but preserve every interaction:
- **Source assignment**: file dropzone → file list with per-file account picker (populated from `/api/outflows/config`).
- **Compile** button → POST `/api/outflows/compile` (multipart with `files` + `accounts[]`).
- **Results panel**: metrics cards (total in range, n transactions, n duplicates, n unmapped, n dropped negatives), Plotly chart by category, Tabulator table with category filter + date range.
- **Downloads**: three buttons (Categorised xlsx, Unmapped xlsx, HTML snapshot) wired to the corresponding endpoints with the date range payload.
- **Append-to-history** button → `/api/outflows/history/append/{sid}` with date range payload; shows toast with `n_added` / `n_skipped`.
- **Warning surfaces**: mapping warnings, history warnings, unfamiliar accounts — render as a dismissible card list.

Style with `.tile`, `.card`, `.btn-primary`, `.dropzone`, `.table` from `components.css`. Plotly + Tabulator loaded from CDN in `{% block head %}`.

---

## 9. Sub-app spec — **My Assets** (`apps/assets/`)

### 9.1 Source mapping
Copy from `folio-allocation` (branch `feat/fastapi-ui`) into `apps/assets/`, unchanged:
- `fx_rates.py`
- `parsers/broker_a.py`, `parsers/broker_c.py`, `parsers/manual.py`
- Any helpers in `app.py` that are pure logic (compile pipeline, `compute_all_allocations`, `apply_currency_lookthrough`, `convert_to_usd`, PDF builder) → extract into a `pipeline.py` module rather than leaving them in `router.py`.

### 9.2 `router.py`
| Original | New under `api_router` |
|---|---|
| `GET  /api/config`                       | `GET  /config` |
| `POST /api/compile`                      | `POST /compile` |
| `POST /api/load`                         | `POST /load` |
| `POST /api/save/{sid}`                   | `POST /save/{sid}` |
| `POST /api/download/pdf/{sid}`           | `POST /download/pdf/{sid}` |
| `POST /api/download/excel/{sid}`         | `POST /download/excel/{sid}` |
| `POST /api/unmapped/add/{sid}`           | `POST /unmapped/add/{sid}` |

Keep request/response shapes identical (including `DownloadOptions` Pydantic model).

### 9.3 Config & data folders
- `apps/assets/config/` — `sources.yaml`, `asset_class_labels.csv`, `mapping_asset_class.csv`, `mapping_broad_asset_class.csv`, `mapping_us_situs.csv`, `currency_lookthrough.csv`, `fx_rates_cache.json`.
- `apps/assets/data/` — `last_compiled.parquet`, `last_compiled_meta.json` (auto-created).
- All file path constants in extracted modules must derive from `Path(__file__).parent`.

### 9.4 Frontend (`page.html` + `assets.js` + `assets.css`)
Reproduce all functionality:
- Dropzone + file list with per-file source picker (from `/api/assets/config.sources`).
- "Load last" button → POST `/api/assets/load`, then render normally.
- Compile → POST `/api/assets/compile` (multipart `files` + JSON-string `assignments`).
- After compile: metrics (Total USD), holdings Tabulator table (columns from response), allocation Plotly charts (one per category in the `allocations` dict).
- "Save" button → POST `/api/assets/save/{sid}` → updates the "Last saved" indicator from response.
- Download buttons (PDF / Excel) wired with `DownloadOptions` form (hide balances toggle, lookthrough toggle).
- Unmapped warning panel + "Auto-add unmapped" button → POST `/api/assets/unmapped/add/{sid}`.
- FX section: render the `fx_display` map; if `fx_error`, show a warning tag.

---

## 10. Sub-app spec — **My Claims** (`apps/claims/`)

### 10.1 Source mapping
Port `mediclaim/app.py` into:
- `db.py` — `_init_db()`, connection helpers, `lifespan` context manager (called from sub-app startup).
- `files.py` — invoice-name safety, path helpers.
- `status.py` — `compute_status(row)`.
- `router.py` — endpoints.

Database file moves to `apps/claims/data/mediclaim.db`. Invoices folder moves to `apps/claims/data/invoices/`. `claimants.json`, `institutions.json` move to `apps/claims/config/`.

### 10.2 Startup hook
Claims is the only sub-app needing DB init. Use FastAPI sub-app `lifespan` via a router-level startup event, or simply call `db.init()` lazily on first request (preferred — fewer moving parts in the combined server).

### 10.3 `router.py`
| Original | New under `api_router` |
|---|---|
| `GET  /api/config`                                  | `GET  /config` |
| `GET  /api/institutions`                            | `GET  /institutions` |
| `POST /api/institutions`                            | `POST /institutions` |
| `GET  /api/claims`                                  | `GET  /claims` |
| `POST /api/claims`                                  | `POST /claims` |
| `PUT  /api/claims/{id}`                             | `PUT  /claims/{id}` |
| `POST /api/claims/{id}/toggle`                      | `POST /claims/{id}/toggle` |
| `DELETE /api/claims/{id}`                           | `DELETE /claims/{id}` |
| `GET  /api/claims/archived`                         | `GET  /claims/archived` |
| `POST /api/claims/{id}/restore`                     | `POST /claims/{id}/restore` |
| `DELETE /api/claims/{id}/permanent`                 | `DELETE /claims/{id}/permanent` |
| `GET  /api/claims/{id}/invoice`                     | `GET  /claims/{id}/invoice` |
| `POST /api/claims/{id}/invoice`                     | `POST /claims/{id}/invoice` |
| `POST /api/claims/{id}/files`                       | `POST /claims/{id}/files` |
| `GET  /api/claims/{id}/files/{fid}`                 | `GET  /claims/{id}/files/{fid}` |
| `DELETE /api/claims/{id}/files/{fid}`               | `DELETE /claims/{id}/files/{fid}` |

Schemas (claims, claim_files tables, status logic, file naming) are unchanged — see source for exact behaviour.

### 10.4 Frontend
Rebuild `static/index.html` as `page.html` under unified design:
- Summary tiles: Total Incurred, Total Rebated, Shortfall (Outstanding).
- Filter bar: date range, claimant select, status select, free-text search.
- Claims table: colour-coded rows by status, inline toggle dots for `invoice_received` / `claimed` / `rebated` / `excluded`, View / Edit / Archive actions, "Other Docs" pop-out.
- New-claim form: claimant select, institution select (with "+ Add new"), amount, currency, date, flags, amount_rebated, notes, invoice file upload.
- Archive view: list + restore + permanent-delete buttons.
- Strict feature parity with the source UI; styling rebuilt against `tokens.css` + `components.css`.

---

## 11. Sub-app spec — **My Loan** (`apps/loan/`) — NEW API + UI

### 11.1 Source mapping
Copy `MortgageMonitor/cli.py`'s simulation core into `apps/loan/simulate.py`:
- `q`, `fmt`, `adjusted_payment_date`, `next_month`
- `simulate_state(as_of: date, loan: Loan) -> dict`

Refactor `simulate_state` to accept a `Loan` dataclass/Pydantic model (instead of reading `loan.json` directly). Loading the JSON moves to `apps/loan/config.py`:

```python
@dataclass(frozen=True)
class Loan:
    origin_date: date
    origin_principal: Decimal
    annual_rate: Decimal
    monthly_payment: Decimal
    original_tenor_months: int
    maturity_date: date
    payment_day_of_month: int
    currency: str

def load_loan() -> Loan: ...
```

### 11.2 `router.py`

| Method | Path (under `/api/loan`) | Purpose | Request / Response |
|---|---|---|---|
| `GET` | `/config` | Return the loan config (so the UI can show terms). | `Loan` as JSON (Decimals serialised as strings). |
| `PUT` | `/config` | Replace `loan.json`. Validates the schema. | Body: `Loan` JSON. Response: stored `Loan`. |
| `GET` | `/state` | Snapshot as of a date. | Query: `as_of=YYYY-MM-DD` (optional, default today). Response: the `state` dict from `simulate_state`, with Decimals as strings and dates as ISO. |
| `GET` | `/schedule` | Full amortisation schedule from origin to payoff. | Query: optional `up_to=YYYY-MM-DD`. Response: `{rows: [{payment_date, amount, interest, principal_paid, closing_principal}], summary: {total_interest, total_paid, payoff_date}}`. |

`schedule` is a thin wrapper over `simulate_state` looped month-by-month; expose it because the UI will show a table.

### 11.3 Frontend
Mirror the **My Claims** summary-tile pattern. `page.html` contains:
- **Tiles**: Outstanding Principal, Accrued Interest, Next Payment (date + amount), Days Since Last Payment.
- **Date picker**: "Snapshot as of [date]" (defaults today) → re-fetches `/api/loan/state`.
- **Loan terms card**: Origin date, Original principal, Rate p.a., Monthly payment, Tenor, Maturity, Currency.
- **Last paid installment card**: collapsible — Date, Payment, Interest portion, Principal portion, Closing principal.
- **"Edit loan" button**: opens a form modal that PUTs to `/api/loan/config`.
- **Schedule table** (Tabulator): full amortisation, with summary footer (total interest, payoff date).
- All money formatted with the loan currency.

### 11.4 Decimal handling
- Server: always use `Decimal`; serialise to string in JSON responses so precision is preserved.
- Client: format with `Intl.NumberFormat` for display; never round before display.

---

## 12. Frontend behaviour conventions

- All XHR via the shared `api.js` wrapper. No raw `fetch` calls.
- Errors surface as a toast in the bottom-right corner (`<div id="toasts">` injected by `shell.js`).
- Each sub-app's JS is wrapped in an IIFE and only attaches event handlers under its own `<main>` root.
- Tabulator and Plotly are loaded from CDN in the per-app `{% block head %}` (only on pages that need them — `claims` and `loan` don't load Plotly).
- All forms submit with `application/x-www-form-urlencoded` or `multipart/form-data` matching what the original endpoints accepted; do **not** silently switch to JSON.
- Date inputs use native `<input type="date">`; values serialised as `YYYY-MM-DD`.

---

## 13. Tests

Keep tests **minimal** — the brief is to combine, not to add coverage. One smoke test per sub-app:

```python
# tests/test_server_boots.py
from fastapi.testclient import TestClient
from abicus.server import app

def test_root_redirects_to_outflows():
    c = TestClient(app, follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/outflows"

def test_each_subapp_serves_html():
    c = TestClient(app)
    for name in ("outflows", "assets", "claims", "loan"):
        r = c.get(f"/{name}")
        assert r.status_code == 200
        assert "<html" in r.text.lower()

def test_each_subapp_config_endpoint():
    c = TestClient(app)
    for name in ("outflows", "assets", "claims", "loan"):
        r = c.get(f"/api/{name}/config")
        assert r.status_code == 200
```

Plus one route-list assertion per sub-app to guarantee no endpoint was lost in the move:

```python
def test_outflows_has_all_legacy_routes():
    paths = {r.path for r in app.routes}
    expected = {
        "/api/outflows/config",
        "/api/outflows/compile",
        "/api/outflows/download/categorised/{session_id}",
        "/api/outflows/download/unmapped/{session_id}",
        "/api/outflows/download/html/{session_id}",
        "/api/outflows/history/append/{session_id}",
    }
    assert expected.issubset(paths)
```

(Replicate for assets, claims, loan.)

No integration tests against real files — the smoke set is the contract.

---

## 14. Build order

Recommended sequence for the implementing session:

0. **Clone the existing GitHub repo** — the user has already set up `https://github.com/snowleopard-spec/abicus`. The current working dir `/Users/wessch/Projects/Tools/abicus/` is not yet wired to it. Either `git init` here and add the remote, or `git clone` the remote into a sibling folder and move `Abicus Spec.md`, `ABICUS_BUILD_SPEC.md`, and `Image.png` into it. Preserve those three files — they're the inputs to this build.
1. **Scaffold** — create the folder tree from §3 with empty `__init__.py` and stub `router.py` files (each exporting an empty `api_router` and `views_router`). Commit on a feature branch (`feat/initial-build`).
2. **Shell** — implement `server.py`, `base.html`, `_sidebar.html`, `tokens.css`, `shell.css`, `components.css`, `api.js`, `shell.js`. Each sub-app's `page.html` extends `base.html` with placeholder content. `python -m abicus` should boot and navigate between the four blank pages with the sidebar working.
3. **Claims** (port first — smallest, no parsers, real DB) — copy `app.py` logic into `router.py`/`db.py`/`status.py`/`files.py`, move `claimants.json`/`institutions.json` to `config/`, build the new UI. Smoke test.
4. **Outflows** — copy modules + parsers, port `app.py` into `router.py`, fix config paths, build UI.
5. **Assets** — same pattern; extract pipeline helpers into `pipeline.py` first.
6. **Loan** — extract simulation into `simulate.py`, build new `router.py` (config CRUD + state + schedule), build new UI.
7. **Smoke tests** — write `tests/` files, run.
8. **README** — install instructions, how to seed `config/` files, how to run.

Each step should leave the server runnable. Don't move to the next sub-app until the current one renders and its smoke test passes.

---

## 15. Acceptance criteria

The build is done when **all** of the following are true:

- [ ] `pip install -r requirements.txt && python -m abicus` starts the server with no errors on `127.0.0.1:8765`.
- [ ] Visiting `/` redirects to `/outflows`.
- [ ] All four pages render with the sidebar highlighting the active page.
- [ ] Sidebar styling visually matches the Cloudflare reference (`Image.png`) — sidebar width, grouped sections, search box, page header layout.
- [ ] **Outflows**: dropzone accepts files, per-file account picker populated from `accounts.yaml`, Compile produces a table + chart, all three downloads return valid files, "Append to history" updates `transaction_history.xlsx`. Warnings (mapping/history/unfamiliar accounts) render.
- [ ] **Assets**: Compile produces holdings + allocation charts, Save persists a parquet, Load restores it across server restarts, PDF and Excel downloads work, unmapped auto-add appends to the CSVs.
- [ ] **Claims**: CRUD on claims works end-to-end (create, edit, toggle flags, archive, restore, hard delete). Invoice upload + view + other-docs management work. Filters and summary tiles update live.
- [ ] **Loan**: `/api/loan/state?as_of=…` returns correct numbers matching `python cli.py --date …` from the original repo. Tiles + date picker work. Editing the loan config persists. Schedule table renders.
- [ ] `pytest` passes all smoke tests.
- [ ] No FastAPI route from any source app is missing — verified by the route-list tests.
- [ ] `requirements.txt` is the only dependency file; no per-sub-app `requirements.txt` left over.
- [ ] Each `apps/<name>/config/` and `apps/<name>/data/` is gitignored (verified by `git check-ignore`).

---

## 16. Notes & gotchas

- **Path-relative file loads**: every existing module that opens `"config/..."` will break when imported into the combined server (CWD is now the project root). Replace string paths with `Path(__file__).parent / "config" / "..."` during the port.
- **In-memory SESSIONS** dicts: keep one per sub-app (don't share). Multiple tabs of the same sub-app will share the same session pool — that already matches existing behaviour.
- **CDN dependency**: Plotly and Tabulator load from CDN. Documented; acceptable for a localhost tool.
- **Streamlit removal** (loan): explicitly drop `dashboard.py` and the `streamlit` dep. The new FastAPI UI replaces it.
- **Currency mismatches**: each sub-app may report in different currencies (Outflows in SGD, Assets in USD, Claims in SGD, Loan in whatever's in `loan.json`). No conversion across apps — render whatever each app produces.
- **No homepage**: don't add a dashboard or aggregation. Sidebar only.
- **Backward compat for users**: existing users' configs and DBs need to be copied into the new `apps/<name>/config/` and `apps/<name>/data/` folders. See §17.

---

## 17. Backfill from existing local installs

All four sub-apps gitignore their user data, so a fresh clone yields empty `config/` and `data/` folders. The user already runs all four locally; copy their real files into the new layout as part of the build.

### 17.1 Known local source paths (on the user's machine)

| Sub-app | Local repo | Items to copy | Destination |
|---|---|---|---|
| outflows | `~/Projects/Tools/spending_review/config/` | `accounts.yaml`, `categories.txt`, `mapping.json`, `mapping.xlsx`, `transaction_history.xlsx` | `apps/outflows/config/` |
| assets   | `~/Projects/Tools/Portfolio-Ag/config/`     | `sources.yaml`, `asset_class_labels.csv`, `mapping_asset_class.csv`, `mapping_broad_asset_class.csv`, `mapping_us_situs.csv`, `currency_lookthrough.csv`, `fx_rates_cache.json` | `apps/assets/config/` |
| assets   | `~/Projects/Tools/Portfolio-Ag/data/`       | `last_compiled.parquet`, `last_compiled_meta.json` (skip `last_portfolio.parquet` — legacy, not used by current code) | `apps/assets/data/` |
| claims   | `~/Projects/Tools/mediclaim/` (repo root)   | `claimants.json`, `institutions.json` | `apps/claims/config/` |
| claims   | `~/Projects/Tools/mediclaim/` (repo root)   | `mediclaim.db` | `apps/claims/data/` |
| claims   | `~/Projects/Tools/mediclaim/invoices/`      | every file in the folder | `apps/claims/data/invoices/` |
| loan     | `~/Projects/Tools/mortgage-tracker/`        | `loan.json` | `apps/loan/config/` |

**MediClaim invoices** — `claims/db.py` stores `invoice_file` and `claim_files.filename` as bare filenames (no leading path), and `files.py` resolves them against the invoices directory at read time. So copying `mediclaim.db` and `invoices/*` is sufficient — no DB path rewriting needed. Verify after copy by hitting `GET /api/claims/claims` and confirming each row's `invoice_file` resolves to a file that exists on disk.

### 17.2 `scripts/migrate_from_legacy.sh`

Commit this script at the repo root. It's the canonical way to backfill.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Source locations (override with env vars if the user's paths differ)
OUTFLOWS_SRC="${OUTFLOWS_SRC:-$HOME/Projects/Tools/spending_review}"
ASSETS_SRC="${ASSETS_SRC:-$HOME/Projects/Tools/Portfolio-Ag}"
CLAIMS_SRC="${CLAIMS_SRC:-$HOME/Projects/Tools/mediclaim}"
LOAN_SRC="${LOAN_SRC:-$HOME/Projects/Tools/mortgage-tracker}"

FORCE="${1:-}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="$ROOT/abicus/apps"

copy_into() {
  # copy_into <src_file_or_dir> <dest_dir>
  local src="$1" dst="$2"
  mkdir -p "$dst"
  if [ -e "$dst/$(basename "$src")" ] && [ "$FORCE" != "--force" ]; then
    echo "  SKIP $dst/$(basename "$src") (exists; rerun with --force to overwrite)"
    return
  fi
  cp -R "$src" "$dst/"
  echo "  COPY $src -> $dst/"
}

echo "Backfilling outflows..."
for f in accounts.yaml categories.txt mapping.json mapping.xlsx transaction_history.xlsx; do
  [ -f "$OUTFLOWS_SRC/config/$f" ] && copy_into "$OUTFLOWS_SRC/config/$f" "$APPS/outflows/config"
done

echo "Backfilling assets config..."
for f in sources.yaml asset_class_labels.csv mapping_asset_class.csv mapping_broad_asset_class.csv mapping_us_situs.csv currency_lookthrough.csv fx_rates_cache.json; do
  [ -f "$ASSETS_SRC/config/$f" ] && copy_into "$ASSETS_SRC/config/$f" "$APPS/assets/config"
done
echo "Backfilling assets data..."
for f in last_compiled.parquet last_compiled_meta.json; do
  [ -f "$ASSETS_SRC/data/$f" ] && copy_into "$ASSETS_SRC/data/$f" "$APPS/assets/data"
done

echo "Backfilling claims..."
for f in claimants.json institutions.json; do
  [ -f "$CLAIMS_SRC/$f" ] && copy_into "$CLAIMS_SRC/$f" "$APPS/claims/config"
done
[ -f "$CLAIMS_SRC/mediclaim.db" ] && copy_into "$CLAIMS_SRC/mediclaim.db" "$APPS/claims/data"
if [ -d "$CLAIMS_SRC/invoices" ]; then
  mkdir -p "$APPS/claims/data/invoices"
  # copy contents, not the folder itself
  for f in "$CLAIMS_SRC/invoices/"*; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    [ "$base" = ".DS_Store" ] && continue
    copy_into "$f" "$APPS/claims/data/invoices"
  done
fi

echo "Backfilling loan..."
[ -f "$LOAN_SRC/loan.json" ] && copy_into "$LOAN_SRC/loan.json" "$APPS/loan/config"

echo "Done."
```

Usage:
```sh
bash scripts/migrate_from_legacy.sh           # safe — skips files that already exist
bash scripts/migrate_from_legacy.sh --force   # overwrite
```

### 17.3 Post-migration verification

Add a check to the smoke tests (or run by hand once after migration):

- `apps/outflows/config/categories.txt` exists and is non-empty.
- `apps/assets/config/sources.yaml` parses and lists ≥1 source.
- `apps/assets/data/last_compiled.parquet` opens with `pd.read_parquet` and has ≥1 row.
- `apps/claims/data/mediclaim.db` opens; `SELECT COUNT(*) FROM claims` returns the expected number; every `invoice_file` value resolves to an existing file under `apps/claims/data/invoices/`.
- `apps/loan/config/loan.json` parses and `simulate_state(date.today(), load_loan())` returns a sensible state dict.

### 17.4 Going forward

Once the new layout is the source of truth, the legacy folders under `~/Projects/Tools/` can be archived. The new app writes everything in-place under `apps/<name>/{config,data}/`, so no further sync is needed.

---

## 18. Resolved decisions (locked in this spec)

These were chosen during spec review. They are settled — don't re-litigate during the build.

| Topic | Decision |
|---|---|
| **GitHub repo** | `https://github.com/snowleopard-spec/abicus` (already created; build session works in this repo). |
| **Discovery strategy** | All four source repos were inspected end-to-end during spec; their internals are captured in §§ 8–11. |
| **UI strategy** | Full rebuild of all four sub-apps against the unified design system in §7 — no preserved-as-is UIs. |
| **Home page** | None. `/` 307-redirects to `/outflows`. No cross-app aggregation. |
| **My Loan UI** | Tile-driven, mirroring My Claims' summary-tile pattern (§11.3). |
| **Branding** | Text-only "Abicus" wordmark in the sidebar. No logo asset. Inline-SVG favicon ("A"). |
| **Header right** | Monospace version chip showing `vX.Y.Z · <git-short-sha>` (degrades to version-only if git not available). No other global header items. |
| **Launch UX** | `python -m abicus` opens `http://127.0.0.1:8765/` in the default browser on boot; `--no-browser` to suppress. `--reload` flag available for dev. |
| **Migration** | Legacy data backfilled via `scripts/migrate_from_legacy.sh` (§17). Idempotent; `--force` to overwrite. |
| **Auth / multi-user** | Out of scope. Localhost, single user. |
| **Cross-app data sharing** | None. Each sub-app keeps its own persistence layer. |
| **Build tooling** | None. Vanilla HTML/CSS/JS, Plotly + Tabulator from CDN, no bundler. |

If the build session encounters something that contradicts any of these, prefer this spec; only deviate after confirming with the user.

---

## 19. Milestones

The build is broken into eight numbered milestones. **At the end of each milestone, the build session must stop, summarise what was done, and wait for the user to verify before continuing.** Each milestone leaves the server in a runnable state and produces something the user can inspect (visually, via a browser, or via a quick command).

For every milestone, the build session should:
1. Commit the work on the feature branch with a message like `M3: claims sub-app ported`.
2. Post a short status: what was built, what was skipped, any deviations from the spec, and a one-line "to verify" instruction for the user.
3. Wait. Do not start the next milestone until the user gives the go-ahead.

---

### M0 — Repo bootstrap
**Goal:** working git checkout, folder tree, branch.

**Done when:**
- `snowleopard-spec/abicus` is cloned (or current dir initialised + remote added) and on a `feat/initial-build` branch.
- `Abicus Spec.md`, `ABICUS_BUILD_SPEC.md`, `Image.png` are preserved at the repo root.
- Empty folder tree from §3 exists with `__init__.py` stubs.
- `requirements.txt`, `.gitignore`, `run.sh`, `pyproject.toml` (minimal) committed.

**User verifies:** `git log --oneline` shows the bootstrap commit; `tree -L 3 abicus/` matches §3.

**Risk to catch:** wrong repo, wrong branch, accidentally clobbered the spec docs.

---

### M1 — Shared shell boots
**Goal:** server runs, sidebar navigates four blank pages.

**Done when:**
- `python -m abicus` starts uvicorn on `127.0.0.1:8765` and opens the browser.
- `/` redirects to `/outflows`.
- All four routes (`/outflows`, `/assets`, `/claims`, `/loan`) return placeholder pages (`<p>Coming soon</p>`) extending `base.html`.
- Sidebar shows the "Abicus" wordmark, search input, four nav links, active link highlighted.
- Version chip appears in the top-right of each page.
- Page styling visually approximates the Cloudflare reference (`Image.png`) — sidebar width, white card backgrounds, type hierarchy.

**User verifies:** open each of the four pages; confirm sidebar + active-state + header look right; resize browser to check layout doesn't break.

**Risk to catch:** layout off, version chip not rendering, browser doesn't auto-open, port conflict.

---

### M2 — Migration script
**Goal:** legacy data lands in the new layout.

**Done when:**
- `scripts/migrate_from_legacy.sh` is implemented exactly per §17.2.
- Running it (no `--force`) copies every file listed in §17.1.
- A spot-check confirms: outflows has its mapping files; assets has its config + parquet; claims has its DB + invoices/* + json lists; loan has loan.json.
- Re-running without `--force` produces "SKIP" lines, not overwrites.

**User verifies:** `ls -la abicus/apps/*/config/ abicus/apps/*/data/` shows the expected files; open `mediclaim.db` with `sqlite3 -header -column abicus/apps/claims/data/mediclaim.db "select count(*) from claims;"` and confirm count matches the legacy install.

**Risk to catch:** wrong source paths, missed files, invoices folder copied as `invoices/invoices/`, permissions errors.

---

### M3 — My Claims ported
**Goal:** first sub-app fully functional end-to-end (chosen first per §14 — smallest, real DB, no parsers).

**Done when:**
- All Claims routes from §10.3 respond correctly.
- The new UI renders: summary tiles, filter bar, colour-coded table with inline toggles, create form, edit modal, archive view.
- CRUD round-trip works: create a test claim, toggle flags, upload an invoice, attach an "other doc", archive, restore, hard-delete.
- Existing migrated data displays correctly: every row's `invoice_file` resolves to a real file on disk.
- Smoke tests for claims pass.

**User verifies:** click through every claim action in the browser; confirm migrated claims look identical to the legacy app; download an invoice; create a new claim with file upload.

**Risk to catch:** DB-init lifecycle wrong, file-path resolution broken after the folder move, status-computation regression, file-naming collisions on re-upload.

---

### M4 — My Outflows ported
**Goal:** statement-categorisation flow fully functional.

**Done when:**
- All Outflows routes from §8.2 respond correctly.
- Dropzone accepts files, per-file account picker is populated from `accounts.yaml`.
- Compile produces a Tabulator table + Plotly chart matching the legacy behaviour.
- All three downloads (categorised xlsx, unmapped xlsx, HTML snapshot) return valid files.
- "Append to history" writes to `transaction_history.xlsx` and shows the n_added/n_skipped toast.
- Warning surfaces (mapping/history/unfamiliar-account) render.
- Smoke tests pass.

**User verifies:** drop in a real statement file, compile, check category assignments match expectations, download each output, append a row to history.

**Risk to catch:** parser registry broken by the folder move, mapping.xlsx → mapping.json rebuild not triggered, Plotly/Tabulator not loading from CDN, multipart form field name mismatch.

---

### M5 — My Assets ported
**Goal:** portfolio aggregation fully functional.

**Done when:**
- All Assets routes from §9.2 respond correctly.
- Compile produces holdings + per-category allocation charts.
- "Load last" restores the saved parquet across a fresh server boot.
- Save writes a new parquet and updates the timestamp.
- PDF and Excel downloads work.
- "Auto-add unmapped" appends correctly to the mapping CSVs.
- FX section renders (or shows a warning tag if `fx_error`).
- Smoke tests pass.

**User verifies:** compile a real broker file, confirm totals match the legacy app's output, save + reload, download PDF and Excel, intentionally add an unmapped instrument to confirm the warning + auto-add flow.

**Risk to catch:** FX cache path broken, yfinance optional dep missing, parquet schema drift, currency-lookthrough off-by-one, reportlab PDF generation regression.

---

### M6 — My Loan built (greenfield)
**Goal:** brand-new FastAPI + UI for the mortgage tool.

**Done when:**
- `simulate_state` extracted into `apps/loan/simulate.py` and exercised by both routes and tests.
- All four routes from §11.2 respond correctly.
- The UI shows tiles (Outstanding Principal, Accrued Interest, Next Payment date+amount, Days Since Last Payment), date picker, loan-terms card, collapsible last-installment card, edit-loan modal, full schedule table with summary footer.
- All money formatted with the loan currency.
- `GET /api/loan/state?as_of=…` returns numbers that match `python cli.py --date …` from the legacy repo for at least 3 spot-check dates (today, mid-loan, post-payoff).
- Editing loan config via PUT persists and the UI refreshes.
- Smoke tests pass.

**User verifies:** compare three snapshot dates against the legacy CLI output and confirm exact Decimal match; edit a loan field and confirm it persists across a server restart.

**Risk to catch:** Decimal precision lost via JSON, weekend-payment-day adjustment regression, schedule generation slow on long tenors, edit form not validating dates.

---

### M7 — Smoke tests, README, polish
**Goal:** ship-ready.

**Done when:**
- All smoke tests from §13 pass under `pytest`.
- Route-list assertions confirm zero endpoints lost from any source app.
- README documents: install (`pip install -r requirements.txt`), migration (`bash scripts/migrate_from_legacy.sh`), run (`python -m abicus`), and per-sub-app config-folder layout.
- `git check-ignore apps/outflows/config/categories.txt` returns success (proving the gitignore is correct).
- Final commit on `feat/initial-build`; branch pushed; PR opened against `main` if the user wants one (don't open without asking).
- Every checkbox in §15 (Acceptance criteria) is ticked, with evidence.

**User verifies:** fresh clone smoke test — wipe `.venv`, reinstall, run the migration, boot, click through each sub-app. PR opened only on explicit user confirmation.

**Risk to catch:** missing dep, README assumes paths that don't exist, route accidentally renamed, PR opened prematurely.

---

### Pacing guidance

These milestones are **stopping points, not size targets.** M1 and M3 each touch a lot of files; M2 is small. The build session should not rush a milestone to "fit" the list — it's fine to take a long session on M5 and a tiny one on M2.

If an unexpected blocker appears mid-milestone (e.g. a source repo's parser depends on a package missing from `requirements.txt`), the session should pause **at the blocker**, not at the next clean milestone boundary — surface the issue immediately rather than carrying broken work forward.
