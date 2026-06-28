#!/usr/bin/env bash
set -euo pipefail

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
