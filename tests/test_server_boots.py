from fastapi.testclient import TestClient


def test_root_redirects_to_outflows(app):
    c = TestClient(app, follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/outflows"


def test_each_subapp_serves_html(app):
    c = TestClient(app)
    for name in ("outflows", "assets", "claims", "loan"):
        r = c.get(f"/{name}")
        assert r.status_code == 200, f"/{name} returned {r.status_code}"
        body = r.text.lower()
        assert "<html" in body
        # active state is wired through to the body tag
        assert f'data-active="{name}"' in body


def test_each_subapp_config_endpoint(app):
    c = TestClient(app)
    for name in ("outflows", "assets", "claims", "loan"):
        r = c.get(f"/api/{name}/config")
        assert r.status_code == 200, f"/api/{name}/config returned {r.status_code}: {r.text[:200]}"


def test_each_subapp_static_serves(app):
    c = TestClient(app)
    for name in ("outflows", "assets", "claims", "loan"):
        r = c.get(f"/{name}/static/{name}.css")
        assert r.status_code == 200, f"/{name}/static/{name}.css returned {r.status_code}"
    # shell statics
    for path in ("tokens.css", "shell.css", "components.css"):
        r = c.get(f"/shell/static/css/{path}")
        assert r.status_code == 200
