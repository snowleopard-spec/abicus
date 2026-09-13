from __future__ import annotations

import io
import json
import os
import platform
import re
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from abicus.apps.outflows import db, db_history, guess_embed, pdf_export
from abicus.apps.outflows.accounts import load_accounts
from abicus.apps.outflows.build_mapping import (
    build_mapping_if_changed,
    load_mapping_table,
    save_mapping_table,
)
from abicus.apps.outflows.categories import load_categories, load_category_types
from abicus.apps.outflows.guess import best_guess, build_corpus, load_guess_config
from abicus.apps.outflows.categorise import (
    UNCATEGORISED,
    categorise_dataframe,
    load_mapping,
    normalise_text,
)
from abicus.apps.outflows.breakdown_html_export import build_breakdown_html
from abicus.apps.outflows.html_export import build_html
from abicus.apps.outflows.transaction_history import (
    DEFAULT_PATH as HISTORY_PATH,
    append_to_history,
    load_history_mapping,
    load_history_table,
    save_history_table,
    upsert_history_category,
)
from abicus.apps.outflows.parsers.format_a import parse as parse_format_a
from abicus.apps.outflows.parsers.format_b import parse as parse_format_b
from abicus.apps.outflows.parsers.format_c import parse as parse_format_c
from abicus.apps.outflows.parsers.format_d import parse as parse_format_d
from abicus.apps.outflows.parsers.format_e import parse as parse_format_e
from abicus.apps.outflows.parsers.format_f import parse as parse_format_f
from abicus.templating import templates

MAPPING_PATH = Path(__file__).parent / "config" / "mapping.json"
# Saved app states. Lives under data/, which is gitignored — state files
# contain full transaction data and must never reach git.
STATES_DIR = Path(__file__).parent / "data" / "states"
STATE_VERSION = 1

PARSERS = {
    "Format A": parse_format_a,
    "Format B": parse_format_b,
    "Format C": parse_format_c,
    "Format D": parse_format_d,
    "Format E": parse_format_e,
    "Format F": parse_format_f,
}

# Format A's dynamic header scan (date/description/amount anywhere in the
# first 30 rows) also matches Format F's row-0 manual-template header, so an
# F file always try-parses as both. F is the stricter fingerprint — prefer
# it. Any candidate pair not listed here stays ambiguous.
DETECT_PRECEDENCE = {frozenset({"Format A", "Format F"}): "Format F"}

SESSIONS: dict[str, dict] = {}

api_router = APIRouter()
views_router = APIRouter()


@views_router.get("")
@views_router.get("/")
def page(request: Request):
    return templates.TemplateResponse(
        request,
        "outflows/page.html",
        {"active": "outflows"},
    )


@views_router.get("/mapping")
def mapping_page(request: Request):
    return templates.TemplateResponse(
        request,
        "outflows/mapping.html",
        {"active": "outflows"},
    )


@views_router.get("/history")
def history_page(request: Request):
    return templates.TemplateResponse(
        request,
        "outflows/history.html",
        {"active": "outflows"},
    )


@views_router.get("/breakdown")
def breakdown_page(request: Request):
    return templates.TemplateResponse(
        request,
        "outflows/breakdown.html",
        {"active": "outflows"},
    )


@views_router.get("/dbedit")
def dbedit_page(request: Request):
    return templates.TemplateResponse(
        request,
        "outflows/dbedit.html",
        {
            "active": "outflows",
            "backup_dir": str((db.DB_PATH.parent / "backups").resolve()),
        },
    )


class MappingRule(BaseModel):
    partial_string: str
    category: str


class MappingPut(BaseModel):
    rules: list[MappingRule]


@api_router.get("/mapping")
def api_get_mapping():
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = set()
    return {
        "rules": load_mapping_table(),
        "categories": sorted(valid_cats),
    }


@api_router.put("/mapping")
def api_put_mapping(body: MappingPut):
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"categories.txt: {e}")
    rules = [{"partial_string": r.partial_string, "category": r.category} for r in body.rules]
    try:
        n, warnings = save_mapping_table(rules, valid_cats)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "n_rules": n, "warnings": warnings}


class HistoryRow(BaseModel):
    date: str = ""
    description: str = ""
    amount: float | None = None
    category: str = ""


class HistoryPut(BaseModel):
    rows: list[HistoryRow]


