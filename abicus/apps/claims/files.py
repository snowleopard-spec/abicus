import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INVOICE_DIR = BASE_DIR / "data" / "invoices"


def ensure_invoice_dir() -> Path:
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    return INVOICE_DIR


def _safe_token(s: str, max_len: int = 40) -> str:
    s = (s or "").replace(" ", "")
    s = re.sub(r"[^A-Za-z0-9_-]", "", s)
    return s[:max_len] or "x"


def _safe_ext(filename: str) -> str:
    _, ext = os.path.splitext(filename or "")
    if not ext:
        return ""
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)
    if not ext.startswith("."):
        ext = "." + ext
    return ext.lower()


def _safe_name(filename: str, max_len: int = 120) -> str:
    base = os.path.basename(filename or "")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base[:max_len] or "file"


def _avoid_collision(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.exists():
        return target
    stem, ext = os.path.splitext(filename)
    i = 2
    while True:
        candidate = directory / f"{stem}_{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def invoice_filename(claimant: str, institution: str, date_incurred: str, original_filename: str) -> str:
    """Build a sanitised invoice filename of the form YYYYMMDD_Claimant_Institution.ext."""
    yyyymmdd = (date_incurred or "").replace("-", "")[:8] or "00000000"
    parts = f"{yyyymmdd}_{_safe_token(claimant)}_{_safe_token(institution)}"
    ext = _safe_ext(original_filename)
    return parts + ext


def store_invoice(claimant: str, institution: str, date_incurred: str, original_filename: str, file_obj) -> str:
    """Persist the uploaded invoice. Returns the bare on-disk filename."""
    directory = ensure_invoice_dir()
    name = invoice_filename(claimant, institution, date_incurred, original_filename)
    target = _avoid_collision(directory, name)
    with target.open("wb") as out:
        import shutil

        shutil.copyfileobj(file_obj, out)
    return target.name


def store_other_doc(claim_id: int, original_filename: str, file_obj) -> str:
    """Persist an attached 'other doc'. Returns the bare on-disk filename."""
    directory = ensure_invoice_dir()
    name = f"{claim_id}_other_{_safe_name(original_filename)}"
    target = _avoid_collision(directory, name)
    with target.open("wb") as out:
        import shutil

        shutil.copyfileobj(file_obj, out)
    return target.name


def resolve(filename: str) -> Path | None:
    """Return a path for the bare filename if it exists, else None."""
    if not filename:
        return None
    p = INVOICE_DIR / filename
    return p if p.exists() else None


def delete_if_exists(filename: str) -> bool:
    p = resolve(filename)
    if p is None:
        return False
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
