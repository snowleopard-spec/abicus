"""Tests that a default compile is fully offline and that live price fetches
are batched into a single yfinance call rather than per-ticker requests."""

import io
from unittest.mock import patch

import pandas as pd
import pytest

from abicus.apps.assets import pipeline


MANUAL_CSV = (
    "Asset Name,Asset Class,Currency,Institution,Account Type,Jurisdiction,"
    "Beneficiary,Balance (Local),US Situs Flag,Auto Calc,Units,Ticker,Tag\n"
    "Apple,Single Stock,USD,Broker,Brokerage,US,W,,Y,TRUE,100,AAPL,\n"
    "Google,Single Stock,USD,Broker,Brokerage,US,W,,Y,TRUE,50,GOOG,\n"
    "USD Cash,Cash,USD,Broker,Brokerage,US,W,10000,N,FALSE,,,\n"
)

VALID_FX = {
    "USD": 1.0, "GBP": 0.79, "EUR": 0.92, "SGD": 1.34,
    "AUD": 1.44, "HKD": 7.82, "JPY": 150.0,
}


@pytest.fixture
def manual_buf():
    buf = io.BytesIO(MANUAL_CSV.encode())
    buf.name = "manual.csv"
    return buf


@pytest.fixture
def config():
    return pipeline.load_config()


def test_default_compile_makes_no_network_calls(manual_buf, config, monkeypatch):
    """Warm cached_prices + live_prices=False → parser resolves everything
    from cache, so neither requests.get nor yf.download fires."""
    monkeypatch.delenv("ABICUS_LIVE_PRICES", raising=False)
    cached = {"AAPL": 200.0, "GOOG": 150.0}
    with patch("abicus.apps.assets.pipeline.yf") as yf_mock, \
         patch("abicus.apps.assets.fx_rates.requests.get") as get:
        result = pipeline.compile_master(
            [("manual.csv", manual_buf, "Manual Upload")],
            config,
            rates=VALID_FX,
            fx_error=False,
            live_prices=False,
            cached_prices=cached,
        )

    yf_mock.download.assert_not_called()
    get.assert_not_called()

    master = result["master"]
    assert master is not None and len(master) == 3
    apple = master[master["Asset Name"] == "Apple"].iloc[0]
    assert apple["Balance (Local)"] == 100 * 200.0
    goog = master[master["Asset Name"] == "Google"].iloc[0]
    assert goog["Balance (Local)"] == 50 * 150.0


def test_live_true_batches_all_tickers_into_one_call(manual_buf, config):
    """live_prices=True should invoke the batched fetcher exactly once with
    every ticker at once — not once per ticker."""
    with patch(
        "abicus.apps.assets.pipeline.fetch_stock_prices_batched",
        return_value=({"AAPL": 200.0, "GOOG": 150.0}, []),
    ) as batch:
        pipeline.compile_master(
            [("manual.csv", manual_buf, "Manual Upload")],
            config,
            rates=VALID_FX,
            fx_error=False,
            live_prices=True,
            cached_prices=None,
        )

    assert batch.call_count == 1
    (tickers_arg,), _ = batch.call_args
    assert sorted(tickers_arg) == ["AAPL", "GOOG"]


def test_fetch_stock_prices_batched_issues_single_download():
    """yfinance's `download` should be invoked once with a space-joined ticker
    string — i.e. one upstream call carrying all tickers together."""
    fake = pd.DataFrame(
        {
            ("AAPL", "Close"): [200.0],
            ("GOOG", "Close"): [150.0],
        }
    )
    fake.columns = pd.MultiIndex.from_tuples(fake.columns)
    with patch("abicus.apps.assets.pipeline.yf") as yf_mock:
        yf_mock.download.return_value = fake
        prices, failed = pipeline.fetch_stock_prices_batched(["AAPL", "GOOG"])

    assert yf_mock.download.call_count == 1
    kwargs = yf_mock.download.call_args.kwargs
    assert kwargs["tickers"] == "AAPL GOOG"
    assert prices == {"AAPL": 200.0, "GOOG": 150.0}
    assert failed == []


def test_no_live_and_no_cache_flags_price_errors(manual_buf, config, monkeypatch):
    """Without cache or live flag, Auto Calc tickers can't be priced. The
    compile must not call yfinance and must report the tickers as price
    errors so the UI surfaces the gap."""
    monkeypatch.delenv("ABICUS_LIVE_PRICES", raising=False)
    with patch("abicus.apps.assets.pipeline.yf") as yf_mock:
        result = pipeline.compile_master(
            [("manual.csv", manual_buf, "Manual Upload")],
            config,
            rates=VALID_FX,
            fx_error=False,
            live_prices=False,
            cached_prices=None,
        )
    yf_mock.download.assert_not_called()
    assert set(result["price_errors"]) == {"AAPL", "GOOG"}


def test_env_flag_enables_live_prices(manual_buf, config, monkeypatch):
    monkeypatch.setenv("ABICUS_LIVE_PRICES", "1")
    with patch(
        "abicus.apps.assets.pipeline.fetch_stock_prices_batched",
        return_value=({"AAPL": 200.0, "GOOG": 150.0}, []),
    ) as batch:
        pipeline.compile_master(
            [("manual.csv", manual_buf, "Manual Upload")],
            config,
            rates=VALID_FX,
            fx_error=False,
            live_prices=False,  # env should still enable it
            cached_prices=None,
        )
    assert batch.call_count == 1


def test_lse_price_conversion_from_pence_preserved(config):
    """Regression guard: `.L` tickers still convert pence→pounds after the
    refactor, so Balance (Local) maths for LSE holdings is unchanged."""
    csv = (
        "Asset Name,Asset Class,Currency,Institution,Account Type,Jurisdiction,"
        "Beneficiary,Balance (Local),US Situs Flag,Auto Calc,Units,Ticker,Tag\n"
        "Vanguard FTSE,ETF,GBP,Broker,Brokerage,UK,W,,N,TRUE,10,VUKE.L,\n"
    )
    buf = io.BytesIO(csv.encode())
    buf.name = "manual.csv"

    result = pipeline.compile_master(
        [("manual.csv", buf, "Manual Upload")],
        config,
        rates=VALID_FX,
        fx_error=False,
        live_prices=False,
        cached_prices={"VUKE.L": 4200.0},  # pence
    )
    row = result["master"].iloc[0]
    assert row["Balance (Local)"] == pytest.approx(10 * 42.0)  # pounds