@api_router.get("/history")
def api_get_history():
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = set()
    return {
        "rows": load_history_table(),
        "categories": sorted(valid_cats),
    }


@api_router.put("/history")
def api_put_history(body: HistoryPut):
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"categories.txt: {e}")
    payload = [r.model_dump() for r in body.rows]
    try:
        n, warnings = save_history_table(payload, valid_cats)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "n_rows": n, "warnings": warnings}


@api_router.get("/config")
def api_config():
    try:
        accounts = load_accounts(valid_formats=set(PARSERS.keys()))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"accounts.yaml: {e}")

    try:
        all_cats, excluded = load_categories()
    except (FileNotFoundError, ValueError):
        all_cats, excluded = set(), set()

    return {
        "accounts": [
            {"name": name, "format": info["format"], "labels": info["labels"]}
            for name, info in accounts.items()
        ],
        "categories": sorted(all_cats),
        "excluded": sorted(excluded),
    }


@api_router.post("/detect")
async def api_detect(file: UploadFile = File(...)):
    """Auto-detect a statement's format by try-parsing it against every
    registered parser — the parsers themselves are the format fingerprints.
    Returns the account to pre-select when detection is unambiguous:

        format:     the single format that parsed, else null
        account:    the single accounts.yaml account for that format, else null
        candidates: every format that parsed (empty = not recognised)
    """
    file_bytes = await file.read()

    candidates = []
    for format_name, parser in PARSERS.items():
        try:
            parser(file_bytes, file.filename)
        except Exception:
            # Any failure — wrong headers, unreadable bytes, empty file —
            # just means "not this format" for detection purposes.
            continue
        candidates.append(format_name)

    detected = (
        candidates[0] if len(candidates) == 1
        else DETECT_PRECEDENCE.get(frozenset(candidates))
    )

    account = None
    if detected is not None:
        try:
            account_map = load_accounts(valid_formats=set(PARSERS.keys()))
        except (FileNotFoundError, ValueError):
            account_map = {}
        matches = [
            name for name, info in account_map.items()
            if info["format"] == detected
        ]
        # Only auto-pick when the format maps to exactly one account.
        if len(matches) == 1:
            account = matches[0]

    return {"format": detected, "account": account, "candidates": candidates}


