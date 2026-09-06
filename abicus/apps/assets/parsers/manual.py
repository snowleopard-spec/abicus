"""
Parser for the Manual export file.
Reads the file as-is — all attributes are pre-populated in the spreadsheet.
For rows with Auto Calc Flag = TRUE, resolves prices via the caller-supplied
`resolve_prices` callback and calculates Balance (Local) from Units × Price.
Handles both Excel (.xlsx/.xls) and CSV (.csv) files.
"""

import pandas as pd


# Expected columns in the manual file
EXPECTED_COLUMNS = [
    "Asset Name",
    "Asset Class",
    "Currency",
    "Institution",
    "Account Type",
    "Jurisdiction",
    "Beneficiary",
    "Balance (Local)",
    "US Situs Flag",
    "Auto Calc",
    "Units",
    "Ticker",
    "Tag",
]


def read_file(file):
    """Read a file as either Excel or CSV based on filename."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file)


def parse(file, file_config, mapping_asset_class, mapping_us_situs, *, context=None):
    """
    Parse a Manual export file into the standard portfolio schema.

    `context` may carry a `resolve_prices` callable that maps a list of
    tickers to `(prices, failed, meta)`. Supplied by the pipeline so this
    parser stays offline-only and never imports yfinance directly.
    """

    # --- 1. Read the file ---
    df = read_file(file)

    # --- 2. Clean column names (strip whitespace) ---
    df.columns = df.columns.str.strip()

    # --- 3. Check for missing columns ---
    missing = [col for col in EXPECTED_COLUMNS if col not in df.columns]
    if missing:
        found = df.columns.tolist()
        raise ValueError(
            f"Missing columns in manual file: {missing}\n"
            f"Columns found in file: {found}"
        )

    # --- 4. Handle Auto Calc rows ---
    price_errors: list[str] = []
    yfinance_error = False
    fetched_prices: dict = {}

    df["Auto Calc"] = df["Auto Calc"].astype(str).str.strip().str.upper()
    auto_calc_mask = df["Auto Calc"] == "TRUE"
    auto_calc_rows = df[auto_calc_mask]

    if len(auto_calc_rows) > 0:
        tickers = auto_calc_rows["Ticker"].dropna().unique().tolist()
        resolve_prices = (context or {}).get("resolve_prices")

        if resolve_prices is None:
            yfinance_error = True
            prices: dict = {t: None for t in tickers}
            price_errors = list(tickers)
        else:
            prices, price_errors, meta = resolve_prices(tickers)
            yfinance_error = bool(meta.get("yfinance_error", False))
            fetched_prices = {t: p for t, p in prices.items() if p is not None}

        for idx in auto_calc_rows.index:
            ticker = df.at[idx, "Ticker"]
            units = df.at[idx, "Units"]
            if pd.notna(ticker) and prices.get(ticker) is not None:
                price = prices[ticker]
                # London Stock Exchange quotes are in pence — convert to
                # pounds for the balance ONLY. `fetched_prices` (and the
                # stock_prices cache persisted from it) always hold the raw
                # quote, so save → reload → recompile divides exactly once.
                if str(ticker).upper().endswith(".L"):
                    price = price / 100
                df.at[idx, "Balance (Local)"] = units * price

    # --- 5. Build the standard output ---
    output = pd.DataFrame(
        {
            "Asset Name": df["Asset Name"].values,
            "Asset Class": df["Asset Class"].values,
            "Currency": df["Currency"].values,
            "Institution": df["Institution"].values,
            "Account Type": df["Account Type"].values,
            "Jurisdiction": df["Jurisdiction"].values,
            "Beneficiary": df["Beneficiary"].values,
            "Balance (Local)": df["Balance (Local)"].values,
            "Balance (USD)": None,
            "US Situs Flag": df["US Situs Flag"].values,
            "Tag": df["Tag"].values,
        }
    )

    output = output.reset_index(drop=True)

    output.attrs["price_errors"] = price_errors
    output.attrs["yfinance_error"] = yfinance_error
    output.attrs["fetched_prices"] = fetched_prices

    return output
