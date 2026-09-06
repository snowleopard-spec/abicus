"""Git-backed commit history for transactions.db (V3 Feature A).

After every write to the transactions table, the table is dumped as
deterministic SQL text and committed into a nested, local-only git repo
(default: a `history/` folder next to the DB file). Each write becomes a
labelled commit, `git log` is the audit trail, and any prior state can be
restored — a rollback is itself a new commit, so history stays linear.

Hard rules (spec §2):
- The history repo has NO remote, ever. Nothing here may push or fetch.
- A broken history layer must never block or corrupt the write it was
  recording: `checkpoint` swallows every failure with a loud warning.
- stdlib + git only. No daemon; each checkpoint is a subprocess that exits.

Everything is parameterised on (db_path, history_dir) with outflows
defaults, so extending history to another DB later is a two-line change.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import subprocess
from pathlib import Path

logger = logging.getLogger("abicus.outflows.db_history")

DUMP_NAME = "transactions.sql"

_REF_RE = re.compile(r"[0-9a-fA-F]{4,40}")


def _default_paths(
    db_path: Path | None, history_dir: Path | None
) -> tuple[Path, Path]:
    """Resolve defaults at call time so a monkeypatched db.DB_PATH is
    honoured; history lives beside the DB it records."""
    if db_path is None:
        from . import db as _db  # deferred: db.py imports this module

        db_path = _db.DB_PATH
    if history_dir is None:
        history_dir = Path(db_path).parent / "history"
    return Path(db_path), Path(history_dir)


def _git(history_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run one git command against the history repo, output captured.
    Raises CalledProcessError on non-zero exit, FileNotFoundError if git
    itself is missing — callers decide whether that's loud or fatal."""
    return subprocess.run(
        ["git", "-C", str(history_dir), *args],
        capture_output=True, text=True, check=True,
    )


def _sql_quote(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _dump_sql(db_path: Path) -> str:
    """The transactions table as deterministic text: rows ordered by
    tx_hash, stable column order, one INSERT per line — identical DB
    states produce byte-identical dumps and `git diff` reads row-per-line."""
    from .db import ROW_COLS

    lines = [f"-- abicus outflows history dump ({', '.join(ROW_COLS)})"]
    if Path(db_path).exists():
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                f"SELECT {', '.join(ROW_COLS)} FROM transactions"
                " ORDER BY tx_hash"
            ).fetchall()
        except sqlite3.OperationalError:  # no transactions table yet
            rows = []
        finally:
            conn.close()
        for r in rows:
            values = ", ".join(_sql_quote(v) for v in r)
            lines.append(f"INSERT INTO transactions VALUES({values});")
    return "\n".join(lines) + "\n"


def _ensure_repo(history_dir: Path) -> None:
    """First call initialises: mkdir, git init, identity local to the repo,
    an empty initial commit. Idempotent. No remote is ever configured."""
    if (history_dir / ".git").exists():
        return
    history_dir.mkdir(parents=True, exist_ok=True)
    _git(history_dir, "init", "--quiet")
    _git(history_dir, "config", "user.name", "abicus")
    _git(history_dir, "config", "user.email", "abicus@localhost")
    _git(history_dir, "config", "commit.gpgsign", "false")
    _git(history_dir, "commit", "--allow-empty", "--quiet", "-m", "init")


def ensure_baseline(
    db_path: Path | None = None,
    history_dir: Path | None = None,
) -> bool:
    """Called BEFORE a write. If the history repo doesn't exist yet but the
    DB already has rows, record that pre-write state as a baseline commit —
    otherwise the first operation's commit would diff against nothing and
    claim the whole existing table as its own change. No-op (one cheap
    .git existence check) once the repo exists. Never raises (R5)."""
    db_path, history_dir = _default_paths(db_path, history_dir)
    if (history_dir / ".git").exists() or not Path(db_path).exists():
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        except sqlite3.OperationalError:  # no transactions table yet
            n = 0
        finally:
            conn.close()
        if not n:
            return False  # nothing pre-existing to protect
        return checkpoint(
            f"baseline: {n} existing rows recorded", db_path, history_dir
        )
    except (OSError, sqlite3.Error) as e:
        logger.warning(
            "DB HISTORY BASELINE FAILED: %s — continuing without baseline", e
        )
        return False