@api_router.post("/compile")
async def api_compile(
    files: list[UploadFile] = File(...),
    accounts: list[str] = Form(...),
    labels: list[str] = Form(...),
):
    if len(files) != len(accounts) or len(files) != len(labels):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected {len(files)} account and label selections, "
                f"got {len(accounts)} accounts / {len(labels)} labels."
            ),
        )

    try:
        account_map = load_accounts(valid_formats=set(PARSERS.keys()))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"accounts.yaml: {e}")

    try:
        rebuilt, n_rules, mapping_warnings = build_mapping_if_changed()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Mapping build failed: {e}")

    frames = []
    unfamiliar_accounts: set[str] = set()
    # Account-column values a file may legitimately carry: any label of any
    # account (account names themselves are dropdown groupings, not labels).
    known_labels = {
        lbl for info in account_map.values() for lbl in info["labels"]
    }
    for upload, chosen_account, label in zip(files, accounts, labels):
        entry = account_map.get(chosen_account)
        if entry is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown account '{chosen_account}' for file '{upload.filename}'.",
            )
        # The label must be in the account's permissible set — by default
        # just the account name itself (legacy behaviour), widened by an
        # optional 'labels' list on the accounts.yaml entry.
        if label not in entry["labels"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Label '{label}' is not an allowed label for account "
                    f"'{chosen_account}' (file '{upload.filename}'). "
                    f"Allowed: {entry['labels']}."
                ),
            )
        format_name = entry["format"]
        parser = PARSERS[format_name]
        try:
            file_bytes = await upload.read()
            parsed = parser(file_bytes, upload.filename)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Failed to parse '{upload.filename}' as "
                    f"{chosen_account} ({format_name}): {e}"
                ),
            )

        if "account" in parsed.columns:
            parsed["account"] = parsed["account"].fillna(label)
            unfamiliar_accounts |= (
                set(parsed["account"].unique()) - known_labels
            )
        else:
            parsed["account"] = label
        frames.append(parsed)

    df = pd.concat(frames, ignore_index=True)

    if "pre_categorised" not in df.columns:
        df["pre_categorised"] = False
    else:
        df["pre_categorised"] = df["pre_categorised"].fillna(False).astype(bool)

    df["duplicate"] = df.duplicated(
        subset=["date", "amount", "description"], keep="first"
    )
    duplicates_count = int(df["duplicate"].sum())

    # Refunds/credits (amount <= 0) are kept but flagged: hidden from the
    # dashboard, listed in the Refunds panel, re-includable per row like
    # excluded transactions. dropped_negatives keeps its name for the
    # metric tile ("Refunds dropped").
    df["refund"] = df["amount"] <= 0
    dropped_negatives = int(df["refund"].sum())
    df = df.reset_index(drop=True)

    try:
        mapping = load_mapping(MAPPING_PATH)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = None

    try:
        history, history_warnings = load_history_mapping(
            HISTORY_PATH, valid_categories=valid_cats
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Transaction history: {e}")

    df = categorise_dataframe(df, mapping, history)

    df["date"] = pd.to_datetime(df["date"])

    session_id = uuid.uuid4().hex
    payload = {
        "session_id": session_id,
        "rows": _df_to_records(df),
        "mapping_status": {"rebuilt": rebuilt, "n_rules": n_rules},
        "mapping_warnings": mapping_warnings,
        "history_warnings": history_warnings,
        "dropped_negatives": dropped_negatives,
        "duplicates_count": duplicates_count,
        "unfamiliar_accounts": sorted(unfamiliar_accounts),
    }
    SESSIONS[session_id] = {
        "df": df,
        "dropped_negatives": dropped_negatives,
        "duplicates_count": duplicates_count,
        "mapping_warnings": mapping_warnings,
        "history_warnings": history_warnings,
        "payload": payload,
    }
    return payload


@api_router.get("/session/{session_id}")
def api_get_session(session_id: str):
    """Return the cached compile payload so the client can re-hydrate the
    dashboard after navigating to Edit mapping / Edit history and back.
    Returns 404 if the session is gone (server restart / never existed)."""
    state = SESSIONS.get(session_id)
    if state is None or "payload" not in state:
        raise HTTPException(
            status_code=404,
            detail="Session not found (server may have restarted).",
        )
    return state["payload"]


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    out = df.copy()
    if pd.api.types.is_datetime64_any_dtype(out["date"]):
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    else:
        out["date"] = out["date"].astype(str)
    out = out.where(pd.notnull(out), None)
    return out.to_dict(orient="records")


class DateRangeBody(BaseModel):
    start_date: date
    end_date: date


class CommitBody(BaseModel):
    start_date: date
    end_date: date
    # Row indices (into the compile response's rows array) that the client
    # has overridden via the ⟲/+ buttons — hidden by default, but committed.
    unsuppressed_dup_idx: list[int] = []
    reincluded_excl_idx: list[int] = []
    reincluded_refund_idx: list[int] = []
    # Rows the user excluded by hand via the × button — visible by default,
    # but hidden and therefore not committed.
    excluded_row_idx: list[int] = []


def _get_session(session_id: str) -> dict:
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown or expired session. Re-Compile to continue.",
        )
    return state


def _commit_view(
    state: dict,
    start_date: date,
    end_date: date,
    unsuppressed_dup_idx: list[int],
    reincluded_excl_idx: list[int],
    excluded_row_idx: list[int] | None = None,
    reincluded_refund_idx: list[int] | None = None,
) -> pd.DataFrame:
    """Rebuild the exact set of rows the user sees in the Categorised
    Transactions table, honouring their per-row ⟲/× overrides. Row indices
    in the override sets refer to positions in the raw compile DataFrame
    (which is what `_df_to_records` iterates), not into any filtered view."""
    df: pd.DataFrame = state["df"]
    mask_range = (df["date"] >= pd.Timestamp(start_date)) & (
        df["date"] <= pd.Timestamp(end_date)
    )
    df_ranged = df[mask_range]

    try:
        _, excluded = load_categories()
    except (FileNotFoundError, ValueError):
        excluded = set()

    unsup = set(unsuppressed_dup_idx)
    reinc = set(reincluded_excl_idx)
    manual = set(excluded_row_idx or [])
    reinc_ref = set(reincluded_refund_idx or [])

    hidden_dup = df_ranged["duplicate"] & ~df_ranged.index.isin(unsup)
    hidden_excl = (
        df_ranged["category"].isin(excluded) & ~df_ranged.index.isin(reinc)
        if excluded else pd.Series(False, index=df_ranged.index)
    )
    hidden_manual = df_ranged.index.isin(manual)
    hidden_refund = _refund_col(df_ranged) & ~df_ranged.index.isin(reinc_ref)
    return df_ranged[
        ~hidden_dup & ~hidden_excl & ~hidden_manual & ~hidden_refund
    ].reset_index(drop=True)


