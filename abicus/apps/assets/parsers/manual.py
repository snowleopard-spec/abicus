"""
Parser for the Manual export file.
Reads the file as-is — all attributes are pre-populated in the spreadsheet.
For rows with Auto Calc Flag = TRUE, fetches stock prices via yfinance
and calculates Balance (Local) from Units × Price.
Handles both Excel (.xlsx/.xls) and CSV (.csv) files.
"""

import pandas as pd

try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


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


def fetch_stock_prices(tickers):
    """
    Fetch current stock prices for a list of tickers.

    Returns
    -------
    tuple of (dict, list) : ({ticker: price}, [failed_tickers])
    """
    if not YFINANCE_AVAILABLE:
        return {t: None for t in tickers}, list(tickers)

    prices = {}
    failed = []

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            price = stock.fast_info.get("lastPrice", None)
            if price is None:
                hist = stock.history(period="1d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
            prices[ticker] = price
            if price is None:
                failed.append(ticker)
        except Exception:
            prices[ticker] = None
            failed.append(ticker)

    return prices, failed


def read_file(file):
    """Read a file as either Excel or CSV based on filename."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file)


def parse(file, file_config, mapping_asset_class, mapping_us_situs):
    """
    Parse a Manual export file into the standard portfolio schema.
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
    price_errors = []
    yfinance_error = False
    fetched_prices = {}  # {ticker: price} for display

    # Convert Auto Calc to boolean
    df["Auto Calc"] = df["Auto Calc"].astype(str).str.strip().str.upper()
    auto_calc_mask = df["Auto Calc"] == "TRUE"
    auto_calc_rows = df[auto_calc_mask]

    if len(auto_calc_rows) > 0:
        if not YFINANCE_AVAILABLE:
            yfinance_error = True
        else:
            # Get unique tickers that need pricing
            tickers = auto_calc_rows["Ticker"].dropna().unique().tolist()
            prices, failed = fetch_stock_prices(tickers)
            price_errors = failed
            fetched_prices = {t: p for t, p in prices.items() if p is not None}

            # Calculate Balance (Local) = Units × Price
            for idx in auto_calc_rows.index:
                ticker = df.at[idx, "Ticker"]
                units = df.at[idx, "Units"]
                if pd.notna(ticker) and ticker in prices and prices[ticker] is not None:
                    price = prices[ticker]
                    # London Stock Exchange prices are in pence — convert to pounds
                    if str(ticker).upper().endswith(".L"):
                        price = price / 100
                        fetched_prices[ticker] = price  # store converted price
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

    # Attach metadata
    output.attrs["price_errors"] = price_errors
    output.attrs["yfinance_error"] = yfinance_error
    output.attrs["fetched_prices"] = fetched_prices

    return output
