# -*- coding: utf-8 -*-
"""
SMDsmart ETL - main entry point.

Run manually with:  python run_etl.py
Schedule daily via Windows Task Scheduler (see run_etl.ps1 + the imported
SMDsmart_ETL_Task.xml) or SQL Server Agent - see the System Documentation
for exact setup steps.

Design: dependency-ordered stages. The core order pipeline (stages 1-9)
halts the whole run on failure, since everything else references it.
Independent branches (production detail, finance, HR) are each wrapped so
one failing doesn't block the others - you'll get a clear per-branch
summary at the end either way.

UPDATE (Phase 7): exit code now reflects partial-branch failures too, not
just a core-pipeline crash - the previous version returned exit code 0
even if e.g. the Finance branch failed, which meant a scheduled task's
failure alerting would silently miss it.
"""
import logging
import os
import sys
import datetime

import config
import extract
import load
import db

os.makedirs(config.LOG_DIR, exist_ok=True)
log_file = os.path.join(config.LOG_DIR, f"etl_{datetime.date.today():%Y%m%d}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("smdsmart_etl")


def run():
    started = datetime.datetime.now()
    logger.info("=" * 70)
    logger.info("SMDsmart ETL run starting")
    results = {"ok": [], "failed": []}

    engine = db.get_engine()

    # ---------------------------------------------------------------
    # CORE PIPELINE (halts run on failure - everything depends on this)
    # ---------------------------------------------------------------
    try:
        orders_df = extract.extract_orders()
        project_log_df = extract.extract_project_log()
        employees_df = extract.extract_employees()

        load.load_dim_date(engine)
        employee_sk_map = load.load_dim_employee(engine, employees_df)
        customer_sk_map = load.load_dim_customer(engine, orders_df)
        order_attr_sk_map = load.load_dim_order_attributes(engine, orders_df)
        n_new_orders = load.load_fact_order_base(engine, orders_df, project_log_df,
                                                   customer_sk_map, order_attr_sk_map)
        order_sk_map = load.get_fact_order_sk_map(engine)
        results["ok"].append(f"Core order pipeline ({n_new_orders} new orders)")
    except Exception:
        logger.exception("CORE PIPELINE FAILED - halting run, nothing downstream can be trusted")
        raise

    # ---------------------------------------------------------------
    # PRODUCTION DETAIL BRANCH
    # ---------------------------------------------------------------
    try:
        error_log_df = extract.extract_error_log()
        feeder_log_df = extract.extract_feeder_log()
        placement_log_df = extract.extract_placement_log()

        load.load_fact_error(engine, error_log_df, employee_sk_map, order_sk_map)
        component_sk_map = load.load_dim_component(engine, feeder_log_df, placement_log_df)
        load.load_fact_feeder_event(engine, feeder_log_df, employee_sk_map, order_sk_map, component_sk_map)
        load.load_placement_detail(engine, placement_log_df)
        load.purge_old_placement_detail(engine, config.PLACEMENT_DETAIL_RETENTION_DAYS)
        results["ok"].append("Production detail (Error/Feeder/Placement)")
    except Exception:
        logger.exception("Production detail branch failed - core order data is still safe")
        results["failed"].append("Production detail (Error/Feeder/Placement)")

    # ---------------------------------------------------------------
    # FINANCE BRANCH
    # ---------------------------------------------------------------
    try:
        purchase_df = extract.extract_purchase()
        invoice_df = extract.extract_invoice()

        vendor_sk_map = load.load_dim_vendor(engine, purchase_df)
        load.load_fact_purchase(engine, purchase_df, order_sk_map, vendor_sk_map)
        load.load_fact_order_invoice_update(engine, invoice_df)
        results["ok"].append("Finance (Purchase/Invoice)")
    except Exception:
        logger.exception("Finance branch failed")
        results["failed"].append("Finance (Purchase/Invoice)")

    # ---------------------------------------------------------------
    # HR BRANCH
    # ---------------------------------------------------------------
    try:
        payroll_df = extract.extract_payroll()
        attendance_df = extract.extract_attendance()
        transaction_df = extract.extract_transaction()

        load.load_fact_payroll(engine, payroll_df, employee_sk_map)
        load.load_fact_attendance(engine, attendance_df, employee_sk_map)
        load.load_fact_transaction(engine, transaction_df)
        results["ok"].append("HR & Transactions (Payroll/Attendance/Transaction)")
    except Exception:
        logger.exception("HR/Transaction branch failed")
        results["failed"].append("HR & Transactions (Payroll/Attendance/Transaction)")

    # ---------------------------------------------------------------
    elapsed = (datetime.datetime.now() - started).total_seconds()
    logger.info("-" * 70)
    logger.info(f"ETL run finished in {elapsed:.1f}s")
    logger.info(f"Succeeded: {results['ok']}")
    if results["failed"]:
        logger.error(f"Failed branches (see log above for details): {results['failed']}")
    logger.info("=" * 70)
    return results


if __name__ == "__main__":
    run_results = run()
    if run_results["failed"]:
        sys.exit(1)   # any branch failure -> non-zero exit, so schedulers/alerts catch it
    sys.exit(0)
