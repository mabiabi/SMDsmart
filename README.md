# SMDsmart Data Warehouse & Analytics Platform

**A complete, from-scratch data infrastructure for a 25-person PCB assembly job shop** — replacing manual Excel reporting with a scheduled Python ETL, a SQL Server star-schema warehouse, and a 10-page Power BI dashboard.

Built end-to-end: illustrative data generation → dimensional modeling → ETL → KPI/DAX design → dashboard spec → scheduling → documentation.

> **Note on the data:** data in this repo is illustrative. SMDsmart's real customer, order, and financial data never left the building — this project was built entirely on realistically-generated sample data specifically so the resulting pipeline, schema, and dashboard design could be shared and reviewed without any privacy or confidentiality concern.

---

## Why this exists

SMDsmart runs two SMD assembly lines (Samsung SM421 pick-and-place + reflow oven) serving 150+ customers, with every order, production run, and financial transaction previously tracked by hand across disconnected Excel files. This project replaces that with:

- A **single source of truth** — a SQL Server star schema that conforms customer, order, production, and finance data into one queryable model.
- **Zero ongoing analyst dependency** — a scheduled ETL that runs unattended, with idempotent reruns, per-branch failure isolation, and full logging.
- **Decision-ready KPIs** — on-time delivery, defect rate, COPQ (cost of poor quality), and customer lifetime value, computed consistently rather than recalculated by hand every month.

## Architecture

```text
NAS exports (11 files, daily)
        │
        ▼
Python ETL  ── scheduled daily (Task Scheduler) ──▶  logs + idempotent upserts
        │
        ▼
SQL Server  ── dw schema (star schema, 8 dims + 7 facts) ──▶  Power BI (Import)
            └─ ods schema (raw placement drill-through)  ──▶  Power BI (DirectQuery)
```

[`Architecture.png`](./Architecture.png)

Full Python ETL structure: [`py_structure.drawio`](./etl/py_structure.drawio) (open in [diagrams.net](https://app.diagrams.net)).

[`py_structure.png`](./etl/py_structure.png)

Full entity-relationship diagram: [`smdsmart_dwh_erd.drawio`](./warehouse/smdsmart_dwh_erd.drawio)
(open in [diagrams.net](https://app.diagrams.net)).

[`SSMS_ERD.png`](./warehouse/SSMS_ERD.png)

## What's in this repo

| Area | Highlights |
| --- | --- |
| **data** | operating history — 151 customers, 370 orders, 249K component placements, full payroll/attendance/transaction ledgers — with a verified Jalali↔Gregorian calendar converter |
| **Data warehouse** | Star schema: `FactOrder` as an accumulating snapshot, a role-playing `DimDate` shared across 6 date roles, a junk dimension for low-cardinality order flags, SCD Type 1 where history isn't needed |
| **ETL** | Python + pandas + SQLAlchemy. Dependency-ordered stages, per-branch error isolation, idempotent upserts, a rolling retention/purge policy for high-volume raw detail |
| **KPI & DAX layer** | 25 measures across 7 categories — fulfillment, quality/COPQ, financial, customer/CLV, production, procurement, HR |
| **Power BI** | Custom theme, full 10-page build spec (exact visuals, fields, and filters per page) |
| **Operations** | Task Scheduler automation, first-run setup script, full runbook and troubleshooting guide |

## Key design decisions worth knowing about

- **`FactOrder` is an accumulating snapshot**, not append-only — its
  milestone-date columns and financial fields get updated in place as an
  order progresses from registration through delivery through payment.
- **One `DimDate` table, six relationships** into `FactOrder` (a
  role-playing dimension) — avoids six redundant copies of the same
  calendar, at the cost of needing `USERELATIONSHIP()` in some DAX measures.
- **Raw per-placement machine data lives in a separate `ods` schema**,
  outside the star schema, with no enforced foreign key — it's a
  drill-through/troubleshooting table with its own retention policy, not
  a reporting table. (At real full-population volume this table would be
  tens of millions of rows for six months of data; the repo's sample
  covers a representative 15 orders at true per-placement grain, everything
  else at board-level summary — see `System_Documentation.md` for the
  full reasoning.)
- **Currency and calendar are Toman and Jalali throughout**, including in
  the warehouse and DAX layer — not bolted on as a display-only conversion.

## Getting started

```bash
# 1. Stand up the warehouse
sqlcmd -S <your-server> -i dwh_schema.sql

# 2. Configure and install the ETL
cd etl
./setup.ps1          # first-time setup: installs deps, checks ODBC driver, creates .env
# edit .env with real SQL Server connection details

# 3. Run it
./run_etl.ps1

# 4. Schedule it (Windows Task Scheduler)
#    Import SMDsmart_ETL_Task.xml, or see System_Documentation.md §4

# 5. Build the dashboard
#    Open Power BI Desktop, connect to your database.
```

## Repository structure

```text
.
├── data/                                Source files (11)
├── warehouse/
│   ├── dwh_schema.sql                   Star schema DDL
│   └── smdsmart_dwh_erd.drawio          Full ERD
├── etl/
│   ├── config.py, extract.py, transform.py, db.py, load.py, run_etl.py
│   ├── jalali.py                        Verified Gregorian ↔ Jalali conversion
│   ├── setup.ps1, run_etl.ps1           First-time setup + scheduled wrapper
│   └── requirements.txt, .env.example   ETL-specific operational docs                     
├── scheduling/
│   └── SMDsmart_ETL_Task.xml            Windows Task Scheduler definition
├── powerbi/
│   ├── SMDsmart_Dashboard.pbix
│   └── SMDsmart_PowerBI_Theme.json
└── docs/
    ├── System_Documentation.md          Master reference: architecture, runbook, limitations
    ├── Data_Dictionary.md               Business-facing column definitions
    └── KPI_Catalog_and_DAX_Measures.md  KPI definitions + ready-to-paste DAX
```

## Honest status

- ⚠️ Scheduling scripts (`setup.ps1`, `run_etl.ps1`, Task Scheduler import)
  were built without access to a Windows test environment — functionally
  sound, but do a manual test run before trusting the unattended trigger.

Full known-limitations list, with the reasoning behind each: see
`docs/System_Documentation.md` §5.

## Tech stack

`Python` · `pandas` · `SQLAlchemy` · `pyodbc` · `SQL Server` · `Power BI` · `DAX`