def checkpoint(
    label: str,
    db_path: Path | None = None,
    history_dir: Path | None = None,
) -> bool:
    """Dump the current table state and commit it under `label`.

    Returns True if a commit landed, False otherwise (no-op write, or the
    history layer failed). Never raises: the caller's DB write has already
    succeeded and must stand even if git is missing or broken (R5).
    """
    db_path, history_dir = _default_paths(db_path, history_dir)
    try:
        _ensure_repo(history_dir)
        (history_dir / DUMP_NAME).write_text(_dump_sql(db_path))
        _git(history_dir, "add", DUMP_NAME)
        staged = subprocess.run(
            ["git", "-C", str(history_dir), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if staged.returncode == 0:
            return False  # identical state — commit nothing
        _git(history_dir, "commit", "--quiet", "-m", label)
        return True
    except FileNotFoundError:
        logger.warning(
            "DB HISTORY CHECKPOINT FAILED (%r): git not found on PATH — "
            "the write succeeded but was NOT recorded in %s", label, history_dir,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        logger.warning(
            "DB HISTORY CHECKPOINT FAILED (%r): %s — the write succeeded "
            "but was NOT recorded in %s", label, detail.strip(), history_dir,
        )
    return False


def _check_ref(ref: str) -> str:
    """Only plain (abbreviated) commit shas are accepted — never git
    syntax like HEAD^ or flags — so refs are safe to pass to subprocess."""
    if not _REF_RE.fullmatch(ref):
        raise ValueError(f"Bad ref {ref!r} — expected a commit sha.")
    return ref


def log(
    history_dir: Path | None = None, db_path: Path | None = None
) -> list[dict]:
    """Commit log, newest first: [{sha, sha8, date, label}, ...].
    The synthetic `init` commit is excluded. Empty if no repo yet."""
    _, history_dir = _default_paths(db_path, history_dir)
    if not (history_dir / ".git").exists():
        return []
    out = _git(
        history_dir, "log", "--format=%H%x1f%h%x1f%cI%x1f%s"
    ).stdout
    entries = []
    for line in out.splitlines():
        sha, sha8, date, label = line.split("\x1f", 3)
        if label == "init":
            continue
        entries.append({"sha": sha, "sha8": sha8, "date": date, "label": label})
    return entries


def show(
    ref: str,
    history_dir: Path | None = None,
    db_path: Path | None = None,
) -> str:
    """The dump text as of commit `ref`."""
    _, history_dir = _default_paths(db_path, history_dir)
    return _git(history_dir, "show", f"{_check_ref(ref)}:{DUMP_NAME}").stdout


def _rows_at(ref_dump: str) -> dict[str, dict]:
    """Rebuild a dump in memory and index its rows by tx_hash."""
    from .db import ROW_COLS, SCHEMA

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        conn.executescript(ref_dump)
        rows = conn.execute(
            f"SELECT {', '.join(ROW_COLS)} FROM transactions"
        ).fetchall()
    finally:
        conn.close()
    return {r["tx_hash"]: dict(r) for r in rows}


def diff(
    ref: str,
    history_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    """What commit `ref` changed vs its parent, as readable rows:
    {"added": [row...], "removed": [row...],
     "changed": [{"before": row, "after": row}...]}."""
    _, history_dir = _default_paths(db_path, history_dir)
    ref = _check_ref(ref)
    after = _rows_at(show(ref, history_dir))
    parent = subprocess.run(
        ["git", "-C", str(history_dir), "rev-parse", "--verify",
         "--quiet", f"{ref}^"],
        capture_output=True, text=True,
    )
    before: dict[str, dict] = {}
    if parent.returncode == 0 and parent.stdout.strip():
        try:
            before = _rows_at(show(parent.stdout.strip(), history_dir))
        except subprocess.CalledProcessError:
            pass  # parent is the empty `init` commit — no dump yet
    return {
        "added": [after[h] for h in after if h not in before],
        "removed": [before[h] for h in before if h not in after],
        "changed": [
            {"before": before[h], "after": after[h]}
            for h in after
            if h in before and after[h] != before[h]
        ],
    }


_INS_RE = re.compile(r"^([+-])INSERT INTO transactions VALUES\('([0-9a-f]{64})'")


def diff_counts(
    ref: str,
    history_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    """Cheap change summary for the History panel's commit list — counts
    rows added/removed/changed from the row-per-line text diff, one git
    call, no DB rebuild (diff() rebuilds both states and is per-commit)."""
    _, history_dir = _default_paths(db_path, history_dir)
    out = _git(
        history_dir, "show", "--format=", "--unified=0", "--no-color",
        _check_ref(ref), "--", DUMP_NAME,
    ).stdout
    plus: set[str] = set()
    minus: set[str] = set()
    for line in out.splitlines():
        m = _INS_RE.match(line)
        if m:
            (plus if m.group(1) == "+" else minus).add(m.group(2))
    return {
        "added": len(plus - minus),
        "removed": len(minus - plus),
        "changed": len(plus & minus),
    }


def row_count(
    ref: str,
    history_dir: Path | None = None,
    db_path: Path | None = None,
) -> int:
    """Total rows in the DB as of commit `ref` — counted with `git grep`
    over the dump blob so the full dump text never leaves git."""
    _, history_dir = _default_paths(db_path, history_dir)
    p = subprocess.run(
        ["git", "-C", str(history_dir), "grep", "-c",
         "^INSERT INTO transactions", _check_ref(ref), "--", DUMP_NAME],
        capture_output=True, text=True,
    )
    if p.returncode == 0:  # "sha:transactions.sql:1496"
        return int(p.stdout.strip().rsplit(":", 1)[1])
    return 0  # no matches (empty table) or no dump in this commit


def restore(
    ref: str,
    db_path: Path | None = None,
    history_dir: Path | None = None,
) -> dict:
    """Rebuild transactions.db from commit `ref`'s dump and swap it in.

    The current state is checkpointed first (`pre-restore snapshot`), so a
    restore is itself always reversible; the restored state then commits as
    `restore → <sha8>` — history stays linear, never `git reset`.

    Unlike checkpoint(), this raises on failure: restore is an explicit
    user action and a half-done one must be loud.
    """
    db_path, history_dir = _default_paths(db_path, history_dir)
    ref = _check_ref(ref)
    from .db import SCHEMA

    dump = show(ref, history_dir)  # resolve the ref before touching anything
    sha8 = _git(history_dir, "rev-parse", "--short", ref).stdout.strip()

    checkpoint("pre-restore snapshot", db_path, history_dir)

    tmp = Path(db_path).with_name(Path(db_path).name + ".restore-tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        conn.executescript(dump)
        n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, db_path)

    checkpoint(f"restore → {sha8}", db_path, history_dir)
    return {"restored_to": sha8, "rows": int(n)}
