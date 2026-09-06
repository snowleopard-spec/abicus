"""Claims logic tests — V3.1 M3/M4.

Each test names the ARCHITECTURE.md §6 invariant it pins (# C-n).
Route tests run against a temp DB: DB_PATH / config paths / INVOICE_DIR
are monkeypatched into tmp_path and db._init_done is reset so the
schema is created in the temp file (invariant C-7: schema init runs
once per process and would otherwise short-circuit).
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from abicus.apps.claims import db, files
from abicus.apps.claims.status import compute_status


# ---------- fixtures ----------

@pytest.fixture
def claims_env(tmp_path, monkeypatch):
    """Point every claims persistence path into tmp_path and reset the
    module-global init latch (# C-7) so the schema is built in the temp DB."""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "mediclaim.db")
    monkeypatch.setattr(db, "CLAIMANTS_PATH", config_dir / "claimants.json")
    monkeypatch.setattr(db, "INSTITUTIONS_PATH", config_dir / "institutions.json")
    monkeypatch.setattr(files, "INVOICE_DIR", data_dir / "invoices")
    monkeypatch.setattr(db, "_init_done", False)
    yield tmp_path


@pytest.fixture
def client(app, claims_env):
    return TestClient(app)


FORM = {
    "claimant": "Self",
    "institution": "Mount E",
    "amount": "120.50",
    "currency": "SGD",
    "date_incurred": "2026-01-15",
}


def _create(client, **overrides):
    data = {**FORM, **overrides}
    return client.post("/api/claims/claims", data=data)


# ---------- C-1: compute_status is a strict cascade, exact strings ----------

def test_status_cascade_exact_strings_in_precedence_order():
    # C-1: the order of the ifs IS the business rule; the frontend
    # pattern-matches these exact strings.
    def row(excluded=0, invoice_received=0, claimed=0, rebated=0):
        return {
            "excluded": excluded,
            "invoice_received": invoice_received,
            "claimed": claimed,
            "rebated": rebated,
        }

    # Excluded beats everything, even the data-integrity warning state.
    assert compute_status(row(excluded=1, invoice_received=1, claimed=0, rebated=1)) == "Excluded"
    # Rebated-but-not-claimed beats Complete/Claim submitted/Ready.
    assert compute_status(row(invoice_received=1, claimed=0, rebated=1)) == "Check: rebated but not claimed"
    # Rebated (and claimed) → Complete, beating Claim submitted.
    assert compute_status(row(invoice_received=1, claimed=1, rebated=1)) == "Complete"
    # Claimed (not rebated) → Claim submitted, beating Ready to claim.
    assert compute_status(row(invoice_received=1, claimed=1, rebated=0)) == "Claim submitted"
    # Invoice received only → Ready to claim.
    assert compute_status(row(invoice_received=1)) == "Ready to claim"
    # Nothing set → Awaiting invoice.
    assert compute_status(row()) == "Awaiting invoice"


# ---------- C-2: outstanding three-branch clamp ----------

def test_outstanding_three_branches_and_over_rebate_clamp(claims_env):
    # C-2: excluded → 0; rebated → max(amount − rebated, 0); else full amount.
    excluded = db.create_claim({
        "claimant": "Self", "institution": "A", "amount": 100.0,
        "date_incurred": "2026-01-01", "excluded": True,
    })
    assert excluded["outstanding"] == 0.0

    rebated = db.create_claim({
        "claimant": "Self", "institution": "A", "amount": 100.0,
        "date_incurred": "2026-01-01", "rebated": True, "amount_rebated": 30.0,
    })
    assert rebated["outstanding"] == pytest.approx(70.0)

    # C-2: an over-rebate never goes negative.
    over = db.create_claim({
        "claimant": "Self", "institution": "A", "amount": 100.0,
        "date_incurred": "2026-01-01", "rebated": True, "amount_rebated": 150.0,
    })
    assert over["outstanding"] == 0.0

    # C-2: submitted-but-unrebated is still fully outstanding.
    claimed = db.create_claim({
        "claimant": "Self", "institution": "A", "amount": 100.0,
        "date_incurred": "2026-01-01", "claimed": True, "amount_rebated": 30.0,
    })
    assert claimed["outstanding"] == pytest.approx(100.0)


# ---------- C-9: toggle_flag whitelist is the SQL-injection guard ----------

def test_toggle_flag_unknown_field_raises_valueerror():
    # C-9: the field name is f-string-interpolated; the whitelist is the
    # only thing making that safe. The check fires before any DB touch.
    with pytest.raises(ValueError):
        db.toggle_flag(1, "archived")
    with pytest.raises(ValueError):
        db.toggle_flag(1, "id; DROP TABLE claims--")


def test_toggle_route_maps_unknown_field_to_400(client):
    # C-9: route maps the whitelist ValueError to a 400.
    created = _create(client)
    assert created.status_code == 200
    claim_id = created.json()["id"]
    r = client.post(f"/api/claims/claims/{claim_id}/toggle", data={"field": "archived"})
    assert r.status_code == 400
    # A whitelisted field still toggles fine.
    r = client.post(f"/api/claims/claims/{claim_id}/toggle", data={"field": "claimed"})
    assert r.status_code == 200
    assert r.json()["claimed"] == 1


# ---------- C-15/C-16: invoice filename shape + collision suffixes ----------

def test_invoice_filename_shape_sanitisation_and_sentinel():
    # C-15: YYYYMMDD_Claimant_Institution.ext, sanitised at write time.
    assert files.invoice_filename("Self", "Mount E", "2026-01-15", "scan.pdf") == \
        "20260115_Self_MountE.pdf"
    # Unsafe chars stripped from the tokens.
    assert files.invoice_filename("A/B c!", "Ins*t", "2026-01-15", "scan.pdf") == \
        "20260115_ABc_Inst.pdf"
    # C-15: missing date → the "00000000" sentinel.
    assert files.invoice_filename("Self", "Clinic", "", "scan.pdf") == \
        "00000000_Self_Clinic.pdf"
    # Extension is lowercased.
    assert files.invoice_filename("Self", "Clinic", "2026-01-15", "SCAN.PDF").endswith(".pdf")


def test_invoice_collision_suffixes(tmp_path, monkeypatch):
    # C-16: collisions get _2 then _3 suffixes when files already exist.
    monkeypatch.setattr(files, "INVOICE_DIR", tmp_path)
    first = files.store_invoice("Self", "Clinic", "2026-01-15", "a.pdf", io.BytesIO(b"one"))
    second = files.store_invoice("Self", "Clinic", "2026-01-15", "b.pdf", io.BytesIO(b"two"))
    third = files.store_invoice("Self", "Clinic", "2026-01-15", "c.pdf", io.BytesIO(b"three"))
    assert first == "20260115_Self_Clinic.pdf"
    assert second == "20260115_Self_Clinic_2.pdf"
    assert third == "20260115_Self_Clinic_3.pdf"
    for name in (first, second, third):
        assert (tmp_path / name).exists()


# ---------- C-13/C-14: archive vs permanent delete ----------

def test_delete_archives_and_row_stays_listable(client):
    # C-13: DELETE /claims/{id} archives; the row moves to /claims/archived.
    claim_id = _create(client).json()["id"]
    r = client.delete(f"/api/claims/claims/{claim_id}")
    assert r.status_code == 200
    active_ids = [c["id"] for c in client.get("/api/claims/claims").json()]
    archived_ids = [c["id"] for c in client.get("/api/claims/claims/archived").json()]
    assert claim_id not in active_ids
    assert claim_id in archived_ids


def test_permanent_delete_removes_row_and_files(client, claims_env):
    # C-14: only /permanent deletes — DB row first, file unlinks after.
    created = _create(client)
    claim_id = created.json()["id"]
    up = client.post(
        f"/api/claims/claims/{claim_id}/invoice",
        files={"file": ("scan.pdf", b"%PDF", "application/pdf")},
    )
    assert up.status_code == 200
    stored = up.json()["invoice_file"]
    invoice_path = claims_env / "data" / "invoices" / stored
    assert invoice_path.exists()

    r = client.delete(f"/api/claims/claims/{claim_id}/permanent")
    assert r.status_code == 200
    assert not invoice_path.exists()
    assert claim_id not in [c["id"] for c in client.get("/api/claims/claims").json()]
    assert claim_id not in [c["id"] for c in client.get("/api/claims/claims/archived").json()]


def test_permanent_delete_missing_file_does_not_500(client):
    # C-14: file unlink is best-effort — an orphan/missing file must not
    # turn the delete into a 500 with the row already gone.
    claim_id = _create(client).json()["id"]
    db.set_invoice_file(claim_id, "does_not_exist_on_disk.pdf")
    r = client.delete(f"/api/claims/claims/{claim_id}/permanent")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------- V3.1 R3: SGD-only enforcement ----------

def test_create_non_sgd_rejected_with_400(client):
    # R3 (spec V3.1): claims are SGD-only, enforced on create.
    r = _create(client, currency="USD")
    assert r.status_code == 400
    assert "SGD" in r.json()["detail"]
    # And nothing was persisted.
    assert client.get("/api/claims/claims").json() == []


def test_create_sgd_accepted(client):
    r = _create(client, currency="SGD")
    assert r.status_code == 200
    assert r.json()["currency"] == "SGD"


def test_update_non_sgd_rejected_with_400(client):
    # R3: the same guard covers the update path.
    claim_id = _create(client).json()["id"]
    r = client.put(f"/api/claims/claims/{claim_id}", data={**FORM, "currency": "EUR"})
    assert r.status_code == 400
    assert "SGD" in r.json()["detail"]
    # Row unchanged.
    assert client.get("/api/claims/claims").json()[0]["currency"] == "SGD"
