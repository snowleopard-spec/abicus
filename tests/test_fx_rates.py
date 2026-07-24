"""Tests for the cache-first FX rates loader.

Guardrails: no test should hit the network. `requests.get` is patched in every
test that exercises the live path so a missed guard surfaces as an
AssertionError rather than a hanging HTTP call.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from abicus.apps.assets import fx_rates as fx_mod


VALID_RATES = {
    "USD": 1.0, "GBP": 0.79, "EUR": 0.92, "SGD": 1.34,
    "AUD": 1.44, "HKD": 7.82, "JPY": 150.0, "CHF": 0.88,
}


@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    """Redirect cache/snapshot to a temp dir and clear the live env flag."""
    cache = tmp_path / "fx_rates_cache.json"
    snapshot = tmp_path / "fx_rates_snapshot.json"
    monkeypatch.setattr(fx_mod, "RATES_CACHE_FILE", cache)
    monkeypatch.setattr(fx_mod, "RATES_SNAPSHOT_FILE", snapshot)
    monkeypatch.delenv("ABICUS_LIVE_FX", raising=False)
    return {"cache": cache, "snapshot": snapshot}


def _mock_ok(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


def test_default_prefers_cache_with_no_http_call(isolated_files):
    isolated_files["cache"].write_text(json.dumps(VALID_RATES))
    with patch("abicus.apps.assets.fx_rates.requests.get") as get:
        rates, meta = fx_mod.fetch_fx_rates()
    get.assert_not_called()
    assert meta == {"source": "cache", "fx_stale": True, "fx_error": False}
    assert rates["GBP"] == 0.79


def test_default_falls_back_to_snapshot_when_cache_missing(isolated_files):
    isolated_files["snapshot"].write_text(json.dumps(VALID_RATES))
    with patch("abicus.apps.assets.fx_rates.requests.get") as get:
        rates, meta = fx_mod.fetch_fx_rates()
    get.assert_not_called()
    assert meta["source"] == "snapshot"
    assert meta["fx_stale"] is True
    assert meta["fx_error"] is False
    assert rates["EUR"] == 0.92


def test_no_cache_no_snapshot_returns_usd_only_with_error(isolated_files):
    with patch("abicus.apps.assets.fx_rates.requests.get") as get:
        rates, meta = fx_mod.fetch_fx_rates()
    get.assert_not_called()
    assert rates == {"USD": 1.0}
    assert meta["fx_error"] is True
    assert meta["fx_stale"] is True


def test_live_true_fetches_and_populates_cache(isolated_files):
    resp = _mock_ok({"rates": VALID_RATES})
    with patch("abicus.apps.assets.fx_rates.requests.get", return_value=resp) as get:
        rates, meta = fx_mod.fetch_fx_rates(live=True)
    get.assert_called_once()
    assert meta == {"source": "live", "fx_stale": False, "fx_error": False}
    assert json.loads(isolated_files["cache"].read_text())["JPY"] == 150.0
    assert rates["JPY"] == 150.0


def test_malformed_200_does_not_poison_cache(isolated_files):
    """A 200 response missing expected currencies must not overwrite the cache
    or be treated as valid. The loader falls back to snapshot cleanly."""
    isolated_files["snapshot"].write_text(json.dumps(VALID_RATES))
    resp = _mock_ok({"rates": {"USD": 1.0}})  # truncated table
    with patch("abicus.apps.assets.fx_rates.requests.get", return_value=resp):
        rates, meta = fx_mod.fetch_fx_rates(live=True)
    assert meta["source"] == "snapshot"
    assert meta["fx_stale"] is True
    assert meta["fx_error"] is False
    assert not isolated_files["cache"].exists()
    assert rates["GBP"] == 0.79


def test_env_flag_enables_live_without_explicit_param(isolated_files, monkeypatch):
    monkeypatch.setenv("ABICUS_LIVE_FX", "1")
    resp = _mock_ok({"rates": VALID_RATES})
    with patch("abicus.apps.assets.fx_rates.requests.get", return_value=resp) as get:
        rates, meta = fx_mod.fetch_fx_rates()
    get.assert_called_once()
    assert meta["source"] == "live"


def test_live_network_error_falls_back_to_cache(isolated_files):
    isolated_files["cache"].write_text(json.dumps(VALID_RATES))
    with patch(
        "abicus.apps.assets.fx_rates.requests.get",
        side_effect=Exception("network down"),
    ):
        rates, meta = fx_mod.fetch_fx_rates(live=True)
    assert meta["source"] == "cache"
    assert meta["fx_stale"] is True
    assert meta["fx_error"] is False
    assert rates["AUD"] == 1.44
