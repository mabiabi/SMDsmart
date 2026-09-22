# -*- coding: utf-8 -*-
"""
Extract layer: reads every source file into pandas, with dtype coercion
handled here so downstream transform code can assume clean types.
All NaN/NaT values are converted to None for safe SQL parameter binding.
extraxt1.py in help.
"""
import pandas as pd

import config


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Replace pandas NaN/NaT with None so SQL Server receives NULL."""
    return df.where(pd.notnull(df), None)


def extract_orders():
    df = pd.read_excel(config.FILES["orders"], dtype=str)
    numeric_cols = [
        "Board Qty", "Pad SMD Top Qty", "Pad SMD Bottom Qty",
        "Pad THD Top Qty", "Pad THD Bottom Qty",
        "Distinct Component Count",
        "SMD Montage Price per Pad (Toman)", "THD Montage Price per Pad (Toman)",
        "Board Montage Price (Toman)", "Stencil Price (Toman)",
        "Anti-static Packaging Price (Toman)", "Non-reel Counting Price (Toman)",
        "Cost of Line Stopping (Toman)"
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_project_log():
    df = pd.read_csv(config.FILES["project_log"], dtype=str)
    df = df.assign(
        PlannedQty=lambda d: pd.to_numeric(d["PlannedQty"]),
        ProducedGoodQty=lambda d: pd.to_numeric(d["ProducedGoodQty"]),
        ProducedRejectQty=lambda d: pd.to_numeric(d["ProducedRejectQty"]),
        TotalStoppageMinutes=lambda d: pd.to_numeric(d["TotalStoppageMinutes"]),
    )
    return _clean_dataframe(df)


def extract_feeder_log():
    df = pd.read_csv(config.FILES["feeder_log"], dtype=str)
    for c in ["FeederSlotNo", "ComponentsLoadedQty", "ComponentsConsumedQty", "ComponentsRemainingQty"]:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_error_log():
    df = pd.read_csv(config.FILES["error_log"], dtype=str)
    df["DurationMinutes"] = pd.to_numeric(df["DurationMinutes"])
    return _clean_dataframe(df)


def extract_placement_log():
    df = pd.read_csv(config.FILES["placement_log"], dtype=str)
    for c in ["FeederSlotNo", "HeadNo"]:
        df[c] = pd.to_numeric(df[c])
    for c in ["PlacementX_mm", "PlacementY_mm"]:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_employees():
    df = pd.read_csv(config.FILES["employees"], dtype=str)
    return _clean_dataframe(df)


def extract_purchase():
    df = pd.read_excel(config.FILES["purchase"], dtype=str)
    for c in ["Quantity", "UnitPrice (Toman)", "TotalAmount (Toman)"]:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_invoice():
    df = pd.read_excel(config.FILES["invoice"], dtype=str)
    money_cols = [c for c in df.columns if "Toman" in c]
    for c in money_cols:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_payroll():
    df = pd.read_excel(config.FILES["payroll"], dtype=str)
    for c in [
        "BaseSalary (Toman)", "OvertimeHours", "OvertimePay (Toman)", "Bonus (Toman)",
        "GrossPay (Toman)", "Deductions (Toman)", "NetPay (Toman)"
    ]:
        df[c] = pd.to_numeric(df[c])
    return _clean_dataframe(df)


def extract_attendance():
    df = pd.read_excel(config.FILES["attendance"], dtype=str)
    df["HoursWorked"] = pd.to_numeric(df["HoursWorked"])
    return _clean_dataframe(df)


def extract_transaction():
    df = pd.read_excel(config.FILES["transaction"], dtype=str)
    df["Amount (Toman)"] = pd.to_numeric(df["Amount (Toman)"])
    return _clean_dataframe(df)