EXPECTED = {
    "/api/outflows/config",
    "/api/outflows/compile",
    "/api/outflows/download/categorised/{session_id}",
    "/api/outflows/download/unmapped/{session_id}",
    "/api/outflows/download/html/{session_id}",
    "/api/outflows/history/append/{session_id}",
}


def test_outflows_has_all_legacy_routes(all_paths):
    missing = EXPECTED - all_paths
    assert not missing, f"missing routes: {missing}"
