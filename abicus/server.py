from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from abicus.apps.outflows.router import api_router as outflows_api, views_router as outflows_views
from abicus.apps.assets.router import api_router as assets_api, views_router as assets_views
from abicus.apps.claims.router import api_router as claims_api, views_router as claims_views
from abicus.apps.loan.router import api_router as loan_api, views_router as loan_views

ROOT = Path(__file__).parent

app = FastAPI(title="Abicus")

app.mount(
    "/shell/static",
    StaticFiles(directory=ROOT / "shell" / "static"),
    name="shell-static",
)

for _name in ("outflows", "assets", "claims", "loan"):
    app.mount(
        f"/{_name}/static",
        StaticFiles(directory=ROOT / "apps" / _name / "static"),
        name=f"{_name}-static",
    )

app.include_router(outflows_views, prefix="/outflows")
app.include_router(assets_views, prefix="/assets")
app.include_router(claims_views, prefix="/claims")
app.include_router(loan_views, prefix="/loan")

app.include_router(outflows_api, prefix="/api/outflows")
app.include_router(assets_api, prefix="/api/assets")
app.include_router(claims_api, prefix="/api/claims")
app.include_router(loan_api, prefix="/api/loan")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/outflows", status_code=307)
