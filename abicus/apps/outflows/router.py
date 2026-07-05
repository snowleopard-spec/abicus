from __future__ import annotations

import io
import os
import platform
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from abicus.apps.outflows import db
from abicus.apps.outflows.accounts import load_accounts
from abicus.apps.outflows.build_mapping import (
    build_mapping_if_changed,
    load_mapping_table,
    save_mapping_table,
)
from abicus.apps.outflows.categories import load_categories
from abicus.apps.outflows.categorise import UNCATEGORISED, categorise_dataframe, load_mapping
from abicus.apps.outflows.html_export import build_html
from abicus.apps.outflows.transaction_history import (
    DEFAULT_PATH as HISTORY_PATH,
    append_to_history,
    load_history_mapping,
    load_history_table,
    save_history_table,
)
from abicus.apps.outflows.parsers.format_a import parse as parse_format_a
from abicus.apps.outflows.parsers.format_b import parse as parse_format_b
from abicus.apps.outflows.parsers.format_c import parse as parse_format_c
from abicus.apps.outflows.parsers.format_d import parse as parse_format_d
from abicus.apps.outflows.parsers.format_e import parse as parse_format_e
from abicus.apps.outflows.parsers.format_f import parse as parse_format_f
from abicus.templating import templates

MAPPING_PATH = Path(__file__).parent / "config" / "mapping.json"

PARSERS = {
    "Format A": parse_format_a,
    "Format B": parse_format_b,
    "Format C": parse_format_c,
    "Format D": parse_format_d,
    "Format E": parse_format_e,
    "Format F": parse_format_f,
}

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
        "accounts": [{"name": name, "format": fmt} for name, fmt in accounts.items()],
        "categories": sorted(all_cats),
        "excluded": sorted(excluded),
    }


@api_router.post("/compile")
async def api_compile(
    files: list[UploadFile] = File(...),
    accounts: list[str] = Form(...),
):
    if len(files) != len(accounts):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(files)} account selections, got {len(accounts)}.",
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
    for upload, chosen_account in zip(files, accounts):
        if chosen_account not in account_map:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown account '{chosen_account}' for file '{upload.filename}'.",
            )
        format_name = account_map[chosen_account]
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
            parsed["account"] = parsed["account"].fillna(chosen_account)
            unfamiliar_accounts |= (
                set(parsed["account"].unique()) - set(account_map.keys())
            )
        else:
            parsed["account"] = chosen_account
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

    before = len(df)
    df = df[df["amount"] > 0].reset_index(drop=True)
    dropped_negatives = before - len(df)

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
    # has overridden via the ⟲ buttons — hidden by default, but committed.
    unsuppressed_dup_idx: list[int] = []
    reincluded_excl_idx: list[int] = []


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
) -> pd.DataFrame:
    """Rebuild the exact set of rows the user sees in the Categorised
    Transactions table, honouring their per-row ⟲ overrides. Row indices in
    the override sets refer to positions in the raw compile DataFrame (which
    is what `_df_to_records` iterates), not into any filtered view."""
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

    hidden_dup = df_ranged["duplicate"] & ~df_ranged.index.isin(unsup)
    hidden_excl = (
        df_ranged["category"].isin(excluded) & ~df_ranged.index.isin(reinc)
        if excluded else pd.Series(False, index=df_ranged.index)
    )
    return df_ranged[~hidden_dup & ~hidden_excl].reset_index(drop=True)


def _scoped_views(state: dict, start_date: date, end_date: date) -> dict:
    df: pd.DataFrame = state["df"]
    mask = (df["date"] >= pd.Timestamp(start_date)) & (
        df["date"] <= pd.Timestamp(end_date)
    )
    df_dated = df[mask].reset_index(drop=True)
    df_full = df_dated[~df_dated["duplicate"]].reset_index(drop=True)

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


@api_router.post("/db/commit/{session_id}")
def api_db_commit(session_id: str, body: CommitBody):
    """Upsert the currently-visible Categorised Transactions rows into
    transactions.db. Honours client-side ⟲ overrides so what the user sees
    is what gets committed."""
    state = _get_session(session_id)
    view = _commit_view(
        state, body.start_date, body.end_date,
        body.unsuppressed_dup_idx, body.reincluded_excl_idx,
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
    by lifetime total descending for tile ordering."""
    return db.load_monthly_breakdown()
