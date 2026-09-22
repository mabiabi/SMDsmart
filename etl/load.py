# -*- coding: utf-8 -*-
"""
Load layer: one function per target table. Each function resolves the
surrogate keys it needs (via db.py's generic helpers) and writes to SQL
Server. Ordered per FK dependencies - see run_etl.py for the full sequence.
"""
import datetime
import logging
import pandas as pd

import db
import transform

logger = logging.getLogger("smdsmart_etl")


# --------------------------------------------------------------------------
# DATE DIMENSION (run once at the start of every batch; idempotent)
# --------------------------------------------------------------------------
def load_dim_date(engine, start_date=None, end_date=None):
    existing_count = pd.read_sql("SELECT COUNT(*) AS n FROM dw.DimDate", engine)["n"].iloc[0]
    if existing_count > 0:
        logger.info(f"dw.DimDate already populated ({existing_count} rows) - skipping")
        return
    start_date = start_date or datetime.date(2015, 1, 1)
    end_date = end_date or datetime.date(2035, 1, 1)
    dim = transform.build_dim_date(start_date, end_date)
    dim.to_sql("DimDate", engine, schema="dw", if_exists="append", index=False, chunksize=2000)
    logger.info(f"dw.DimDate: populated {len(dim)} rows ({start_date} to {end_date})")


# --------------------------------------------------------------------------
# EMPLOYEE / CUSTOMER (SCD Type 1)
# --------------------------------------------------------------------------
def load_dim_employee(engine, employees_df):
    from jalali import jalali_str_to_gregorian
    df = employees_df.rename(columns={"Full Name": "FullName", "Home Line": "HomeLine",
                                        "Hire Date (Jalali)": "HireDateJalali"})
    df["HireDate"] = df["HireDateJalali"].apply(lambda s: jalali_str_to_gregorian(str(s).strip()))
    update_cols = ["FullName", "Role", "HomeLine", "Shift", "HireDate"]
    result = db.upsert_scd1_dimension(engine, "dw", "DimEmployee", "EmployeeSK", "EmployeeID",
                                        df[["EmployeeID"] + update_cols], update_cols)
    return result[["EmployeeID", "EmployeeSK"]]


def load_dim_customer(engine, orders_df):
    dim = transform.transform_dim_customer(orders_df)
    update_cols = ["CustomerName", "CustomerType", "Address", "PhoneNumber",
                    "NationalID", "Email", "PostalCode", "EconomicCode"]
    result = db.upsert_scd1_dimension(engine, "dw", "DimCustomer", "CustomerSK", "CustomerID",
                                        dim, update_cols)
    return result[["CustomerID", "CustomerSK"]]


# --------------------------------------------------------------------------
# SMALL REFERENCE DIMENSIONS
# --------------------------------------------------------------------------
def load_dim_order_attributes(engine, orders_df):
    dim, order_attr_map = transform.transform_dim_order_attributes(orders_df)
    natural_cols = ["FactorType", "StencilBy", "HasBGA", "Has0402", "Has0201", "ComponentSourcing"]
    full = db.get_or_create_dim(engine, "dw", "DimOrderAttributes", "OrderAttributesSK", natural_cols, dim)
    full["_attr_tuple"] = list(zip(full["FactorType"], full["StencilBy"], full["HasBGA"],
                                     full["Has0402"], full["Has0201"], full["ComponentSourcing"]))
    order_attr_sk = order_attr_map.merge(full[["_attr_tuple", "OrderAttributesSK"]], on="_attr_tuple", how="left")
    return order_attr_sk[["Order ID", "OrderAttributesSK"]]


def load_dim_component(engine, feeder_log_df, placement_log_df):
    dim = transform.transform_dim_component(feeder_log_df, placement_log_df)
    full = db.get_or_create_dim(engine, "dw", "DimComponent", "ComponentSK",
                                  ["PartNumber", "ComponentType", "Package"], dim)
    return full[["PartNumber", "ComponentSK"]]


