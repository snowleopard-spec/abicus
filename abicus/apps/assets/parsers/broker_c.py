"""
Parser for Broker C exports.
Reads the file without headers (column titles are in row 26 area),
filters to 'Positions and Mark-to-Market Profit and Loss' / 'Summary' rows.
Handles both Excel (.xlsx/.xls) and CSV (.csv) files.

Note on cash balance treatment:
    Broker C reports cash (Forex) balances with both the native-currency
    quantity (column I / index 8) and the USD equivalent (column M / index 12).
    For Forex rows we therefore use:
        Balance (Local) = column 8   (native currency amount)
        Balance (USD)   = column 12  (USD equivalent, already provided)
    For non-Forex rows we keep the original behaviour:
        Balance (Local) = column 12  (in the instrument's own currency)
        Balance (USD)   = None       (populated downstream by fx_rates.convert_to_usd)
"""

import pandas as pd


def read_file_no_header(file):
    """Read a file without headers, as either Excel or CSV based on filename."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        # Broker C CSVs have inconsistent column counts across rows
        # (header sections have fewer columns than data rows).
        # Pre-define enough columns to fit the widest row.
        return pd.read_csv(
            file,
            header=None,
            names=range(30),
            on_bad_lines="skip",
        )
    else:
        return pd.read_excel(file, header=None)


def parse(file, file_config, mapping_asset_class, mapping_us_situs):
    """
    Parse a Broker C export file into the standard portfolio schema.
    """

    # --- 1. Read without headers (non-standard layout) ---
    df = read_file_no_header(file)

    # --- 2. Filter to the rows we care about ---
    df = df[
        (df[0] == "Positions and Mark-to-Market Profit and Loss")
        & (df[2] == "Summary")
    ].copy()

    # --- 3. Assign readable column names ---
    df = df.rename(
        columns={
            3: "Field Value",
            4: "Currency",
            5: "Symbol",
            6: "Description",
            8: "Local Quantity",   # Native-currency amount (used for Forex cash rows)
            12: "Market Value",    # USD value
        }
    )

    # --- 4. Determine Asset Class ---
    asset_class_map = dict(
        zip(
            mapping_asset_class["Underlying Instrument Description"],
            mapping_asset_class["Asset Class"],
        )
    )

    def determine_asset_class(row):
        if row["Field Value"] == "Forex":
            return "Cash"
        if row["Field Value"] == "Stocks":
            return "Single Stock"
        desc = str(row["Description"]).strip()
        mapped = asset_class_map.get(desc, "")
        if mapped and str(mapped).strip():
            return str(mapped).strip()
        return "UNMAPPED"

    df["Asset Class"] = df.apply(determine_asset_class, axis=1)

    # --- 5. Determine US Situs Flag ---
    us_situs_map = dict(
        zip(
            mapping_us_situs["Underlying Instrument Description"],
            mapping_us_situs["US Situs Flag"],
        )
    )

    def determine_us_situs(row):
        if row["Field Value"] == "Forex":
            return "N"
        desc = str(row["Description"]).strip()
        mapped = us_situs_map.get(desc, "")
        if mapped and str(mapped).strip():
            return str(mapped).strip()
        return "UNMAPPED"

    df["US Situs Flag"] = df.apply(determine_us_situs, axis=1)

    # --- 6. Determine Currency ---
    def determine_currency(row):
        if row["Field Value"] == "Forex":
            return str(row["Symbol"]).strip()
        return str(row["Currency"]).strip()

    df["Ccy"] = df.apply(determine_currency, axis=1)

    # --- 7. Determine Asset Name ---
    def determine_asset_name(row):
        if row["Field Value"] == "Forex":
            return str(row["Symbol"]).strip() + " Cash Balance"
        return str(row["Description"]).strip()

    df["Asset Name"] = df.apply(determine_asset_name, axis=1)

    # --- 8. Build the standard output ---
    # Forex rows: Balance (Local) = Local Quantity (col 8), Balance (USD) = Market Value (col 12)
    # Non-Forex rows: Balance (Local) = Market Value (col 12), Balance (USD) = None (filled downstream)
    is_forex = df["Field Value"] == "Forex"

    balance_local = pd.to_numeric(
        df["Local Quantity"].where(is_forex, df["Market Value"]),
        errors="coerce",
    )
    balance_usd = pd.to_numeric(
        df["Market Value"].where(is_forex, other=pd.NA),
        errors="coerce",
    )

    output = pd.DataFrame(
        {
            "Asset Name": df["Asset Name"].values,
            "Asset Class": df["Asset Class"].values,
            "Currency": df["Ccy"].values,
            "Institution": file_config["institution"],
            "Account Type": file_config["account_type"],
            "Jurisdiction": file_config["jurisdiction"],
            "Beneficiary": file_config["beneficiary"],
            "Balance (Local)": balance_local.values,
            "Balance (USD)": balance_usd.values,
            "US Situs Flag": df["US Situs Flag"].values,
            "Tag": file_config.get("tag", ""),
        }
    )

    output = output.reset_index(drop=True)
    return output