def _refund_col(df: pd.DataFrame) -> pd.Series:
    """Refund flag column; absent on pre-refund-feature sessions/fixtures."""
    if "refund" in df.columns:
        return df["refund"].fillna(False).astype(bool)
    return pd.Series(False, index=df.index)


def _scoped_views(state: dict, start_date: date, end_date: date) -> dict:
    df: pd.DataFrame = state["df"]
    mask = (df["date"] >= pd.Timestamp(start_date)) & (
        df["date"] <= pd.Timestamp(end_date)
    )
    df_dated = df[mask].reset_index(drop=True)
    df_full = df_dated[
        ~df_dated["duplicate"] & ~_refund_col(df_dated)
    ].reset_index(drop=True)

    try:
        _, excluded = load_categories()
    except (FileNotFoundError, ValueError):
        excluded = set()

    df_view = (
        df_full[~df_full["category"].isin(excluded)].reset_index(drop=True)
        if excluded
        else df_full
    )

    return {"df_dated": df_dated, "df_full": df_full, "df": df_view}


def _to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def _xlsx_response(df: pd.DataFrame, filename: str) -> Response:
    return Response(
        content=_to_excel_bytes(df),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


CATEGORISED_COLS = [
    "date", "description", "amount", "category", "account",
    "matched_pattern", "source_file",
]
UNMAPPED_COLS = ["date", "description", "amount", "account"]


@api_router.post("/download/categorised/{session_id}")
def api_download_categorised(session_id: str, body: DateRangeBody):
    state = _get_session(session_id)
    views = _scoped_views(state, body.start_date, body.end_date)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return _xlsx_response(
        views["df"][CATEGORISED_COLS],
        f"spending_categorised_{timestamp}.xlsx",
    )


@api_router.post("/download/unmapped/{session_id}")
def api_download_unmapped(session_id: str, body: DateRangeBody):
    state = _get_session(session_id)
    views = _scoped_views(state, body.start_date, body.end_date)
    unmapped = views["df_full"][views["df_full"]["category"] == UNCATEGORISED][
        UNMAPPED_COLS
    ].reset_index(drop=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return _xlsx_response(unmapped, f"spending_unmapped_{timestamp}.xlsx")


@api_router.post("/download/html/{session_id}")
def api_download_html(session_id: str, body: DateRangeBody):
    state = _get_session(session_id)
    views = _scoped_views(state, body.start_date, body.end_date)
    html = build_html(views["df"], body.start_date, body.end_date)
    filename = (
        f"spending_snapshot_"
        f"{body.start_date.isoformat()}_{body.end_date.isoformat()}.html"
    )
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/history/open")
def api_history_open():
    """Ask the OS to open transaction_history.xlsx in its default handler
    (Excel/Numbers). Safe because abicus runs locally as a desktop tool."""
    if not HISTORY_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{HISTORY_PATH.name} does not exist yet.",
        )
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(HISTORY_PATH)])
        elif system == "Windows":
            os.startfile(str(HISTORY_PATH))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(HISTORY_PATH)])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open file: {e}")
    return {"opened": str(HISTORY_PATH)}


@api_router.post("/history/append/{session_id}")
def api_history_append(session_id: str, body: DateRangeBody):
    state = _get_session(session_id)
    views = _scoped_views(state, body.start_date, body.end_date)
    unmapped = views["df_full"][views["df_full"]["category"] == UNCATEGORISED][
        UNMAPPED_COLS
    ].reset_index(drop=True)

    if unmapped.empty:
        return {"n_added": 0, "n_skipped": 0}

    try:
        n_added, n_skipped = append_to_history(unmapped, HISTORY_PATH)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"n_added": n_added, "n_skipped": n_skipped}


class MappingAddRuleBody(BaseModel):
    substring: str
    category: str


