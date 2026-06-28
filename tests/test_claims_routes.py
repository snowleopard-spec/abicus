EXPECTED = {
    "/api/claims/config",
    "/api/claims/institutions",
    "/api/claims/claims",
    "/api/claims/claims/{claim_id}",
    "/api/claims/claims/{claim_id}/toggle",
    "/api/claims/claims/archived",
    "/api/claims/claims/{claim_id}/restore",
    "/api/claims/claims/{claim_id}/permanent",
    "/api/claims/claims/{claim_id}/invoice",
    "/api/claims/claims/{claim_id}/files",
    "/api/claims/claims/{claim_id}/files/{file_id}",
}


def test_claims_has_all_legacy_routes(all_paths):
    missing = EXPECTED - all_paths
    assert not missing, f"missing routes: {missing}"
