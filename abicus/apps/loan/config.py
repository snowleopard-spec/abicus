import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from abicus.apps.loan.simulate import Loan

CONFIG_DIR = Path(__file__).resolve().parent / "config"
LOAN_PATH = CONFIG_DIR / "loan.json"


def load_loan() -> Loan:
    raw = json.loads(LOAN_PATH.read_text())
    return Loan(
        origin_date=date.fromisoformat(raw["origin_date"]),
        origin_principal=Decimal(str(raw["origin_principal"])),
        annual_rate=Decimal(str(raw["annual_rate"])),
        monthly_payment=Decimal(str(raw["monthly_payment"])),
        original_tenor_months=int(raw["original_tenor_months"]),
        maturity_date=date.fromisoformat(raw["maturity_date"]),
        payment_day_of_month=int(raw["payment_day_of_month"]),
        currency=str(raw["currency"]),
    )


def save_loan(loan: Loan) -> Loan:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOAN_PATH.write_text(json.dumps(loan_to_dict(loan), indent=2))
    return loan


def loan_to_dict(loan: Loan) -> dict:
    return {
        "origin_date": loan.origin_date.isoformat(),
        "origin_principal": str(loan.origin_principal),
        "annual_rate": str(loan.annual_rate),
        "monthly_payment": str(loan.monthly_payment),
        "original_tenor_months": loan.original_tenor_months,
        "maturity_date": loan.maturity_date.isoformat(),
        "payment_day_of_month": loan.payment_day_of_month,
        "currency": loan.currency,
    }
