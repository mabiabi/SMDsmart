# -*- coding: utf-8 -*-
"""
Database layer: SQLAlchemy engine + generic, reusable helpers for the
get-or-create / upsert patterns every dimension load needs.
db1.py in help. (raises error for NaN/NaT/None to None for SQL Server)

"""
import logging
import pandas as pd
from sqlalchemy import create_engine, text

import config

logger = logging.getLogger("smdsmart_etl")


def _sanitize_param(value):
    """
    Convert pandas/NumPy missing values (NaN, NaT, None) to Python None
    so that SQL Server receives proper NULL instead of an invalid float.
    """
    if value is None:
        return None
    try:
        # pd.isna catches float('nan'), None, pd.NaT, numpy.nan, etc.
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        # For unusual types where pd.isna might fail, keep original value
        pass
    return value


def get_engine():
    return create_engine(config.get_connection_string(), fast_executemany=True)


def upsert_scd1_dimension(engine, schema, table, sk_col, natural_key_col, df, update_cols):
    """
    For dimensions with a SINGLE natural key column and SCD Type 1 semantics
    (overwrite changed attributes): DimCustomer, DimEmployee.

    Returns df with an added sk_col mapping every input row to its surrogate key.
    """
    existing = pd.read_sql(f"SELECT {sk_col}, {natural_key_col}, {', '.join(update_cols)} "
                            f"FROM {schema}.{table}", engine)

    merged = df.merge(existing[[natural_key_col, sk_col]], on=natural_key_col, how="left")
    new_rows = merged[merged[sk_col].isna()].drop(columns=[sk_col])

    if len(new_rows):
        new_rows[[natural_key_col] + update_cols].to_sql(
            table, engine, schema=schema, if_exists="append", index=False)
        logger.info(f"{schema}.{table}: inserted {len(new_rows)} new rows")

    # detect changed attributes on existing rows and update them
    to_check = merged[merged[sk_col].notna()].merge(
        existing, on=natural_key_col, suffixes=("", "_db"))
    changed_mask = False
    for col in update_cols:
        changed_mask = changed_mask | (to_check[col].astype(str) != to_check[f"{col}_db"].astype(str))
    changed = to_check[changed_mask] if hasattr(changed_mask, "any") and changed_mask.any() else to_check.iloc[0:0]

    if len(changed):
        with engine.begin() as conn:
            for _, row in changed.iterrows():
                set_clause = ", ".join(f"{c} = :{c}" for c in update_cols)
                params = {c: _sanitize_param(row[c]) for c in update_cols}
                params["sk"] = row[sk_col]   # surrogate key is always an integer, no missing value
                conn.execute(text(f"UPDATE {schema}.{table} SET {set_clause} "
                                   f"WHERE {sk_col} = :sk"), params)
        logger.info(f"{schema}.{table}: updated {len(changed)} changed rows (SCD1)")

    # re-select full mapping (existing + newly inserted)
    full = pd.read_sql(f"SELECT {sk_col}, {natural_key_col} FROM {schema}.{table}", engine)
    return df.merge(full, on=natural_key_col, how="left")


def get_or_create_dim(engine, schema, table, sk_col, natural_key_cols, dim_df):
    """
    For small reference/junk dimensions with (possibly composite) natural
    keys and NO update semantics (insert-only if the combo is new):
    DimOrderAttributes, DimComponent, DimVendor, DimLine, DimErrorCategory.

    dim_df must contain exactly the natural_key_cols (no surrogate key).
    Returns the full existing+new mapping (natural_key_cols + sk_col).
    """
    existing = pd.read_sql(f"SELECT {sk_col}, {', '.join(natural_key_cols)} "
                            f"FROM {schema}.{table}", engine)

    key_df = dim_df[natural_key_cols].drop_duplicates()
    merged = key_df.merge(existing, on=natural_key_cols, how="left")
    new_rows = merged[merged[sk_col].isna()][natural_key_cols]

    if len(new_rows):
        new_rows.to_sql(table, engine, schema=schema, if_exists="append", index=False)
        logger.info(f"{schema}.{table}: inserted {len(new_rows)} new combinations")

    full = pd.read_sql(f"SELECT {sk_col}, {', '.join(natural_key_cols)} FROM {schema}.{table}", engine)
    return full


def bulk_insert_new_only(engine, schema, table, id_col, df):
    """Append-only facts (Purchase/Payroll/Attendance/Transaction/Error/
    FeederEvent): insert rows whose business-key id_col isn't already
    loaded. Keeps re-runs idempotent without needing per-row diffing."""
    existing_ids = pd.read_sql(f"SELECT {id_col} FROM {schema}.{table}", engine)[id_col]
    new_df = df[~df[id_col].isin(existing_ids)]
    if len(new_df):
        new_df.to_sql(table, engine, schema=schema, if_exists="append", index=False, chunksize=1000)
        logger.info(f"{schema}.{table}: inserted {len(new_df)} new rows "
                    f"({len(df) - len(new_df)} already present, skipped)")
    else:
        logger.info(f"{schema}.{table}: nothing new to insert")
    return len(new_df)


def update_fact_order_invoice_fields(engine, invoice_update_df):
    """FactOrder Stage B: UPDATE existing rows (matched by OrderID) with
    financial columns once invoicing has happened. Only touches orders
    whose financials actually changed or are still NULL, to keep re-runs cheap."""
    cols = [c for c in invoice_update_df.columns if c != "OrderID"]
    set_clause = ", ".join(f"{c} = :{c}" for c in cols)
    with engine.begin() as conn:
        for _, row in invoice_update_df.iterrows():
            params = {c: _sanitize_param(row[c]) for c in cols}
            params["OrderID"] = row["OrderID"]
            conn.execute(text(f"UPDATE dw.FactOrder SET {set_clause} WHERE OrderID = :OrderID"), params)
    logger.info(f"dw.FactOrder: updated invoice fields for {len(invoice_update_df)} orders")