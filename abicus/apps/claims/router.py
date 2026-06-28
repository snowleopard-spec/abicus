from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from abicus.apps.claims import db, files
from abicus.templating import templates

api_router = APIRouter()
views_router = APIRouter()


# ---------- views ----------

@views_router.get("")
@views_router.get("/")
def page(request: Request):
    return templates.TemplateResponse(
        request,
        "claims/page.html",
        {"active": "claims"},
    )


# ---------- config / institutions ----------

@api_router.get("/config")
def get_config():
    return {"claimants": db.load_claimants()}


@api_router.get("/institutions")
def get_institutions():
    return db.load_institutions()


class InstitutionIn(BaseModel):
    name: str


@api_router.post("/institutions")
def post_institution(body: InstitutionIn):
    try:
        return db.add_institution(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- claims list (declare specific path BEFORE /claims/{id} routes) ----------

@api_router.get("/claims/archived")
def list_archived():
    return db.list_claims(archived=True)


@api_router.get("/claims")
def list_active():
    return db.list_claims(archived=False)


# ---------- create / update ----------

def _claim_form_payload(
    claimant: str,
    institution: str,
    amount: float,
    currency: str,
    date_incurred: str,
    invoice_received: str | bool,
    claimed: str | bool,
    rebated: str | bool,
    excluded: str | bool,
    amount_rebated: float,
    notes: str,
) -> dict:
    def truthy(v):
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("1", "true", "on", "yes")
    return {
        "claimant": claimant,
        "institution": institution,
        "amount": amount,
        "currency": currency or "SGD",
        "date_incurred": date_incurred,
        "invoice_received": truthy(invoice_received),
        "claimed": truthy(claimed),
        "rebated": truthy(rebated),
        "excluded": truthy(excluded),
        "amount_rebated": amount_rebated,
        "notes": notes or "",
    }


@api_router.post("/claims")
async def create(
    claimant: str = Form(...),
    institution: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("SGD"),
    date_incurred: str = Form(...),
    invoice_received: str = Form("false"),
    claimed: str = Form("false"),
    rebated: str = Form("false"),
    excluded: str = Form("false"),
    amount_rebated: float = Form(0),
    notes: str = Form(""),
    invoice: UploadFile | None = File(None),
):
    payload = _claim_form_payload(
        claimant, institution, amount, currency, date_incurred,
        invoice_received, claimed, rebated, excluded, amount_rebated, notes,
    )
    if invoice is not None and invoice.filename:
        stored = files.store_invoice(
            payload["claimant"], payload["institution"], payload["date_incurred"],
            invoice.filename, invoice.file,
        )
        payload["invoice_file"] = stored
    created = db.create_claim(payload)
    return created


@api_router.put("/claims/{claim_id}")
async def update(
    claim_id: int,
    claimant: str = Form(...),
    institution: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("SGD"),
    date_incurred: str = Form(...),
    invoice_received: str = Form("false"),
    claimed: str = Form("false"),
    rebated: str = Form("false"),
    excluded: str = Form("false"),
    amount_rebated: float = Form(0),
    notes: str = Form(""),
    invoice: UploadFile | None = File(None),
):
    payload = _claim_form_payload(
        claimant, institution, amount, currency, date_incurred,
        invoice_received, claimed, rebated, excluded, amount_rebated, notes,
    )
    if invoice is not None and invoice.filename:
        stored = files.store_invoice(
            payload["claimant"], payload["institution"], payload["date_incurred"],
            invoice.filename, invoice.file,
        )
        db.set_invoice_file(claim_id, stored)
    updated = db.update_claim(claim_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return updated


# ---------- toggle / archive / restore / delete ----------

@api_router.post("/claims/{claim_id}/toggle")
def toggle(claim_id: int, field: str = Form(...)):
    try:
        result = db.toggle_flag(claim_id, field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return result


@api_router.delete("/claims/{claim_id}")
def archive(claim_id: int):
    if not db.archive_claim(claim_id):
        raise HTTPException(status_code=404, detail="claim not found")
    return {"ok": True}


@api_router.post("/claims/{claim_id}/restore")
def restore(claim_id: int):
    if not db.restore_claim(claim_id):
        raise HTTPException(status_code=404, detail="claim not found")
    return {"ok": True}


@api_router.delete("/claims/{claim_id}/permanent")
def delete_permanent(claim_id: int):
    deleted, orphans = db.delete_claim_permanent(claim_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="claim not found")
    for name in orphans:
        files.delete_if_exists(name)
    return {"ok": True, "deleted": claim_id}


# ---------- invoice ----------

@api_router.get("/claims/{claim_id}/invoice")
def get_invoice(claim_id: int):
    claim = db.get_claim(claim_id)
    if not claim or not claim.get("invoice_file"):
        raise HTTPException(status_code=404, detail="no invoice")
    path = files.resolve(claim["invoice_file"])
    if path is None:
        raise HTTPException(status_code=404, detail="invoice file missing on disk")
    return FileResponse(path, filename=claim["invoice_file"])


@api_router.post("/claims/{claim_id}/invoice")
async def upload_invoice(claim_id: int, file: UploadFile = File(...)):
    claim = db.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="claim not found")
    stored = files.store_invoice(
        claim["claimant"], claim["institution"], claim["date_incurred"],
        file.filename, file.file,
    )
    db.set_invoice_file(claim_id, stored)
    return {"ok": True, "invoice_file": stored}


# ---------- other docs ----------

@api_router.post("/claims/{claim_id}/files")
async def upload_other_file(claim_id: int, file: UploadFile = File(...)):
    if not db.get_claim(claim_id):
        raise HTTPException(status_code=404, detail="claim not found")
    stored = files.store_other_doc(claim_id, file.filename, file.file)
    record = db.add_file(claim_id, stored, file.filename or stored)
    return record


@api_router.get("/claims/{claim_id}/files/{file_id}")
def download_other_file(claim_id: int, file_id: int):
    f = db.get_file(claim_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="file not found")
    path = files.resolve(f["filename"])
    if path is None:
        raise HTTPException(status_code=404, detail="file missing on disk")
    return FileResponse(path, filename=f["original_name"])


@api_router.delete("/claims/{claim_id}/files/{file_id}")
def delete_other_file(claim_id: int, file_id: int):
    name = db.delete_file(claim_id, file_id)
    if name is None:
        raise HTTPException(status_code=404, detail="file not found")
    files.delete_if_exists(name)
    return {"ok": True, "deleted": file_id}