@api_router.post("/mapping/add-rule/{session_id}")
def api_mapping_add_rule(session_id: str, body: MappingAddRuleBody):
    """Highlight-to-map flow: add (or re-point) a substring rule in the
    mapping table — written to both mapping.xlsx and mapping.json via
    save_mapping_table — then recategorise every unmapped session row whose
    description contains the substring, so the rule takes effect
    immediately."""
    state = _get_session(session_id)

    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"categories.txt: {e}")

    category = body.category.strip()
    if category not in valid_cats:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category}' is not in categories.txt.",
        )

    substring = body.substring.strip()
    sub_lower = normalise_text(substring)
    if len(sub_lower) < 2:
        raise HTTPException(
            status_code=400,
            detail="Highlighted string is too short to use as a rule.",
        )

    rules = load_mapping_table()
    outcome = "added"
    for rule in rules:
        if str(rule["partial_string"]).strip().lower() == sub_lower:
            if rule["category"].strip() == category:
                outcome = "unchanged"
            else:
                rule["category"] = category
                outcome = "updated"
            break
    else:
        rules.append({"partial_string": substring, "category": category})

    try:
        _, warnings = save_mapping_table(rules, valid_cats)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # save_mapping_table re-reports warnings for the whole table; only the
    # ones touching the new rule are worth surfacing here.
    warnings = [w for w in warnings if sub_lower in w.lower()]

    # Immediate effect on the live session, scoped to unmapped rows (rows
    # already matched by another rule keep their category until the next
    # Compile applies full longest-match semantics).
    df: pd.DataFrame = state["df"]
    mask = (df["category"] == UNCATEGORISED) & (
        df["description"].astype(str).map(normalise_text)
        .str.contains(sub_lower, regex=False)
    )
    df.loc[mask, "category"] = category
    df.loc[mask, "matched_pattern"] = sub_lower
    state["payload"]["rows"] = _df_to_records(df)

    return {
        "status": outcome,
        "substring": sub_lower,
        "category": category,
        "updated_idx": [int(i) for i in df.index[mask]],
        "warnings": warnings,
    }


@api_router.post("/guess/{session_id}")
def api_guess(session_id: str):
    """Best-guess categories for the session's unmapped rows, from BOTH
    engines against one shared corpus (transactions.db +
    transaction_history.xlsx pairs):

      rapidfuzz    guess.py's free-deletion distance — matches by spelling
      transformer  guess_embed.py's bge-small cosine NN — matches by
                   meaning; None per-row below threshold, and skipped
                   entirely (with an install hint) when the optional
                   `.[suggest]` ML stack isn't installed (R7)

    Returns {"guesses": {row_idx: {"rapidfuzz": g|null, "transformer":
    g|null}}, "transformer": {"available": bool, "hint": str|null}} —
    rows where neither engine clears its threshold are simply absent."""
    state = _get_session(session_id)

    try:
        cfg = load_guess_config()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"guess.yaml: {e}")

    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = None

    try:
        history_map, _ = load_history_mapping(HISTORY_PATH, valid_categories=valid_cats)
    except ValueError:
        history_map = {}

    t_available = guess_embed.available()
    t_hint = None if t_available else guess_embed.INSTALL_HINT

    corpus = build_corpus(
        db.load_description_categories(),
        [(desc, cat) for desc, cat in history_map.items()],
        valid_categories=valid_cats,
    )
    if not corpus:
        return {
            "guesses": {},
            "transformer": {"available": t_available, "hint": t_hint},
        }

    df: pd.DataFrame = state["df"]
    unmapped = df[(df["category"] == UNCATEGORISED) & ~_refund_col(df)]
    idxs = [int(i) for i in unmapped.index]
    descs = [str(d) for d in unmapped["description"]]

    rf_cache: dict[str, dict | None] = {}  # per distinct description
    rf_results = []
    for desc in descs:
        if desc not in rf_cache:
            rf_cache[desc] = best_guess(desc, corpus, cfg)
        rf_results.append(rf_cache[desc])

    t_results: list[dict | None] = [None] * len(descs)
    if t_available and descs:
        try:
            t_results = guess_embed.batch_guess(descs, corpus, cfg)
        except Exception as e:
            # Meaning-matching is best-effort: a model download failure or
            # broken install must not take the rapidfuzz pills down with it.
            t_available = False
            t_hint = f"Transformer engine failed: {e}"

    guesses: dict[int, dict] = {}
    for idx, rf, t in zip(idxs, rf_results, t_results):
        if rf is not None or t is not None:
            guesses[idx] = {"rapidfuzz": rf, "transformer": t}
    return {
        "guesses": guesses,
        "transformer": {"available": t_available, "hint": t_hint},
    }


