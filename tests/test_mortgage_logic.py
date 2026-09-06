"""Mortgage simulation logic tests (V3_1 spec M2/M4, rule R7).

Each test names the ARCHITECTURE.md §7 invariant it pins. Loans are
built directly against the frozen dataclass — no loan.json needed for
pure simulate tests; only the 400 route test touches the app.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pytest
from fastapi.testclient import TestClient

from abicus.apps.mortgage.simulate import (
    Loan,
    adjusted_payment_date,
    generate_schedule,
    simulate_state,
)


def make_loan(**overrides) -> Loan:
    defaults = dict(
        origin_date=date(2025, 1, 10),
        origin_principal=Decimal("100000"),
        annual_rate=Decimal("0.04"),
        monthly_payment=Decimal("2000"),
        original_tenor_months=60,
        maturity_date=date(2030, 1, 10),
        payment_day_of_month=10,
        currency="SGD",
    )
    defaults.update(overrides)
    return Loan(**defaults)


# M-3: payment dates shift forward over weekends only.
def test_weekend_shift_forward_only():
    # 2025-03-15 is a Saturday, 2025-03-16 a Sunday: both shift forward
    # to Monday 2025-03-17. A weekday payment day is left untouched.
    sat = adjusted_payment_date(2025, 3, 15)
    sun = adjusted_payment_date(2025, 3, 16)
    mon = adjusted_payment_date(2025, 3, 17)
    assert sat == date(2025, 3, 17) and sat.weekday() == 0
    assert sun == date(2025, 3, 17) and sun.weekday() == 0
    assert mon == date(2025, 3, 17)  # unshifted


# M-3: the shifted date flows through the schedule (accrual window
# tracks the *adjusted* dates).
def test_weekend_shift_in_schedule():
    loan = make_loan(origin_date=date(2025, 2, 20), payment_day_of_month=15)
    rows = generate_schedule(loan)["rows"]
    # First payment: 2025-03-15 (Saturday) → Monday 2025-03-17.
    assert rows[0]["payment_date"] == date(2025, 3, 17)


# M-4: the first payment falls in the month AFTER origination.
def test_first_payment_month_after_origination():
    loan = make_loan()  # origin 2025-01-10, payment day 10
    rows = generate_schedule(loan)["rows"]
    assert rows[0]["payment_date"] == date(2025, 2, 10)  # a Monday, unshifted

    # Year rollover: December origin → first payment in January.
    dec = make_loan(origin_date=date(2025, 12, 10))
    first = generate_schedule(dec)["rows"][0]["payment_date"]
    assert (first.year, first.month) == (2026, 1)


# M-6: the final payment is trimmed to exactly principal + accrued
# interest and the balance lands on Decimal("0.00").
def test_final_payment_trimmed_to_balance():
    loan = make_loan(
        origin_principal=Decimal("1000"),
        annual_rate=Decimal("0.05"),
        monthly_payment=Decimal("500"),
        original_tenor_months=12,
    )
    sched = generate_schedule(loan)
    last = sched["rows"][-1]
    assert last["closing_principal"] == Decimal("0.00")
    assert last["amount"] == last["interest"] + last["principal_paid"]
    assert last["amount"] < loan.monthly_payment  # trimmed, not the full payment
    assert sched["summary"]["payoff_date"] == last["payment_date"]


# M-7: a paid-off loan returns explicit zeros, next_payment_date None,
# paid_off True (the frontend keys off that null).
def test_paid_off_state_shape():
    loan = make_loan(
        origin_principal=Decimal("1000"),
        annual_rate=Decimal("0.05"),
        monthly_payment=Decimal("500"),
        original_tenor_months=12,
    )
    state = simulate_state(date(2026, 12, 31), loan)
    assert state["paid_off"] is True
    assert state["principal"] == Decimal("0.00")
    assert state["accrued_interest"] == Decimal("0.00")
    assert state["remaining_loan"] == Decimal("0.00")
    assert state["next_payment_amount"] == Decimal("0.00")
    assert state["next_payment_date"] is None
    assert state["days_since_last_payment"] == 0


# M-1/M-2: Actual/365 accrual, quantised 2dp ROUND_HALF_UP at each step.
# Hand-computed: origin 2025-01-10 (Fri), payment day 10 → first payment
# 2025-02-10 (Mon, unshifted), a 31-day period.
def test_actual_365_accrual_hand_computed():
    loan = make_loan()  # 100000 @ 4%, origin 2025-01-10
    first = generate_schedule(loan)["rows"][0]
    expected = (
        Decimal("100000") * Decimal("0.04") * Decimal(31) / Decimal(365)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert first["interest"] == expected  # 339.73

    # Same arithmetic mid-period via simulate_state: 10 days accrued.
    state = simulate_state(date(2025, 1, 20), loan)
    expected_accrued = (
        Decimal("100000") * Decimal("0.04") * Decimal(10) / Decimal(365)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert state["accrued_interest"] == expected_accrued  # 109.59


# R2 guard: as_of before origin_date raises ValueError naming the
# origin date (previously produced negative accrued interest — §7 hazard).
def test_pre_origin_as_of_raises():
    loan = make_loan()
    with pytest.raises(ValueError) as exc:
        simulate_state(date(2025, 1, 9), loan)
    assert "2025-01-10" in str(exc.value)  # message names the origin date


# R2 guard via the API: pre-origin as_of → 400 with the message as detail.
def test_pre_origin_as_of_returns_400(app, monkeypatch):
    import abicus.apps.mortgage.router as mortgage_router

    loan = make_loan()
    monkeypatch.setattr(mortgage_router, "load_loan", lambda: loan)
    c = TestClient(app)
    r = c.get("/api/mortgage/state", params={"as_of": "2024-12-31"})
    assert r.status_code == 400
    assert "2025-01-10" in r.json()["detail"]


# R2 cap: a negative-amortisation loan (payment below first month's
# interest) returns instead of hanging — mirrors generate_schedule's
# 2×-tenor iteration cap.
def test_negative_amortisation_state_returns():
    loan = make_loan(
        origin_principal=Decimal("100000"),
        annual_rate=Decimal("0.10"),
        monthly_payment=Decimal("100"),  # < first month's interest (~849)
        original_tenor_months=12,  # cap = 24 iterations
    )
    state = simulate_state(date(2030, 1, 1), loan)
    assert state["paid_off"] is False
    assert state["principal"] > loan.origin_principal  # balance grew
    assert state["next_payment_date"] is not None
