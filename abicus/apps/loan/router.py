from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from abicus.apps.loan.config import load_loan, loan_to_dict, save_loan
from abicus.apps.loan.simulate import Loan, generate_schedule, simulate_state
from abicus.templating import templates

api_router = APIRouter()
views_router = APIRouter()


# ---------- view ----------

@views_router.get("")
@views_router.get("/")
def page(request: Request):
    return templates.TemplateResponse(
        request,
        "loan/page.html",
        {"active": "loan"},
    )


# ---------- request models ----------

class LoanIn(BaseModel):
    origin_date: date
    origin_principal: str = Field(...)
    annual_rate: str = Field(...)
    monthly_payment: str = Field(...)
    original_tenor_months: int
    maturity_date: date
    payment_day_of_month: int = Field(..., ge=1, le=28)
    currency: str

    @field_validator("origin_principal", "annual_rate", "monthly_payment")
    @classmethod
    def _decimal_parseable(cls, v: str) -> str:
        try:
            Decimal(str(v))
        except (InvalidOperation, ValueError):
            raise ValueError("must be decimal-parseable")
        return str(v)

    def to_loan(self) -> Loan:
        return Loan(
            origin_date=self.origin_date,
            origin_principal=Decimal(self.origin_principal),
            annual_rate=Decimal(self.annual_rate),
            monthly_payment=Decimal(self.monthly_payment),
            original_tenor_months=self.original_tenor_months,
            maturity_date=self.maturity_date,
            payment_day_of_month=self.payment_day_of_month,
            currency=self.currency,
        )


# ---------- serialisation helpers ----------

def _stringify_state(state: dict) -> dict:
    """Convert Decimal → str and date → isoformat for JSON safety."""
    out = {}
    for k, v in state.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif v is None:
            out[k] = None
        elif isinstance(v, dict):
            out[k] = _stringify_state(v)
        else:
            out[k] = v
    return out


def _stringify_schedule(sched: dict) -> dict:
    return {
        "rows": [_stringify_state(r) for r in sched["rows"]],
        "summary": _stringify_state(sched["summary"]),
    }


# ---------- endpoints ----------

@api_router.get("/config")
def get_config():
    try:
        loan = load_loan()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="loan.json missing — seed it via the migration script")
    return loan_to_dict(loan)


@api_router.put("/config")
def put_config(body: LoanIn):
    loan = body.to_loan()
    save_loan(loan)
    return loan_to_dict(loan)


@api_router.get("/state")
def get_state(as_of: date | None = None):
    try:
        loan = load_loan()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="loan.json missing")
    when = as_of or date.today()
    state = simulate_state(when, loan)
    return {"as_of": when.isoformat(), "currency": loan.currency, **_stringify_state(state)}


@api_router.get("/schedule")
def get_schedule(up_to: date | None = None):
    try:
        loan = load_loan()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="loan.json missing")
    sched = generate_schedule(loan, up_to=up_to)
    return {"currency": loan.currency, **_stringify_schedule(sched)}