class HistoryCategoriseBody(BaseModel):
    row_idx: int
    category: str


@api_router.post("/history/categorise/{session_id}")
def api_history_categorise(session_id: str, body: HistoryCategoriseBody):
    """Assign a category to a single unmapped row: upsert it into
    transaction_history.xlsx as an exact-match rule, then recategorise every
    matching unmapped row in the live session so the change takes effect
    immediately (no re-upload needed)."""
    state = _get_session(session_id)

    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"categories.txt: {e}")

    category = body.category.strip()
    if category not in valid_cats:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category}' is not in categories.txt.",
        )

    df: pd.DataFrame = state["df"]
    if body.row_idx < 0 or body.row_idx >= len(df):
        raise HTTPException(status_code=400, detail="Invalid row index.")

    row = df.iloc[body.row_idx]
    if row["category"] != UNCATEGORISED:
        raise HTTPException(
            status_code=400,
            detail="Row is no longer unmapped — re-Compile to refresh.",
        )

    description = str(row["description"]).strip()
    try:
        outcome = upsert_history_category(
            row["date"].strftime("%Y-%m-%d"),
            description,
            float(row["amount"]),
            category,
            HISTORY_PATH,
        )
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Apply to the live session the same way the history layer would at
    # compile time: exact description match (case-insensitive), category
    # set, matched_pattern = the description itself.
    mask = (
        df["description"].astype(str).map(normalise_text)
        == normalise_text(description)
    ) & (df["category"] == UNCATEGORISED)
    df.loc[mask, "category"] = category
    df.loc[mask, "matched_pattern"] = description
    state["payload"]["rows"] = _df_to_records(df)

    return {
        "status": outcome,
        "category": category,
        "updated_idx": [int(i) for i in df.index[mask]],
    }


# ---- Saved states ----
# A state file is one JSON document: the compiled session payload (rows and
# all — every panel is derived from it) plus the client's UI/override state
# and provenance. Loading rebuilds a server session from the rows.


class UiState(BaseModel):
    dateRange: dict = {}
    tableFilter: dict = {}
    unsuppressedDup: list[int] = []
    reincludedExcl: list[int] = []
    manualExcl: list[int] = []
    reincludedRef: list[int] = []


class StateSaveBody(BaseModel):
    label: str = ""
    ui: UiState = UiState()


def _app_version() -> str:
    try:
        from importlib.metadata import version
        return version("abicus")
    except Exception:
        return "unknown"


def _state_path(filename: str) -> Path:
    """Resolve a state filename safely inside STATES_DIR (no traversal)."""
    name = Path(filename).name
    if name != filename or not re.fullmatch(r"[A-Za-z0-9._ -]+\.json", name):
        raise HTTPException(status_code=400, detail=f"Invalid state file name '{filename}'.")
    return STATES_DIR / name


@api_router.post("/state/save/{session_id}")
def api_state_save(session_id: str, body: StateSaveBody):
    state = _get_session(session_id)
    label = body.label.strip() or datetime.now().strftime("state %Y-%m-%d %H:%M")
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "_", label).strip("_ ") or "state"
    path = STATES_DIR / f"{slug}.json"

    doc = {
        "state_version": STATE_VERSION,
        "meta": {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": _app_version(),
            "label": label,
            "n_rows": len(state["df"]),
            "source_files": sorted(
                state["df"]["source_file"].astype(str).unique().tolist()
            ) if "source_file" in state["df"].columns else [],
        },
        "session": {k: v for k, v in state["payload"].items() if k != "session_id"},
        "ui": body.ui.model_dump(),
    }
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False))
    return {"file": path.name, "label": label, "n_rows": doc["meta"]["n_rows"]}


@api_router.get("/state/list")
def api_state_list():
    if not STATES_DIR.exists():
        return {"states": []}
    states = []
    for p in sorted(STATES_DIR.glob("*.json")):
        try:
            doc = json.loads(p.read_text())
            meta = doc.get("meta", {})
            states.append({
                "file": p.name,
                "label": meta.get("label", p.stem),
                "saved_at": meta.get("saved_at", ""),
                "n_rows": meta.get("n_rows"),
            })
        except (OSError, ValueError):
            continue  # unreadable file — skip rather than break the picker
    states.sort(key=lambda s: s["saved_at"], reverse=True)
    return {"states": states}


