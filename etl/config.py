# -*- coding: utf-8 -*-
"""
Configuration for the SMDsmart ETL. All environment-specific values come
from environment variables (or a .env file loaded via python-dotenv) so
that credentials never live in source control.

Copy .env.example to .env and fill in your real values before running.
"""
import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()

# --- SQL Server connection ---------------------------------------------
SQL_SERVER   = os.getenv("SQL_SERVER", "localhost")
SQL_DATABASE = os.getenv("SQL_DATABASE", "SMDsmart_DWH")
SQL_USERNAME = os.getenv("SQL_USERNAME", "sa")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
SQL_DRIVER   = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
SQL_TRUSTED_CONNECTION = os.getenv("SQL_TRUSTED_CONNECTION", "true").strip().lower() in ("true", "yes", "1")
# ODBC Driver 18 defaults to Encrypt=yes + strict certificate validation (Driver 17
# did not). Self-signed/internal CA certs on the SQL Server will fail with
# "SSL Provider: certificate chain was issued by an authority that is not
# trusted" unless this is set. Fine for an internal network; for anything
# internet-facing, install a proper trusted certificate instead and set this false.
SQL_TRUST_SERVER_CERTIFICATE = os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "true").strip().lower() in ("true", "yes", "1")

def get_connection_string():
    """Returns a SQLAlchemy URL object (not a hand-built string) so
    passwords/servers with special characters, and SERVER\\INSTANCE-style
    named instances, are escaped correctly. create_engine() accepts URL
    objects directly."""
    query = {"driver": SQL_DRIVER}
    if SQL_TRUST_SERVER_CERTIFICATE:
        query["TrustServerCertificate"] = "yes"
    if SQL_TRUSTED_CONNECTION:
        query["trusted_connection"] = "yes"
        return URL.create("mssql+pyodbc", host=SQL_SERVER, database=SQL_DATABASE, query=query)
    return URL.create("mssql+pyodbc", username=SQL_USERNAME, password=SQL_PASSWORD,
                        host=SQL_SERVER, database=SQL_DATABASE, query=query)

# --- Source file locations (the NAS mount on the analyst PC) ------------
NAS_ROOT = os.getenv("NAS_ROOT", r"C:\Users\Enigma\Desktop\SMDsmart_Project\data")

FILES = {
    "orders":      os.path.join(NAS_ROOT, "Project_Order.xlsx"),
    "project_log": os.path.join(NAS_ROOT, "Project_Log.csv"),
    "feeder_log":  os.path.join(NAS_ROOT, "Feeder_Log.csv"),
    "error_log":   os.path.join(NAS_ROOT, "Error_Log.csv"),
    "placement_log": os.path.join(NAS_ROOT, "Placement_Log.csv"),
    "employees":   os.path.join(NAS_ROOT, "Employee_Master.csv"),
    "purchase":    os.path.join(NAS_ROOT, "Purchase.xlsx"),
    "invoice":     os.path.join(NAS_ROOT, "Project_Sale_Invoice.xlsx"),
    "payroll":     os.path.join(NAS_ROOT, "Payroll.xlsx"),
    "attendance":  os.path.join(NAS_ROOT, "Attendance.xlsx"),
    "transaction": os.path.join(NAS_ROOT, "Transaction.xlsx"),
}

# --- Retention policy for the raw placement detail (ods schema) ---------
# At real full-population scale, raw per-placement data grows very fast.
# Keep only a rolling window in SQL Server; older rows should be archived
# to the NAS/cold storage by a separate housekeeping job (not built yet -
# flag this to the team before go-live if full-population logging starts).
PLACEMENT_DETAIL_RETENTION_DAYS = int(os.getenv("PLACEMENT_DETAIL_RETENTION_DAYS", "90"))

# --- Logging --------------------------------------------------------------

# Absolute path to the etl folder (where config.py is located)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Default log path: logs folder next to config.py
DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")

# Allow override with LOG_DIR environment variable (if needed)
LOG_DIR = os.getenv("LOG_DIR", DEFAULT_LOG_DIR)