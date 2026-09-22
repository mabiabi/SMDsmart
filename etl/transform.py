# -*- coding: utf-8 -*-
"""
Transform layer: pure pandas logic, deliberately kept free of any database
dependency so it can be unit-tested with nothing but the source files.
Surrogate-key resolution (which needs the DB) happens in load.py.
"""
import hashlib
import datetime
import pandas as pd

from jalali import jalali_str_to_gregorian


# --------------------------------------------------------------------------
# SHARED HELPERS
# --------------------------------------------------------------------------
def to_datekey(gdate):
    """datetime.date -> INT YYYYMMDD, matching dw.DimDate.DateKey."""
    if pd.isna(gdate) or gdate is None:
        return None
    return int(gdate.strftime("%Y%m%d"))

def jalali_to_datekey(jalali_str):
    if not jalali_str or (isinstance(jalali_str, float) and pd.isna(jalali_str)) or str(jalali_str).strip() == "":
        return None
    return to_datekey(jalali_str_to_gregorian(str(jalali_str).strip()))

def _stable_random(key):
    """Same deterministic hash used by the Phase 0-2 data generator, so
    ComponentSourcing here matches exactly what's already baked into
    Purchase.xlsx / Project_Sale_Invoice.xlsx.
    NOTE FOR PRODUCTION: this is a demo-only shim. In real operations,
    whether a job is turnkey (SMDsmart sources parts) vs customer-furnished
    is known at order-intake time and should be captured as an explicit
    column on Project_Order.xlsx - not inferred after the fact. Add that
    column and replace this function with a direct read once available.
    """
    h = hashlib.md5(key.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF

def is_turnkey_order(order_id):
    return _stable_random(f"turnkey-{order_id}") < 0.10


PACKAGE_TOKENS = {"0201", "0402", "0603", "0805", "SOIC", "BGA", "QFN"}
TYPE_PREFIX_MAP = {"RES": "Resistor", "CAP": "Capacitor", "IC": "IC",
                    "DIO": "Diode/LED", "CONN": "Connector"}

def parse_component_attributes(part_number):
    """Derive Type/Package from the part-numbering convention used in the
    source files (e.g. 'RES-0402-10K' -> Resistor/0402). Falls back to
    'Unknown' for anything that doesn't match - keeps the ETL from crashing
    if new part-number formats show up."""
    tokens = str(part_number).split("-")
    ctype = TYPE_PREFIX_MAP.get(tokens[0], "Unknown")
    package = next((t for t in tokens if t in PACKAGE_TOKENS), None)
    if package is None:
        package = "THD" if ctype == "Connector" else "Unknown"
    return ctype, package


# --------------------------------------------------------------------------
# DIMENSIONS
# --------------------------------------------------------------------------
def transform_dim_customer(orders_df):
    cust_cols = ["CustomerID", "Customer Name/Organization", "Address", "Phone Number",
                 "National ID", "E-mail Address", "Postal Code", "Economic Code"]
    dim = orders_df[cust_cols].drop_duplicates(subset=["CustomerID"]).copy()
    dim["CustomerType"] = dim["Customer Name/Organization"].apply(
        lambda n: "Individual" if str(n).startswith(("آقای", "خانم")) else "Organization")
    dim = dim.rename(columns={
        "Customer Name/Organization": "CustomerName", "Phone Number": "PhoneNumber",
        "National ID": "NationalID", "E-mail Address": "Email",
        "Postal Code": "PostalCode", "Economic Code": "EconomicCode",
    })
    return dim[["CustomerID", "CustomerName", "CustomerType", "Address", "PhoneNumber",
                 "NationalID", "Email", "PostalCode", "EconomicCode"]]


def transform_dim_order_attributes(orders_df):
    df = orders_df.copy()
    df["HasBGA"] = df["Special Components"].str.contains("BGA", na=False).astype(int)
    df["Has0402"] = df["Special Components"].str.contains("0402", na=False).astype(int)
    df["Has0201"] = df["Special Components"].str.contains("0201", na=False).astype(int)
    df["ComponentSourcing"] = df["Order ID"].apply(
        lambda oid: "Turnkey" if is_turnkey_order(oid) else "Customer-Furnished")

    attr_cols = ["Factor Type", "Stencil By", "HasBGA", "Has0402", "Has0201", "ComponentSourcing"]
    dim = df[attr_cols].drop_duplicates().reset_index(drop=True).copy()
    dim = dim.rename(columns={"Factor Type": "FactorType", "Stencil By": "StencilBy"})

    # attach the natural-key tuple back onto the order rows for lookup in load.py
    df["_attr_tuple"] = list(zip(df["Factor Type"], df["Stencil By"], df["HasBGA"],
                                   df["Has0402"], df["Has0201"], df["ComponentSourcing"]))
    dim["_attr_tuple"] = list(zip(dim["FactorType"], dim["StencilBy"], dim["HasBGA"],
                                    dim["Has0402"], dim["Has0201"], dim["ComponentSourcing"]))
    return dim, df[["Order ID", "_attr_tuple"]]


def transform_dim_component(feeder_log_df, placement_log_df):
    parts = pd.concat([feeder_log_df["ComponentPartNumber"],
                        placement_log_df["ComponentPartNumber"]]).drop_duplicates()
    rows = []
    for p in parts:
        ctype, package = parse_component_attributes(p)
        rows.append({"PartNumber": p, "ComponentType": ctype, "Package": package})
    return pd.DataFrame(rows)


def transform_dim_vendor(purchase_df):
    dim = purchase_df[["VendorName", "Category"]].drop_duplicates().rename(
        columns={"Category": "VendorCategory"})
    return dim.reset_index(drop=True)


# --------------------------------------------------------------------------
# FACT: ORDER (accumulating snapshot) - built in two stages
# --------------------------------------------------------------------------
def transform_fact_order_base(orders_df, project_log_df):
    """Stage A: everything known once the order has a production job
    assigned (Project_Order.xlsx JOIN Project_Log.csv). Financial columns
    are left absent here and filled by transform_fact_order_invoice_update."""
    merged = orders_df.merge(project_log_df, left_on="Order ID", right_on="OrderID", how="inner")

    out = pd.DataFrame()
    out["OrderID"] = merged["Order ID"]
    out["CustomerID"] = merged["CustomerID"]
    out["LineID"] = merged["LineID"]
    out["_attr_tuple"] = list(zip(merged["Factor Type"], merged["Stencil By"],
                                    merged["Special Components"].str.contains("BGA", na=False).astype(int),
                                    merged["Special Components"].str.contains("0402", na=False).astype(int),
                                    merged["Special Components"].str.contains("0201", na=False).astype(int),
                                    merged["Order ID"].apply(
                                        lambda oid: "Turnkey" if is_turnkey_order(oid) else "Customer-Furnished")))

    out["RegisteredDateKey"] = merged["Order Registered Date"].apply(jalali_to_datekey)
    out["JobStartDateKey"] = merged["JobStartTimestamp"].str.split(" ").str[0].apply(jalali_to_datekey)
    out["JobEndDateKey"] = merged["JobEndTimestamp"].str.split(" ").str[0].apply(jalali_to_datekey)
    out["AnnouncedDeliveryDateKey"] = merged["Announced Delivery Date"].apply(jalali_to_datekey)
    out["DeliveredDateKey"] = merged["Delivered Date"].apply(jalali_to_datekey)

    out["BoardName"] = merged["Board Name"]
    out["BoardQty"] = merged["Board Qty"]
    out["PadSMDTopQty"] = merged["Pad SMD Top Qty"]
    out["PadSMDBottomQty"] = merged["Pad SMD Bottom Qty"]
    out["PadTHDTopQty"] = merged["Pad THD Top Qty"]
    out["PadTHDBottomQty"] = merged["Pad THD Bottom Qty"]
    out["DistinctComponentCount"] = merged["Distinct Component Count"]

    out["ProducedGoodQty"] = merged["ProducedGoodQty"]
    out["ProducedRejectQty"] = merged["ProducedRejectQty"]
    out["TotalStoppageMinutes"] = merged["TotalStoppageMinutes"]

    reg_greg = merged["Order Registered Date"].apply(lambda s: jalali_str_to_gregorian(str(s).strip()))
    ann_greg = merged["Announced Delivery Date"].apply(lambda s: jalali_str_to_gregorian(str(s).strip()))
    del_greg = merged["Delivered Date"].apply(
        lambda s: jalali_str_to_gregorian(str(s).strip()) if str(s).strip() not in ("", "nan") else None)

    out["LeadTimeDays"] = [(a - r).days for a, r in zip(ann_greg, reg_greg)]
    out["IsOnTime"] = [None if d is None else (d <= a) for d, a in zip(del_greg, ann_greg)]

    return out


def transform_fact_order_invoice_update(invoice_df):
    """Stage B: UPDATE-only columns, applied once invoicing has happened."""
    out = invoice_df.rename(columns={
        "SMD Montage Total (Toman)": "SMDMontageTotal",
        "THD Montage Total (Toman)": "THDMontageTotal",
        "Board Montage Total (Toman)": "BoardMontageTotal",
        "Stencil Total (Toman)": "StencilTotal",
        "Packaging Total (Toman)": "PackagingTotal",
        "Non-reel Counting Total (Toman)": "NonReelCountingTotal",
        "Line Stopping Total (Toman)": "LineStoppingTotal",
        "Component Cost Total (Toman)": "ComponentCostTotal",
        "Subtotal (Toman)": "InvoiceSubtotal",
        "VAT (Toman)": "VATAmount",
        "GrandTotal (Toman)": "InvoiceGrandTotal",
        "AmountPaid (Toman)": "AmountPaid",
    }).copy()
    out["InvoiceDateKey"] = out["InvoiceDate"].apply(jalali_to_datekey)
    keep = ["OrderID", "InvoiceDateKey", "SMDMontageTotal", "THDMontageTotal", "BoardMontageTotal",
            "StencilTotal", "PackagingTotal", "NonReelCountingTotal", "LineStoppingTotal",
            "ComponentCostTotal", "InvoiceSubtotal", "VATAmount", "InvoiceGrandTotal",
            "AmountPaid", "PaymentStatus"]
    return out[keep]


# --------------------------------------------------------------------------
# OTHER FACTS
# --------------------------------------------------------------------------
def transform_fact_error(error_log_df):
    out = error_log_df.copy()
    parts = out["ErrorTimestamp"].str.split(" ", n=1, expand=True)
    out["DateKey"] = parts[0].apply(jalali_to_datekey)
    out["ErrorTime"] = parts[1]
    out["OrderID"] = out["OrderID"].fillna("").replace("", None)
    return out.rename(columns={"ResolvedByOperatorID": "ResolvedByEmployeeID"})


def transform_fact_feeder_event(feeder_log_df):
    out = feeder_log_df.copy()
    out["DateKey"] = out["LoadedTimestamp"].str.split(" ").str[0].apply(jalali_to_datekey)
    return out.rename(columns={"LoadedByOperatorID": "LoadedByEmployeeID"})


def transform_placement_detail(placement_log_df):
    out = placement_log_df.copy()
    date_part = out["PlacementTimestamp"].str.split(" ").str[0]
    time_part = out["PlacementTimestamp"].str.split(" ").str[1]
    greg_date = date_part.apply(lambda s: jalali_str_to_gregorian(str(s).strip()))
    out["PlacementTimestamp"] = [
        datetime.datetime.combine(d, datetime.datetime.strptime(t, "%H:%M:%S").time())
        for d, t in zip(greg_date, time_part)
    ]
    return out


def transform_fact_purchase(purchase_df):
    out = purchase_df.rename(columns={
        "UnitPrice (Toman)": "UnitPrice", "TotalAmount (Toman)": "TotalAmount"})
    out["DateKey"] = out["PurchaseDate"].apply(jalali_to_datekey)
    out["OrderID"] = out["OrderID"].fillna("").replace("", None)
    return out


def transform_fact_payroll(payroll_df):
    out = payroll_df.rename(columns={
        "BaseSalary (Toman)": "BaseSalary", "OvertimePay (Toman)": "OvertimePay",
        "Bonus (Toman)": "Bonus", "GrossPay (Toman)": "GrossPay",
        "Deductions (Toman)": "Deductions", "NetPay (Toman)": "NetPay",
        "PayPeriod (Jalali YYYY/MM)": "PayPeriodJalali"})
    out["PaymentDateKey"] = out["PaymentDate"].apply(jalali_to_datekey)
    return out


def transform_fact_attendance(attendance_df):
    out = attendance_df.copy()
    out["DateKey"] = out["Date"].apply(jalali_to_datekey)
    return out


def transform_fact_transaction(transaction_df):
    out = transaction_df.rename(columns={"Amount (Toman)": "Amount"})
    out["DateKey"] = out["TransactionDate"].apply(jalali_to_datekey)
    return out


# --------------------------------------------------------------------------
# DATE DIMENSION BUILDER
# --------------------------------------------------------------------------
JALALI_MONTH_NAMES = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                       "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
PERSIAN_WEEKDAY_NAMES = {5: "شنبه", 6: "یکشنبه", 0: "دوشنبه", 1: "سه\u200cشنبه",
                          2: "چهارشنبه", 3: "پنجشنبه", 4: "جمعه"}

def build_dim_date(start_date, end_date):
    """Generate one row per calendar day in [start_date, end_date)."""
    from jalali import to_jalali_str
    rows = []
    d = start_date
    while d < end_date:
        jy, jm, jd = map(int, to_jalali_str(d).split("/"))
        wd = d.weekday()
        rows.append({
            "DateKey": to_datekey(d), "GregorianDate": d,
            "JalaliYear": jy, "JalaliMonth": jm, "JalaliDay": jd,
            "JalaliDateText": f"{jy:04d}/{jm:02d}/{jd:02d}",
            "JalaliMonthName": JALALI_MONTH_NAMES[jm - 1],
            "JalaliYearMonth": f"{jy:04d}/{jm:02d}",
            "JalaliQuarter": (jm - 1) // 3 + 1,
            "DayOfWeekName": PERSIAN_WEEKDAY_NAMES[wd],
            "IsWeekend": wd == 4,
            "IsWorkingDay": wd != 4,
        })
        d += datetime.timedelta(days=1)
    return pd.DataFrame(rows)