class StateFileBody(BaseModel):
    file: str


@api_router.post("/state/load")
def api_state_load(body: StateFileBody):
    path = _state_path(body.file)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"State '{body.file}' not found.")
    try:
        doc = json.loads(path.read_text())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Corrupt state file: {e}")
    if doc.get("state_version") != STATE_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported state_version {doc.get('state_version')!r}.",
        )

    payload = doc.get("session") or {}
    rows = payload.get("rows") or []
    if not rows:
        raise HTTPException(status_code=400, detail="State file contains no rows.")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ("duplicate", "refund", "pre_categorised"):
        df[col] = df[col].fillna(False).astype(bool) if col in df.columns else False
    df["amount"] = df["amount"].astype(float)

    session_id = uuid.uuid4().hex
    payload["session_id"] = session_id
    SESSIONS[session_id] = {"df": df, "payload": payload}
    return {"session": payload, "ui": doc.get("ui", {}), "meta": doc.get("meta", {})}


@api_router.post("/state/delete")
def api_state_delete(body: StateFileBody):
    path = _state_path(body.file)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"State '{body.file}' not found.")
    path.unlink()
    return {"deleted": body.file}


@api_router.post("/session/recategorise/{session_id}")
def api_session_recategorise(session_id: str):
    """Re-run categorisation on a session's rows against the CURRENT
    mapping and history — used after loading a frozen state to bring it up
    to date with rules added since it was saved."""
    state = _get_session(session_id)
    try:
        rebuilt, n_rules, mapping_warnings = build_mapping_if_changed()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Mapping build failed: {e}")
    try:
        mapping = load_mapping(MAPPING_PATH)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = None
    try:
        history, history_warnings = load_history_mapping(
            HISTORY_PATH, valid_categories=valid_cats
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Transaction history: {e}")

    df = categorise_dataframe(state["df"], mapping, history)
    state["df"] = df
    payload = state["payload"]
    payload["rows"] = _df_to_records(df)
    payload["mapping_status"] = {"rebuilt": rebuilt, "n_rules": n_rules}
    payload["mapping_warnings"] = mapping_warnings
    payload["history_warnings"] = history_warnings
    return payload


@api_router.post("/db/commit/{session_id}")
def api_db_commit(session_id: str, body: CommitBody):
    """Upsert the currently-visible Categorised Transactions rows into
    transactions.db. Honours client-side ⟲ overrides so what the user sees
    is what gets committed."""
    state = _get_session(session_id)
    view = _commit_view(
        state, body.start_date, body.end_date,
        body.unsuppressed_dup_idx, body.reincluded_excl_idx,
        body.excluded_row_idx, body.reincluded_refund_idx,
    )
    if view.empty:
        return {"inserted": 0, "updated": 0, "total_in_db": db.upsert([])["total_in_db"]}

    rows = view[CATEGORISED_COLS].copy()
    rows["date"] = pd.to_datetime(rows["date"]).dt.strftime("%Y-%m-%d")
    payload = rows.where(pd.notnull(rows), None).to_dict(orient="records")
    return db.upsert(payload)


@api_router.get("/breakdown")
def api_breakdown():
    """Return per-category, per-month spending totals from the DB, sorted
    by lifetime total descending for tile ordering, plus the
    category→type map (F/D/V/E/NA) for tile shading and type filters."""
    return {**db.load_monthly_breakdown(), "category_types": load_category_types()}


@api_router.get("/breakdown/html")
def api_breakdown_html():
    """Fully self-contained HTML export of the breakdown page — every
    month's data, vendored Plotly/Tabulator, zero network requests."""
    content = build_breakdown_html()
    filename = f"monthly_breakdown_{date.today().isoformat()}.html"
    return Response(
        content=content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/breakdown/transactions")
def api_breakdown_transactions(month: str, category: str | None = None):
    """The transactions behind one bar on the breakdown page: one month,
    optionally one category (Monthly-total bars pass no category)."""
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(
            status_code=400, detail=f"Bad month '{month}' — expected YYYY-MM."
        )
    return {"rows": db.load_breakdown_transactions(month, category)}


@api_router.post("/db/clear")
def api_db_clear():
    """Wipe every row from transactions.db. Destructive — the frontend
    guards this with a confirm() dialog."""
    return db.clear()


# ---- DB Edit ----
# Direct row-level editing of transactions.db. Writes are immediate; the
# delete flow returns the deleted row so the client can offer an undo that
# restores it verbatim (same tx_hash, same committed_at).


class DbUpdateCategoryBody(BaseModel):
    tx_hash: str
    category: str


class DbHashBody(BaseModel):
    tx_hash: str


class DbRestoreBody(BaseModel):
    row: dict


@api_router.get("/db/rows")
def api_db_rows():
    """All DB rows plus the valid category list for the edit dropdown."""
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError):
        valid_cats = set()
    return {"rows": db.list_rows(), "categories": sorted(valid_cats)}


@api_router.post("/db/update-category")
def api_db_update_category(body: DbUpdateCategoryBody):
    try:
        valid_cats, _ = load_categories()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"categories.txt: {e}")

    category = body.category.strip()
    if category not in valid_cats:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category}' is not in categories.txt.",
        )
    if not db.update_category(body.tx_hash, category):
        raise HTTPException(
            status_code=404,
            detail="Row not found in the database — reload the page.",
        )
    return {"ok": True, "category": category}


