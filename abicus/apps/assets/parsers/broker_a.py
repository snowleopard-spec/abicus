"""
Parser for Broker A exports.
Reads the 'Aggregated Amounts' tab, filters to the most recent date,
and keeps only Cash and Position Values rows.
Handles both Excel (.xlsx/.xls) and CSV (.csv) files.
"""

import pandas as pd


def read_file(file, sheet_name=None):
    """Read a file as either Excel or CSV based on filename."""
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file, sheet_name=sheet_name)


def parse(file, file_config, mapping_asset_class, mapping_us_situs):
    """
    Parse a Broker A export file into the standard portfolio schema.
    """

    # --- 1. Read the relevant sheet ---
    df = read_file(file, sheet_name="Aggregated Amounts")

    # --- 2. Filter to most recent date ---
    dates = df["Date"].dropna().unique()
    latest_date = sorted(dates)[-1]
    df = df[df["Date"] == latest_date]

    # --- 3. Keep only Cash and Position Values ---
    df = df[df["Amount Type Name"].isin(["Cash", "Position Values"])].copy()

    # --- 4. Determine Asset Class ---
    asset_class_map = dict(
        zip(
            mapping_asset_class["Underlying Instrument Description"],
            mapping_asset_class["Asset Class"],
        )
    )

    def determine_asset_class(row):
        if row["Amount Type Name"] == "Cash":
            return "Cash"
        if row["Asset type"] == "Stock":
            return "Single Stock"
        desc = row["Underlying Instrument Description"]
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
        if row["Amount Type Name"] == "Cash":
            return "N"
        desc = row["Underlying Instrument Description"]
        mapped = us_situs_map.get(desc, "")
        if mapped and str(mapped).strip():
            return str(mapped).strip()
        return "UNMAPPED"

    df["US Situs Flag"] = df.apply(determine_us_situs, axis=1)

    # --- 6. Determine Asset Name ---
    def determine_asset_name(row):
        if row["Amount Type Name"] == "Cash":
            return str(row["Account Currency"]) + " Cash Balance"
        return row["Underlying Instrument Description"]

    df["Asset Name"] = df.apply(determine_asset_name, axis=1)

    # --- 7. Build the standard output ---
    output = pd.DataFrame(
        {
            "Asset Name": df["Asset Name"].values,
            "Asset Class": df["Asset Class"].values,
            "Currency": df["Account Currency"].values,
            "Institution": file_config["institution"],
            "Account Type": file_config["account_type"],
            "Jurisdiction": file_config["jurisdiction"],
            "Beneficiary": file_config["beneficiary"],
            "Balance (Local)": df["Amount Account Currency"].values,
            "Balance (USD)": None,
            "US Situs Flag": df["US Situs Flag"].values,
            "Tag": df["Booking Account ID"].values,
        }
    )

    output = output.reset_index(drop=True)
    return output
