import json
import uuid
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from abicus.apps.assets import pipeline
from abicus.apps.assets.fx_rates import fetch_fx_rates
from abicus.templating import templates

api_router = APIRouter()
views_router = APIRouter()

SESSIONS: dict[str, dict] = {}


# ---------- views ----------

@views_router.get("")
@views_router.get("/")
def page(request: Request):
    return templates.TemplateResponse(
        request,
        "assets/page.html",
        {"active": "assets"},
    )


# ---------- request models ----------

class DownloadOptions(BaseModel):
    hide_balances: bool = False
    lookthrough: bool = False


# ---------- helpers ----------

def _session_or_404(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if session is None or session.get("master") is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


def _fx_state() -> tuple[dict, bool]:
    rates = fetch_fx_rates() or {}
    fx_error = not rates or len(rates) <= 1
    return rates, fx_error


# ---------- endpoints ----------

@api_router.get("/config")
def api_config() -> dict:
    config = pipeline.load_config()
    rates, fx_error = _fx_state()

    sources = []
    for name, cfg in config["sources_config"]["sources"].items():
        sources.append({"name": name, "parser": cfg.get("parser")})

    lookthrough_warnings = []
    lt = config["currency_lookthrough"]
    if not lt.empty:
        wc = lt.groupby("Asset Name")["Weight"].sum()
        for asset, tw in wc[~wc.between(0.999, 1.001)].items():
            lookthrough_warnings.append(
                f"Lookthrough weights for '{asset}' sum to {tw:.3f} (expected 1.000)."
            )

    fx_display = {}
    if rates and not fx_error:
        for ccy in ["GBP", "EUR", "SGD", "AUD", "HKD", "JPY"]:
            if ccy in rates:
                fx_display[ccy] = 1 / rates[ccy]

    return {
        "sources": sources,
        "fx_rates": rates,
        "fx_display": fx_display,
        "fx_error": fx_error,
        "asset_class_labels": config["asset_class_labels"]["Label"].tolist(),
        "lookthrough_available": not config["currency_lookthrough"].empty,
        "lookthrough_warnings": lookthrough_warnings,
        "saved": pipeline.saved_meta(),
    }


@api_router.post("/compile")
async def api_compile(
    files: list[UploadFile] = File(...),
    assignments: str = Form(...),
) -> dict:
    try:
        parsed_assignments = json.loads(assignments)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid assignments JSON: {e}")

    by_name = {a["filename"]: a["source"] for a in parsed_assignments}
    config = pipeline.load_config()
    rates, fx_error = _fx_state()

    file_buffers = []
    for upload in files:
        src_name = by_name.get(upload.filename)
        if src_name is None:
            raise HTTPException(
                status_code=400,
                detail=f"No source assignment for '{upload.filename}'.",
            )
        buf = await pipeline.upload_to_bytesio(upload)
        file_buffers.append((upload.filename, buf, src_name))

    result = pipeline.compile_master(file_buffers, config, rates, fx_error)
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {
        "master": result["master"],
        "compile_log": result["compile_log"],
        "compile_errors": result["compile_errors"],
        "price_errors": result["price_errors"],
        "yfinance_error": result["yfinance_error"],
        "fetched_prices": result["fetched_prices"],
        "fx_rates": rates,
    }
    return pipeline.build_session_response(session_id, SESSIONS[session_id], config, fx_error)


@api_router.post("/load")
def api_load() -> dict:
    df, saved_rates, saved_prices = pipeline.load_compiled()
    if df is None:
        raise HTTPException(status_code=404, detail="No saved compilation found.")
    config = pipeline.load_config()
    rates, fx_error = _fx_state()
    session_id = uuid.uuid4().hex
    meta = pipeline.saved_meta()
    SESSIONS[session_id] = {
        "master": df,
        "compile_log": [f"Loaded from saved file ({len(df)} items, saved {meta.get('timestamp')})"],
        "compile_errors": [],
        "price_errors": [],
        "yfinance_error": False,
        "fetched_prices": saved_prices or {},
        "fx_rates": saved_rates or rates or {},
    }
    return pipeline.build_session_response(session_id, SESSIONS[session_id], config, fx_error)


@api_router.post("/save/{session_id}")
def api_save(session_id: str) -> dict:
    session = _session_or_404(session_id)
    df = session["master"]
    pipeline.save_compiled(df, session.get("fx_rates", {}), session.get("fetched_prices", {}))
    return {"ok": True, "count": len(df), "saved": pipeline.saved_meta()}


@api_router.post("/download/pdf/{session_id}")
def api_download_pdf(session_id: str, opts: DownloadOptions) -> Response:
    session = _session_or_404(session_id)
    master = session["master"]
    config = pipeline.load_config()
    master_ccy = (
        pipeline.apply_currency_lookthrough(master, config["currency_lookthrough"])
        if opts.lookthrough else master
    )
    cash_only = master[master["Asset Class"] == "Cash"] if "Asset Class" in master.columns else master.iloc[0:0]
    chart_configs = [
        ("Broad Asset Class", pipeline.get_chart_data(master, "Broad Asset Class")),
        ("Asset Class", pipeline.get_chart_data(master, "Asset Class")),
        ("Currency", pipeline.get_chart_data(master_ccy, "Currency")),
        ("Jurisdiction", pipeline.get_chart_data(master, "Jurisdiction")),
        ("Institution", pipeline.get_chart_data(master, "Institution")),
        ("Account Type", pipeline.get_chart_data(master, "Account Type")),
        ("US Situs", pipeline.get_chart_data(master, "US Situs Flag")),
        ("Cash by Institution", pipeline.get_chart_data(cash_only, "Institution")),
    ]
    ref_rates = session.get("fx_rates") or {}
    pdf_bytes = pipeline.generate_pdf(
        chart_configs, ref_rates, session.get("fetched_prices", {}), opts.hide_balances,
    )
    filename = f"asset_allocation_{date.today().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/download/excel/{session_id}")
def api_download_excel(session_id: str, opts: DownloadOptions | None = None) -> Response:
    session = _session_or_404(session_id)
    master = session["master"]
    cols = [c for c in pipeline.DISPLAY_COLS if c in master.columns]
    xlsx = pipeline.generate_excel(master, cols)
    filename = f"portfolio_holdings_{date.today().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.post("/unmapped/add/{session_id}")
def api_unmapped_add(session_id: str) -> dict:
    session = _session_or_404(session_id)
    return pipeline.append_unmapped_to_mappings(session["master"])