@api_router.post("/db/delete-row")
def api_db_delete_row(body: DbHashBody):
    row = db.delete_row(body.tx_hash)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Row not found in the database — reload the page.",
        )
    return {"deleted": row}


@api_router.post("/db/restore-row")
def api_db_restore_row(body: DbRestoreBody):
    """Undo a delete: re-insert the row exactly as delete-row returned it."""
    missing = [
        c for c in ("tx_hash", "date", "description", "amount",
                    "category", "account", "committed_at")
        if body.row.get(c) in (None, "")
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Restore payload is missing fields: {missing}.",
        )
    db.restore_row(body.row)
    return {"ok": True}


@api_router.post("/db/backup")
def api_db_backup():
    """Snapshot transactions.db into data/backups/ — a plain .db file,
    independent of the git history layer."""
    return db.backup()


# ---- DB history (V3 Feature A) ----
# The git-backed commit history behind every DB write. List/diff/restore
# are thin wrappers over db_history — the same operations as the
# scripts/outflows_history.py CLI. Lives under /db/history because the
# bare /history/* namespace belongs to the transaction-history tab.


class DbHistoryRestoreBody(BaseModel):
    ref: str


def _history_ref_errors(fn, *args):
    """Map db_history errors to HTTP: bad ref syntax → 400, unknown
    commit → 404, git unavailable → 500."""
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except subprocess.CalledProcessError:
        raise HTTPException(status_code=404, detail="Unknown commit — reload the page.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="git is not available on PATH.")


@api_router.get("/db/history")
def api_db_history():
    """Commit log, newest first, each with a rows added/changed/removed
    summary for the History panel."""
    commits = db_history.log()
    for c in commits:
        c["summary"] = _history_ref_errors(db_history.diff_counts, c["sha"])
        c["rows"] = _history_ref_errors(db_history.row_count, c["sha"])
    return {"commits": commits}


@api_router.get("/db/history/diff/{ref}")
def api_db_history_diff(ref: str):
    """What one commit changed, as readable rows (added/removed/changed)."""
    return _history_ref_errors(db_history.diff, ref)


@api_router.post("/db/history/restore")
def api_db_history_restore(body: DbHistoryRestoreBody):
    """Roll the DB back to a commit's state. The current state is
    snapshotted first and the rollback lands as a `restore → <sha8>`
    commit, so history stays linear and every rollback is reversible.
    The frontend guards this with a confirm dialog."""
    return _history_ref_errors(db_history.restore, body.ref)


class BreakdownPdfBody(BaseModel):
    selected_months: list[str] = []


@api_router.post("/breakdown/pdf")
def api_breakdown_pdf(body: BreakdownPdfBody):
    """Render the Monthly Breakdown as a PDF using the same month selection
    the user has on-screen. Client sends the currently-checked months so the
    report matches the view."""
    data = db.load_monthly_breakdown(
        selected_months=body.selected_months or None,
    )
    pdf_bytes = pdf_export.render(data)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="monthly_breakdown_{stamp}.pdf"',
        },
    )
