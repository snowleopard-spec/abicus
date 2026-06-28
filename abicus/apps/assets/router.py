from fastapi import APIRouter, Request

from abicus.templating import templates

api_router = APIRouter()
views_router = APIRouter()


@views_router.get("")
@views_router.get("/")
def page(request: Request):
    return templates.TemplateResponse(
        request,
        "assets/page.html",
        {"active": "assets"},
    )
