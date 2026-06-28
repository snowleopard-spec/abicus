"""Mortgage simulation core, extracted from MortgageMonitor/cli.py.

Logic is unchanged: month-by-month accrual using Actual/365 day count,
payment day shifted forward over weekends, final payment trimmed to the
exact remaining balance + accrued interest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class Loan:
    origin_date: date
    origin_principal: Decimal
    annual_rate: Decimal
    monthly_payment: Decimal
    original_tenor_months: int
    maturity_date: date
    payment_day_of_month: int
    currency: str


def q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(x: Decimal) -> str:
    return f"{q(x):,.2f}"


def adjusted_payment_date(year: int, month: int, day_of_month: int) -> date:
    d = date(year, month, day_of_month)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def simulate_state(as_of: date, loan: Loan) -> dict:
    principal = loan.origin_principal
    prev_pmt_date = loan.origin_date
    y, m = loan.origin_date.year, loan.origin_date.month
    last_payment = None

    while True:
        y, m = next_month(y, m)
        pmt_date = adjusted_payment_date(y, m, loan.payment_day_of_month)
        days_full_period = (pmt_date - prev_pmt_date).days

        if pmt_date > as_of:
            days_accrued = (as_of - prev_pmt_date).days
            accrued = q(
                principal * loan.annual_rate * Decimal(days_accrued) / Decimal(365)
            )
            return {
                "principal": principal,
                "accrued_interest": accrued,
                "remaining_loan": q(principal + accrued),
                "next_payment_date": pmt_date,
                "next_payment_amount": loan.monthly_payment,
                "last_payment": last_payment,
                "days_since_last_payment": days_accrued,
                "paid_off": False,
            }

        interest = q(
            principal * loan.annual_rate * Decimal(days_full_period) / Decimal(365)
        )
        if principal + interest <= loan.monthly_payment:
            payment = q(principal + interest)
            principal_paid = principal
            principal = Decimal("0.00")
        else:
            payment = loan.monthly_payment
            principal_paid = q(payment - interest)
            principal = q(principal - principal_paid)

        last_payment = {
            "date": pmt_date,
            "amount": payment,
            "interest": interest,
            "principal_paid": principal_paid,
            "closing_principal": principal,
        }
        prev_pmt_date = pmt_date

        if principal <= 0:
            return {
                "principal": Decimal("0.00"),
                "accrued_interest": Decimal("0.00"),
                "remaining_loan": Decimal("0.00"),
                "next_payment_date": None,
                "next_payment_amount": Decimal("0.00"),
                "last_payment": last_payment,
                "days_since_last_payment": 0,
                "paid_off": True,
            }


def generate_schedule(loan: Loan, up_to: date | None = None) -> dict:
    """Full month-by-month amortisation from origin to payoff (or `up_to`)."""
    rows: list[dict] = []
    principal = loan.origin_principal
    prev_pmt_date = loan.origin_date
    y, m = loan.origin_date.year, loan.origin_date.month
    total_interest = Decimal("0")
    total_paid = Decimal("0")
    payoff_date: date | None = None

    # Safety: cap iterations to 2× the original tenor.
    max_iters = (loan.original_tenor_months or 360) * 2

    for _ in range(max_iters):
        y, m = next_month(y, m)
        pmt_date = adjusted_payment_date(y, m, loan.payment_day_of_month)
        if up_to is not None and pmt_date > up_to:
            break

        days_full_period = (pmt_date - prev_pmt_date).days
        interest = q(
            principal * loan.annual_rate * Decimal(days_full_period) / Decimal(365)
        )
        if principal + interest <= loan.monthly_payment:
            payment = q(principal + interest)
            principal_paid = principal
            principal = Decimal("0.00")
        else:
            payment = loan.monthly_payment
            principal_paid = q(payment - interest)
            principal = q(principal - principal_paid)

        total_interest += interest
        total_paid += payment
        rows.append({
            "payment_date": pmt_date,
            "amount": payment,
            "interest": interest,
            "principal_paid": principal_paid,
            "closing_principal": principal,
        })
        prev_pmt_date = pmt_date

        if principal <= 0:
            payoff_date = pmt_date
            break

    return {
        "rows": rows,
        "summary": {
            "total_interest": q(total_interest),
            "total_paid": q(total_paid),
            "payoff_date": payoff_date,
        },
    }
