import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from abicus.apps.claims.status import compute_status

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
DB_PATH = DATA_DIR / "mediclaim.db"
CLAIMANTS_PATH = CONFIG_DIR / "claimants.json"
INSTITUTIONS_PATH = CONFIG_DIR / "institutions.json"

DEFAULT_CLAIMANTS = ["Self", "Spouse"]


_init_done = False


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "invoices").mkdir(parents=True, exist_ok=True)


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS claims (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            claimant        TEXT    NOT NULL,
            institution     TEXT    NOT NULL,
            amount          REAL    NOT NULL DEFAULT 0,
            currency        TEXT    NOT NULL DEFAULT 'SGD',
            date_incurred   TEXT    NOT NULL,
            invoice_received INTEGER NOT NULL DEFAULT 0,
            claimed         INTEGER NOT NULL DEFAULT 0,
            rebated         INTEGER NOT NULL DEFAULT 0,
            amount_rebated  REAL    NOT NULL DEFAULT 0,
            invoice_file    TEXT,
            notes           TEXT    NOT NULL DEFAULT '',
            archived        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
        """
    )
    cols = {r["name"] for r in con.execute("PRAGMA table_info(claims)")}
    if "excluded" not in cols:
        con.execute("ALTER TABLE claims ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS claim_files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id      INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
            kind          TEXT    NOT NULL DEFAULT 'other',
            filename      TEXT    NOT NULL,
            original_name TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_claim_files_claim ON claim_files(claim_id)")


def _seed_files_if_missing(con: sqlite3.Connection) -> None:
    if not CLAIMANTS_PATH.exists():
        CLAIMANTS_PATH.write_text(json.dumps(DEFAULT_CLAIMANTS, indent=2))
    if not INSTITUTIONS_PATH.exists():
        rows = con.execute("SELECT DISTINCT institution FROM claims WHERE institution != ''").fetchall()
        institutions = sorted({r["institution"] for r in rows})
        INSTITUTIONS_PATH.write_text(json.dumps(institutions, indent=2))


def init() -> None:
    """Idempotent. Safe to call from any request handler."""
    global _init_done
    if _init_done:
        return
    _ensure_dirs()
    with connect() as con:
        _init_schema(con)
        _seed_files_if_missing(con)
    _init_done = True


# ---------- JSON-backed config ----------

def load_claimants() -> list[str]:
    init()
    try:
        data = json.loads(CLAIMANTS_PATH.read_text())
        return [str(x) for x in data] if isinstance(data, list) else list(DEFAULT_CLAIMANTS)
    except (FileNotFoundError, json.JSONDecodeError):
        return list(DEFAULT_CLAIMANTS)


def load_institutions() -> list[str]:
    init()
    try:
        data = json.loads(INSTITUTIONS_PATH.read_text())
        if isinstance(data, list):
            return sorted({str(x) for x in data if x})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def save_institutions(names: Iterable[str]) -> list[str]:
    init()
    sorted_names = sorted({n.strip() for n in names if n and n.strip()})
    INSTITUTIONS_PATH.write_text(json.dumps(sorted_names, indent=2))
    return sorted_names


def add_institution(name: str) -> list[str]:
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    current = set(load_institutions())
    current.add(name)
    return save_institutions(current)


# ---------- Claim row helpers ----------

def _claim_files(con: sqlite3.Connection, claim_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT id, filename, original_name, created_at FROM claim_files WHERE claim_id = ? ORDER BY id",
        (claim_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _row_to_dict(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["status"] = compute_status(d)
    rebated_amount = float(d.get("amount_rebated") or 0)
    amount = float(d.get("amount") or 0)
    if bool(d.get("excluded")):
        d["outstanding"] = 0.0
    elif bool(d.get("rebated")):
        d["outstanding"] = max(amount - rebated_amount, 0.0)
    else:
        d["outstanding"] = amount
    d["other_files"] = _claim_files(con, d["id"])
    return d


def list_claims(archived: bool = False) -> list[dict]:
    init()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM claims WHERE archived = ? ORDER BY date_incurred DESC, id DESC",
            (1 if archived else 0,),
        ).fetchall()
        return [_row_to_dict(con, r) for r in rows]


def get_claim(claim_id: int) -> dict | None:
    init()
    with connect() as con:
        row = con.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return _row_to_dict(con, row) if row else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_claim(data: dict) -> dict:
    init()
    now = _now()
    with connect() as con:
        cur = con.execute(
            """
            INSERT INTO claims (
                claimant, institution, amount, currency, date_incurred,
                invoice_received, claimed, rebated, excluded,
                amount_rebated, invoice_file, notes,
                archived, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                data["claimant"], data["institution"], float(data["amount"]),
                data.get("currency") or "SGD", data["date_incurred"],
                int(bool(data.get("invoice_received"))),
                int(bool(data.get("claimed"))),
                int(bool(data.get("rebated"))),
                int(bool(data.get("excluded"))),
                float(data.get("amount_rebated") or 0),
                data.get("invoice_file"),
                data.get("notes") or "",
                now, now,
            ),
        )
        new_id = cur.lastrowid
        row = con.execute("SELECT * FROM claims WHERE id = ?", (new_id,)).fetchone()
        if data["institution"] not in load_institutions():
            try:
                add_institution(data["institution"])
            except ValueError:
                pass
        return _row_to_dict(con, row)


