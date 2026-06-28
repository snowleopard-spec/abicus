EXPECTED = {
    "/api/assets/config",
    "/api/assets/compile",
    "/api/assets/load",
    "/api/assets/save/{session_id}",
    "/api/assets/download/pdf/{session_id}",
    "/api/assets/download/excel/{session_id}",
    "/api/assets/unmapped/add/{session_id}",
}


def test_assets_has_all_legacy_routes(all_paths):
    missing = EXPECTED - all_paths
    assert not missing, f"missing routes: {missing}"
