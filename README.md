# Abicus

Local-only personal-finance dashboard. Combines four sub-apps (My Outflows, My Assets, My Claims, My Loan) under one FastAPI server.

Full build spec: [`SPEC.md`](SPEC.md).

## Install

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Backfill legacy data (first run)

```sh
bash scripts/migrate_from_legacy.sh
```

## Run

```sh
python -m abicus
```

Opens `http://127.0.0.1:8765/` in the default browser. Pass `--no-browser` to suppress.