def update_claim(claim_id: int, data: dict) -> dict | None:
    init()
    with connect() as con:
        existing = con.execute("SELECT id FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if existing is None:
            return None
        con.execute(
            """
            UPDATE claims SET
                claimant = ?, institution = ?, amount = ?, currency = ?, date_incurred = ?,
                invoice_received = ?, claimed = ?, rebated = ?, excluded = ?,
                amount_rebated = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["claimant"], data["institution"], float(data["amount"]),
                data.get("currency") or "SGD", data["date_incurred"],
                int(bool(data.get("invoice_received"))),
                int(bool(data.get("claimed"))),
                int(bool(data.get("rebated"))),
                int(bool(data.get("excluded"))),
                float(data.get("amount_rebated") or 0),
                data.get("notes") or "",
                _now(),
                claim_id,
            ),
        )
        row = con.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return _row_to_dict(con, row)


def set_invoice_file(claim_id: int, filename: str) -> None:
    init()
    with connect() as con:
        con.execute(
            "UPDATE claims SET invoice_file = ?, updated_at = ? WHERE id = ?",
            (filename, _now(), claim_id),
        )


def toggle_flag(claim_id: int, field: str) -> dict | None:
    if field not in {"invoice_received", "claimed", "rebated", "excluded"}:
        raise ValueError(f"unknown field: {field}")
    init()
    with connect() as con:
        row = con.execute(f"SELECT {field} FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if row is None:
            return None
        new_val = 0 if row[field] else 1
        con.execute(
            f"UPDATE claims SET {field} = ?, updated_at = ? WHERE id = ?",
            (new_val, _now(), claim_id),
        )
        full = con.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return _row_to_dict(con, full)


def archive_claim(claim_id: int) -> bool:
    init()
    with connect() as con:
        res = con.execute(
            "UPDATE claims SET archived = 1, updated_at = ? WHERE id = ?",
            (_now(), claim_id),
        )
        return res.rowcount > 0


def restore_claim(claim_id: int) -> bool:
    init()
    with connect() as con:
        res = con.execute(
            "UPDATE claims SET archived = 0, updated_at = ? WHERE id = ?",
            (_now(), claim_id),
        )
        return res.rowcount > 0


def delete_claim_permanent(claim_id: int) -> tuple[bool, list[str]]:
    """Return (deleted, list_of_orphan_filenames_to_unlink)."""
    init()
    with connect() as con:
        row = con.execute("SELECT invoice_file FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if row is None:
            return False, []
        files = con.execute(
            "SELECT filename FROM claim_files WHERE claim_id = ?", (claim_id,)
        ).fetchall()
        to_unlink = [f["filename"] for f in files]
        if row["invoice_file"]:
            to_unlink.append(row["invoice_file"])
        con.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
        return True, to_unlink


# ---------- claim_files (other docs) ----------

def list_files(claim_id: int) -> list[dict]:
    init()
    with connect() as con:
        return _claim_files(con, claim_id)


def add_file(claim_id: int, filename: str, original_name: str) -> dict:
    init()
    with connect() as con:
        cur = con.execute(
            "INSERT INTO claim_files (claim_id, kind, filename, original_name, created_at) "
            "VALUES (?, 'other', ?, ?, ?)",
            (claim_id, filename, original_name, _now()),
        )
        fid = cur.lastrowid
        return {"id": fid, "filename": filename, "original_name": original_name}


def delete_file(claim_id: int, file_id: int) -> str | None:
    """Return the on-disk filename so the caller can unlink it, or None if not found."""
    init()
    with connect() as con:
        row = con.execute(
            "SELECT filename FROM claim_files WHERE id = ? AND claim_id = ?",
            (file_id, claim_id),
        ).fetchone()
        if row is None:
            return None
        con.execute("DELETE FROM claim_files WHERE id = ?", (file_id,))
        return row["filename"]


def get_file(claim_id: int, file_id: int) -> dict | None:
    init()
    with connect() as con:
        row = con.execute(
            "SELECT id, filename, original_name FROM claim_files WHERE id = ? AND claim_id = ?",
            (file_id, claim_id),
        ).fetchone()
        return dict(row) if row else None
