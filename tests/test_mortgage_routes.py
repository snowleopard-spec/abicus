from fastapi.testclient import TestClient

EXPECTED = {
    "/api/mortgage/config",
    "/api/mortgage/state",
    "/api/mortgage/schedule",
}


def test_mortgage_has_all_routes(all_paths):
    missing = EXPECTED - all_paths
    assert not missing, f"missing routes: {missing}"


def test_mortgage_state_decimal_strings(app):
    c = TestClient(app)
    r = c.get("/api/mortgage/state", params={"as_of": "2026-06-28"})
    assert r.status_code == 200
    s = r.json()
    # Money fields serialised as strings (precision-preserving per spec §11.4)
    for k in ("principal", "accrued_interest", "remaining_loan", "next_payment_amount"):
        assert isinstance(s[k], str), f"{k} is {type(s[k]).__name__}, expected str"
    assert s["currency"] == "SGD"
    assert s["next_payment_date"]  # populated when not paid_off


def test_mortgage_schedule_summary(app):
    c = TestClient(app)
    sch = c.get("/api/mortgage/schedule").json()
    assert sch["rows"]
    assert sch["summary"]["payoff_date"]
    # payoff date matches the last row's payment_date
    assert sch["rows"][-1]["payment_date"] == sch["summary"]["payoff_date"]
