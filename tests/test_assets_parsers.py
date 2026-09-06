"""Fixture-driven tests for the assets parsers (V3.1 M5, spec R6/R7).

Every fixture under tests/fixtures/assets/ is fabricated — invented
asset names, round numbers, fake tickers. No real statement content.
Each test names the ARCHITECTURE.md §5 invariant it pins (# A-…).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from abicus.apps.assets.parsers import broker_a, broker_c, manual

FIXTURES = Path(__file__).parent / "fixtures" / "assets"

FILE_CONFIG = {
    "institution": "Fabricated Institution",
    "account_type": "Brokerage",
    "jurisdiction": "SG",
    "beneficiary": "Fabricated Person",
    "tag": "fab-tag",
}


def _mapping_df(kind: str, pairs: dict[str, str]) -> pd.DataFrame:
    """Build a mapping table in the shape pipeline.load_config passes
    (a DataFrame read from the mapping CSV)."""
    value_col = "Asset Class" if kind == "asset_class" else "US Situs Flag"
    return pd.DataFrame(
        {
            "Underlying Instrument Description": list(pairs.keys()),
            value_col: list(pairs.values()),
        }
    )


EMPTY_ASSET_CLASS = _mapping_df("asset_class", {})
EMPTY_US_SITUS = _mapping_df("us_situs", {})


# ---------------------------------------------------------------------------
# Broker A
# ---------------------------------------------------------------------------

# The mapping deliberately tries to override the hard-coded rules:
# the Cash line and the Stock line both have CSV entries pointing at
# "Bond ETF", and the Cash line claims US situs "Y".
BROKER_A_ASSET_CLASS = _mapping_df(
    "asset_class",
    {
        "Fabricated Cash Line": "Bond ETF",
        "Fabricated Stock Corp": "Bond ETF",
        "Fabricated Fund A": "Fabricated Class",
        "Fabricated Fund C": "   ",  # present but whitespace-only (A-1)
    },
)
BROKER_A_US_SITUS = _mapping_df(
    "us_situs",
    {
        "Fabricated Cash Line": "Y",
        "Fabricated Fund A": "Y",
    },
)


@pytest.fixture()
def broker_a_result() -> pd.DataFrame:
    return broker_a.parse(
        FIXTURES / "broker_a.xlsx",
        FILE_CONFIG,
        BROKER_A_ASSET_CLASS,
        BROKER_A_US_SITUS,
        context=None,
    )


def test_broker_a_latest_date_and_amount_type_filter(broker_a_result):
    # A-4: only the most recent date's rows survive, and of those only
    # Amount Type Name in {Cash, Position Values}.
    out = broker_a_result
    # Fixture has 2 old-date rows and 1 latest-date "Fees" row; the 5
    # latest-date Cash/Position Values rows remain.
    assert len(out) == 5
    names = set(out["Asset Name"])
    assert "Fabricated Old Fund" not in names  # old date dropped
    balances = set(out["Balance (Local)"])
    assert 999.0 not in balances  # old-date fund value gone
    assert 900.0 not in balances  # old-date cash value gone
    assert -10.0 not in balances  # latest-date 'Fees' row gone
    assert balances == {1000.0, 2000.0, 3000.0, 4000.0, 5000.0}


def test_broker_a_hardcoded_class_beats_mapping(broker_a_result):
    # A-2: Cash and Stock rows classify as "Cash"/"Single Stock" even
    # though the mapping CSV maps their descriptions to "Bond ETF";
    # other rows use the mapping; no mapping -> "UNMAPPED".
    out = broker_a_result.set_index("Asset Name")
    # Cash rows are renamed "<CCY> Cash Balance" by the parser.
    assert out.loc["USD Cash Balance", "Asset Class"] == "Cash"
    assert out.loc["Fabricated Stock Corp", "Asset Class"] == "Single Stock"
    assert out.loc["Fabricated Fund A", "Asset Class"] == "Fabricated Class"
    assert out.loc["Fabricated Fund B", "Asset Class"] == "UNMAPPED"


def test_broker_a_blank_mapping_is_unmapped(broker_a_result):
    # A-1: a mapping entry that is present but whitespace-only counts
    # as unmapped — the sentinel, not the blank, comes through.
    out = broker_a_result.set_index("Asset Name")
    assert out.loc["Fabricated Fund C", "Asset Class"] == "UNMAPPED"


def test_broker_a_cash_is_never_us_situs(broker_a_result):
    # A-3: cash is unconditionally non-US-situs, even though the situs
    # mapping claims "Y" for the cash line's description.
    out = broker_a_result.set_index("Asset Name")
    assert out.loc["USD Cash Balance", "US Situs Flag"] == "N"
    # Sanity: the mapping does apply to non-cash rows.
    assert out.loc["Fabricated Fund A", "US Situs Flag"] == "Y"
    assert out.loc["Fabricated Fund B", "US Situs Flag"] == "UNMAPPED"


# ---------------------------------------------------------------------------
# Broker C
# ---------------------------------------------------------------------------

BROKER_C_ASSET_CLASS = _mapping_df(
    "asset_class", {"Fabricated Fund A": "Fabricated Class"}
)
BROKER_C_US_SITUS = _mapping_df("us_situs", {"Fabricated Stock Corp": "Y"})


def _parse_broker_c(path) -> pd.DataFrame:
    return broker_c.parse(
        path,
        FILE_CONFIG,
        BROKER_C_ASSET_CLASS,
        BROKER_C_US_SITUS,
        context=None,
    )


def test_broker_c_positional_columns(tmp_path):
    # A-5: the positional column contract (0/2 row filter; 3=Field
    # Value, 4=Currency, 5=Symbol, 6=Description, 8=Local Quantity,
    # 12=Market Value). First the valid fixture parses to exact
    # values; then the same file with ONE extra column inserted after
    # index 2 (a re-export shift) mis-parses — proving this test
    # would catch a shifted export.
    out = _parse_broker_c(FIXTURES / "broker_c.csv")

    # Only the three Summary rows of the right section survive
    # (Detail row, other section, headers and footers all excluded).
    assert list(out["Asset Name"]) == [
        "EUR Cash Balance",
        "Fabricated Stock Corp",
        "Fabricated Fund A",
    ]
    assert list(out["Currency"]) == ["EUR", "USD", "GBP"]
    assert list(out["Balance (Local)"]) == [5000.0, 2500.0, 750.0]
    assert list(out["Asset Class"]) == [
        "Cash",
        "Single Stock",
        "Fabricated Class",
    ]
    assert list(out["US Situs Flag"]) == ["N", "Y", "UNMAPPED"]
    assert list(out["Tag"]) == ["fab-tag"] * 3

    # Now shift: insert one empty field after column 2 in every data
    # row, as a changed re-export would.
    marker = "Positions and Mark-to-Market Profit and Loss,Data,Summary,"
    text = (FIXTURES / "broker_c.csv").read_text()
    shifted_text = text.replace(marker, marker + ",")
    shifted = tmp_path / "broker_c_shifted.csv"
    shifted.write_text(shifted_text)

    shifted_out = _parse_broker_c(shifted)
    # The rows still match the 0/2 filter, but every positional read
    # lands one column early: balances vanish and the hard-coded
    # class rules no longer fire.
    assert len(shifted_out) == 3
    assert shifted_out["Balance (Local)"].isna().all()
    assert list(shifted_out["Asset Name"]) != list(out["Asset Name"])
    assert "Cash" not in set(shifted_out["Asset Class"])
    assert "Single Stock" not in set(shifted_out["Asset Class"])


def test_broker_c_forex_keeps_precomputed_usd():
    # A-6: Forex rows keep the pre-computed Balance (USD) from the
    # market-value column (index 12) and take Balance (Local) from the
    # local-quantity column (index 8); non-Forex rows get Balance
    # (USD) = NA and Balance (Local) from the market-value column.
    out = _parse_broker_c(FIXTURES / "broker_c.csv").set_index("Asset Name")

    forex = out.loc["EUR Cash Balance"]
    assert forex["Balance (Local)"] == 5000.0  # col 8, not col 12
    assert forex["Balance (USD)"] == 5500.0  # pre-computed, kept

    stock = out.loc["Fabricated Stock Corp"]
    assert stock["Balance (Local)"] == 2500.0  # col 12 (local, inverted)
    assert pd.isna(stock["Balance (USD)"])  # filled downstream

    fund = out.loc["Fabricated Fund A"]
    assert fund["Balance (Local)"] == 750.0
    assert pd.isna(fund["Balance (USD)"])


# ---------------------------------------------------------------------------
# Manual
# ---------------------------------------------------------------------------


def _parse_manual(context) -> pd.DataFrame:
    return manual.parse(
        FIXTURES / "manual.csv",
        FILE_CONFIG,
        EMPTY_ASSET_CLASS,
        EMPTY_US_SITUS,
        context=context,
    )


def test_manual_auto_calc_matches_only_true():
    # A-14: after upper-casing, only the string "TRUE" triggers Auto
    # Calc — "true" works via upper(), while "1"/"Y"/"yes" do not.
    calls: list[list[str]] = []

    def fake_resolve_prices(tickers):
        calls.append(list(tickers))
        return {"FAKE1": 5.0, "FAKE2": 7.0}, [], {}

    out = _parse_manual({"resolve_prices": fake_resolve_prices})

    # Only the TRUE/true rows' tickers went to the resolver.
    assert calls == [["FAKE1", "FAKE2"]]

    out = out.set_index("Asset Name")
    # Auto rows: Balance (Local) = Units x Price.
    assert out.loc["Fabricated Auto Upper", "Balance (Local)"] == 50.0  # 10 x 5
    assert out.loc["Fabricated Auto Lower", "Balance (Local)"] == 140.0  # 20 x 7
    # "1", "Y", "yes" rows keep the file's balance untouched.
    assert out.loc["Fabricated Not Auto One", "Balance (Local)"] == 333.0
    assert out.loc["Fabricated Not Auto Wye", "Balance (Local)"] == 444.0
    assert out.loc["Fabricated Not Auto Yes", "Balance (Local)"] == 555.0
    assert out.loc["Fabricated Static Cash", "Balance (Local)"] == 666.0

    assert out.attrs["yfinance_error"] is False
    assert out.attrs["price_errors"] == []
    assert out.attrs["fetched_prices"] == {"FAKE1": 5.0, "FAKE2": 7.0}


@pytest.mark.parametrize("context", [None, {}], ids=["context_none", "context_empty"])
def test_manual_missing_resolver_degrades(context):
    # A-15: with no resolve_prices in context, Auto Calc rows do not
    # raise — the parser sets yfinance_error, lists every auto ticker
    # in price_errors, and leaves balances as they were in the file.
    out = _parse_manual(context)

    assert out.attrs["yfinance_error"] is True
    assert out.attrs["price_errors"] == ["FAKE1", "FAKE2"]
    assert out.attrs["fetched_prices"] == {}

    out = out.set_index("Asset Name")
    assert out.loc["Fabricated Auto Upper", "Balance (Local)"] == 111.0
    assert out.loc["Fabricated Auto Lower", "Balance (Local)"] == 222.0
