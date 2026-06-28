#!/usr/bin/env bash
set -e
[ -d .venv ] && source .venv/bin/activate
exec python -m abicus "$@"