def load_dim_vendor(engine, purchase_df):
    dim = transform.transform_dim_vendor(purchase_df)
    full = db.get_or_create_dim(engine, "dw", "DimVendor", "VendorSK",
                                  ["VendorName", "VendorCategory"], dim)
    return full[["VendorName", "VendorCategory", "VendorSK"]]


def get_dim_line_map(engine):
    return pd.read_sql("SELECT LineID, LineSK FROM dw.DimLine", engine)


def get_dim_error_category_map(engine, error_log_df=None):
    if error_log_df is not None:
        cats = error_log_df[["ErrorCategory"]].drop_duplicates()
        db.get_or_create_dim(engine, "dw", "DimErrorCategory", "ErrorCategorySK",
                              ["ErrorCategory"], cats)
    return pd.read_sql("SELECT ErrorCategory, ErrorCategorySK FROM dw.DimErrorCategory", engine)


# --------------------------------------------------------------------------
# FACT: ORDER
# --------------------------------------------------------------------------
def load_fact_order_base(engine, orders_df, project_log_df, customer_sk_map, order_attr_sk_map):
    base = transform.transform_fact_order_base(orders_df, project_log_df)
    line_map = get_dim_line_map(engine)

    base = base.merge(customer_sk_map, on="CustomerID", how="left")
    base = base.merge(line_map, on="LineID", how="left")
    base = base.merge(order_attr_sk_map.rename(columns={"Order ID": "OrderID"}), on="OrderID", how="left")

    cols = ["OrderID", "CustomerSK", "LineSK", "OrderAttributesSK",
            "RegisteredDateKey", "JobStartDateKey", "JobEndDateKey",
            "AnnouncedDeliveryDateKey", "DeliveredDateKey",
            "BoardName", "BoardQty", "PadSMDTopQty", "PadSMDBottomQty",
            "PadTHDTopQty", "PadTHDBottomQty", "DistinctComponentCount",
            "ProducedGoodQty", "ProducedRejectQty", "TotalStoppageMinutes",
            "LeadTimeDays", "IsOnTime"]
    n_new = db.bulk_insert_new_only(engine, "dw", "FactOrder", "OrderID", base[cols])
    return n_new


def load_fact_order_invoice_update(engine, invoice_df):
    upd = transform.transform_fact_order_invoice_update(invoice_df)
    db.update_fact_order_invoice_fields(engine, upd)


def get_fact_order_sk_map(engine):
    return pd.read_sql("SELECT OrderID, OrderSK FROM dw.FactOrder", engine)


# --------------------------------------------------------------------------
# PRODUCTION FACTS
# --------------------------------------------------------------------------
def load_fact_error(engine, error_log_df, employee_sk_map, order_sk_map):
    fe = transform.transform_fact_error(error_log_df)
    line_map = get_dim_line_map(engine)
    cat_map = get_dim_error_category_map(engine, error_log_df)

    fe = fe.merge(line_map, on="LineID", how="left")
    fe = fe.merge(cat_map, on="ErrorCategory", how="left")
    fe = fe.merge(order_sk_map, on="OrderID", how="left")
    fe = fe.merge(employee_sk_map.rename(
        columns={"EmployeeID": "ResolvedByEmployeeID", "EmployeeSK": "ResolvedByEmployeeSK"}),
        on="ResolvedByEmployeeID", how="left")

    cols = ["ErrorLogID", "DateKey", "ErrorTime", "LineSK", "OrderSK",
            "ErrorCategorySK", "ResolvedByEmployeeSK", "DurationMinutes"]
    db.bulk_insert_new_only(engine, "dw", "FactError", "ErrorLogID", fe[cols])


