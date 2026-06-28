from typing import Mapping


def compute_status(row: Mapping) -> str:
    if bool(row["excluded"]):
        return "Excluded"
    received = bool(row["invoice_received"])
    claimed = bool(row["claimed"])
    rebated = bool(row["rebated"])
    if rebated and not claimed:
        return "Check: rebated but not claimed"
    if rebated:
        return "Complete"
    if claimed:
        return "Claim submitted"
    if received:
        return "Ready to claim"
    return "Awaiting invoice"