def load_fact_feeder_event(engine, feeder_log_df, employee_sk_map, order_sk_map, component_sk_map):
    ff = transform.transform_fact_feeder_event(feeder_log_df)
    line_map = get_dim_line_map(engine)

    ff = ff.merge(line_map, on="LineID", how="left")
    ff = ff.merge(order_sk_map, on="OrderID", how="left")
    ff = ff.merge(component_sk_map.rename(columns={"PartNumber": "ComponentPartNumber"}),
                  on="ComponentPartNumber", how="left")
    ff = ff.merge(employee_sk_map.rename(
        columns={"EmployeeID": "LoadedByEmployeeID", "EmployeeSK": "LoadedByEmployeeSK"}),
        on="LoadedByEmployeeID", how="left")

    cols = ["FeederLogID", "DateKey", "LineSK", "OrderSK", "ComponentSK", "LoadedByEmployeeSK",
            "FeederSlotNo", "ComponentsLoadedQty", "ComponentsConsumedQty", "ComponentsRemainingQty"]
    db.bulk_insert_new_only(engine, "dw", "FactFeederEvent", "FeederLogID", ff[cols])


def load_placement_detail(engine, placement_log_df):
    pdd = transform.transform_placement_detail(placement_log_df)
    cols = ["PlacementLogID", "OrderID", "LineID", "BoardSerialNo", "ReferenceDesignator",
            "ComponentPartNumber", "FeederSlotNo", "PlacementX_mm", "PlacementY_mm",
            "HeadNo", "PlacementTimestamp", "Result", "NGReason"]
    db.bulk_insert_new_only(engine, "ods", "PlacementDetail", "PlacementLogID", pdd[cols])


def purge_old_placement_detail(engine, retention_days):
    """Housekeeping: raw placement detail grows fast at real full-population
    scale, so keep only a rolling window in SQL Server (older data belongs
    in NAS/cold-storage archive, not queried here). Runs every ETL cycle -
    cheap no-op once the table is under the retention window."""
    from sqlalchemy import text
    with engine.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM ods.PlacementDetail "
            "WHERE PlacementTimestamp < DATEADD(day, :neg_days, CAST(GETDATE() AS DATE))"),
            {"neg_days": -retention_days})
        logger.info(f"ods.PlacementDetail: purged rows older than {retention_days} days "
                    f"({result.rowcount} rows deleted)")


# --------------------------------------------------------------------------
# FINANCE / HR FACTS
# --------------------------------------------------------------------------
def load_fact_purchase(engine, purchase_df, order_sk_map, vendor_sk_map):
    fp = transform.transform_fact_purchase(purchase_df)
    vendor_lookup = vendor_sk_map.rename(columns={"VendorCategory": "Category"})
    fp = fp.merge(vendor_lookup, on=["VendorName", "Category"], how="left")
    fp = fp.merge(order_sk_map, on="OrderID", how="left")
    cols = ["PurchaseID", "DateKey", "VendorSK", "OrderSK", "Category",
            "Quantity", "UnitPrice", "TotalAmount", "PaymentStatus"]
    db.bulk_insert_new_only(engine, "dw", "FactPurchase", "PurchaseID", fp[cols])


def load_fact_payroll(engine, payroll_df, employee_sk_map):
    fp = transform.transform_fact_payroll(payroll_df)
    fp = fp.merge(employee_sk_map, on="EmployeeID", how="left")
    cols = ["PayrollID", "EmployeeSK", "PayPeriodJalali", "PaymentDateKey", "BaseSalary",
            "OvertimeHours", "OvertimePay", "Bonus", "GrossPay", "Deductions", "NetPay"]
    db.bulk_insert_new_only(engine, "dw", "FactPayroll", "PayrollID", fp[cols])


def load_fact_attendance(engine, attendance_df, employee_sk_map):
    fa = transform.transform_fact_attendance(attendance_df)
    fa = fa.merge(employee_sk_map, on="EmployeeID", how="left")
    cols = ["AttendanceID", "EmployeeSK", "DateKey", "HoursWorked", "Status"]
    db.bulk_insert_new_only(engine, "dw", "FactAttendance", "AttendanceID", fa[cols])


def load_fact_transaction(engine, transaction_df):
    ft = transform.transform_fact_transaction(transaction_df)
    ft = ft.rename(columns={"Type": "TransactionType"})
    load_cols = ["TransactionID", "DateKey", "TransactionType", "RelatedReferenceID",
                 "Amount", "Direction", "PaymentMethod"]
    db.bulk_insert_new_only(engine, "dw", "FactTransaction", "TransactionID", ft[load_cols])
