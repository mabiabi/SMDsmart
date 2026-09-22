# SMDsmart Data Warehouse & Analytics — System Documentation

**Scope:** end-to-end data infrastructure covering order intake, production,
and finance for SMDsmart's PCB assembly operation — replacing manual Excel
reporting with a scheduled ETL, a SQL Server star-schema warehouse, and a
Power BI dashboard.

**Status as of this document:** ETL verified running end-to-end against a
test database (`run_etl.py` completes without error). Scheduling
configuration is provided, and execution-verified in a live Windows
environment. Power BI `.pbix` has been built.

---

## 1. Architecture

```text
NAS exports (11 files, daily) → Python ETL (scheduled) → SQL Server (dw/ods) → Power BI
```

[`Architecture.png`](../Architecture.png)

Full Python ETL structure: [`py_structure.drawio`](../etl/py_structure.drawio) (open in [diagrams.net](https://app.diagrams.net)).

[`py_structure.png`](../etl/py_structure.png)

- **Source**: 11 files land daily on the NAS — `Project_Order.xlsx`,
  `Project_Log.csv`, `Placement_Log.csv`, `Feeder_Log.csv`, `Error_Log.csv`,
  `Employee_Master.csv`, `Purchase.xlsx`, `Project_Sale_Invoice.xlsx`,
  `Payroll.xlsx`, `Attendance.xlsx`, `Transaction.xlsx`.
- **ETL** (`etl/` folder): Python + pandas + SQLAlchemy. Extract → transform
  → load, in dependency order, with per-branch error isolation (see §3).
- **Warehouse**: SQL Server, two schemas — `dw` (the star schema Power BI
  connects to: 8 dimensions, 7 facts) and `ods` (raw placement-level detail
  for drill-through only, not part of the reporting model).
- **BI layer**: Power BI Desktop, Import mode for `dw.*`, DirectQuery (or
  excluded) for `ods.PlacementDetail`.

Full entity-relationship detail: `smdsmart_dwh_erd.drawio` (open in
[diagrams.net](https://app.diagrams.net)) or [`SSMS_EDR.png`](../warehouse/SSMS_ERD.png) (source of truth).

## 2. Data dictionary — quick reference

| Layer | Object | Grain | Row count (current data) |
| --- | --- | --- | --- |
| Source | `Project_Order.xlsx` | 1 row per order | 370 |
| Source | `Project_Log.csv` | 1 row per order-job | 370 |
| Source | `Placement_Log.csv` | 1 row per component placement (sampled orders only) | 248,913 |
| Source | `Feeder_Log.csv` | 1 row per feeder-slot load event | 4,022 |
| Source | `Error_Log.csv` | 1 row per stoppage event | 220 |
| Source | `Employee_Master.csv` | 1 row per employee | 25 |
| Source | `Purchase.xlsx` | 1 row per purchase line | 275 |
| Source | `Project_Sale_Invoice.xlsx` | 1 row per order (= 1 invoice) | 370 |
| Source | `Payroll.xlsx` | 1 row per employee per pay period | 175 |
| Source | `Attendance.xlsx` | 1 row per employee per day | 3,744 |
| Source | `Transaction.xlsx` | 1 row per cash movement | 797 |
| DWH | `dw.FactOrder` | 1 row per order (accumulating snapshot) | 370 |
| DWH | `dw.FactError` / `FactFeederEvent` / `FactPurchase` / `FactPayroll` / `FactAttendance` / `FactTransaction` | see `dwh_schema.sql` | mirrors source |
| DWH | `ods.PlacementDetail` | 1 row per placement (sampled orders, rolling retention) | ≤248,913, purged after `PLACEMENT_DETAIL_RETENTION_DAYS` |

Full column-level structural reference (types, PK/FK): `dwh_schema.sql`
and `smdsmart_dwh_erd.drawio`. Full column-level **business** reference
(what each field means, valid values, source lineage): `Data_Dictionary.md`
— use that one when the question is "what does this field mean," not
"what type is it."

## 3. ETL runbook

### Running it

```bash
cd etl
run_etl.ps1
```

Logs: console + `etl/logs/etl_YYYYMMDD.log`.

### Reading the log / diagnosing a failure

The log is organized by the same 4 stages every time:

1. **Core order pipeline** — if this fails, the run halts entirely (logged as `CORE PIPELINE FAILED`) and nothing downstream is touched. Fix this first; everything else depends on it.
2. **Production detail** (Error/Feeder/Placement)
3. **Finance** (Purchase/Invoice)
4. **HR & Transactions** (Payroll/Attendance/Transaction)

Stages 2-4 are independent — one failing doesn't stop the others. The
final log block always lists `Succeeded: [...]` and, if anything failed,
`Failed branches: [...]`. **Exit code is non-zero if the core pipeline
crashed OR if any branch failed** — this is what the scheduler's alerting
depends on (see §4).

### Common failure causes, in order of likelihood

1. **Connection/auth issues** — see `etl/README.md` §6 Troubleshooting
   (Windows Auth setup, SSL certificate trust for ODBC Driver 18).
2. **A source file is missing or malformed** — the NAS export didn't land,
   or someone hand-edited a file and broke a column header. The traceback
   will show a `KeyError` or `FileNotFoundError` naming the exact file/column.
3. **A new value doesn't fit an existing dimension assumption** — e.g. a
   new `ErrorCategory` string that wasn't in the original seed list. This
   is handled gracefully (dimensions auto-insert new combinations) but
   worth a glance at the log to confirm it was intentional, not a typo
   upstream.

### Rerunning safely

The ETL is idempotent: dimensions upsert, append-only facts skip
already-loaded IDs, and `FactOrder` updates in place. **It's always safe
to just rerun it** — there's no need to manually clean up a partial run
before retrying.

## 4. First-time setup & scheduling

- **`setup.ps1`** — run this once per machine before the first ETL run.
  Checks Python is on PATH, installs `requirements.txt`, checks for an
  installed SQL Server ODBC driver (warns with a download link rather than
  silently installing anything itself), creates `.env` from `.env.example`
  **only if `.env` doesn't already exist** (never overwrites configured
  credentials), and creates the `logs/` folder.
- **`SMDsmart_ETL_Task.xml`** — importable Windows Task Scheduler
  definition (Task Scheduler → Action → Import Task…). Triggers daily at
  06:00, runs `run_etl.ps1`. Update the hardcoded path inside if the
  project folder ever moves from `C:\Users\Enigma\Desktop\SMDsmart_DWH\etl`.
- **`run_etl.ps1`** — wrapper script: sets the working directory correctly
  regardless of how Task Scheduler invokes it, logs to `etl/logs/wrapper_*.log`,
  and optionally sends an email alert on failure (`$EnableEmailAlert = $false`
  by default — flip to `$true` and fill in the SMTP settings once you have
  a mail account to send from).
- **None of `setup.ps1`, `run_etl.ps1`, or the Task Scheduler import was
  execution-tested in a live Windows environment** (no such environment
  was available while building them) — please do a manual test run before
  relying on the scheduled trigger.
- **Alternative**: SQL Server Agent job, type "Operating system (CmdExec)",
  same command — covered in `etl/README.md` §4 if you'd rather manage
  scheduling alongside the database instead of via Windows.

## 5. Known limitations & recommended next steps

Consolidated from every phase — nothing here is a hidden gap, all of it
was flagged as it came up during the build:

| Item | Where it matters | Recommendation |
| --- | --- | --- |
| `ComponentSourcing` (turnkey vs. customer-furnished) is inferred via a hash function, not read from source | `Purchase.xlsx` generation logic, ETL `transform.py` | Add a real "Component Sourcing" column to `Project_Order.xlsx` at intake; it's a business decision known upfront, not something to infer downstream |
| `FactOrder` date columns are day-grain, not timestamp-grain | Limits time-of-day production analysis | Add `JobStartTime`/`JobEndTime` columns if hourly-precision line analysis becomes a priority |
| `ods.PlacementDetail` only covers 15 sampled orders | Component-level defect root-cause is not company-wide | Acceptable for now (board-level defect rate is complete); at production the retention/archive strategy in `config.py` becomes essential, not optional |
| `DimCustomer` is SCD Type 1 (overwrite), not Type 2 (historized) | No historical point-in-time customer attributes | None of the current 4 target KPIs need this; revisit only if audit-grade address/contact history becomes a compliance requirement |
| CLV is historical (cumulative revenue), not predictive | Customer/CLV dashboard page | Revisit once 18-24+ months of order history accumulate — 6 months isn't enough to fit a reliable churn model |
| Salary bands and deduction rates in the Payroll data are illustrative | HR dashboard page | Replace with figures once Payroll data flows through instead of the dataset |

ETL unnessesary INSERT and UPDATE

| Section | Problem | Solution |
| --------- | --------- | ---------- |
| DimEmployee | Incorrect string comparison of None/NaN values causes false change detection. | Fix change detection logic by considering missing values and data types. |
| PlacementDetail | Inserting all rows and then deleting old ones repeatedly is inefficient. | Filter the input DataFrame to recent dates before insertion. |
| FactOrder | Unconditional update for all orders on every run. | Add real change detection and only update changed rows. |

## 6. Maintenance guide — common changes

**Adding a new KPI**: write the DAX measure, add it to `_Measures` in
Power BI, and add an entry to `KPI_Catalog_and_DAX_Measures.md` so the
catalog stays the single source of truth for what every measure means.

**Adding a new source column**: add it to `extract.py` (dtype coercion if
numeric), `transform.py` (any derived logic), and the relevant `dw` table
via an `ALTER TABLE` — then add it to `load.py`'s column list for that
table. Update `dwh_schema.sql` and the `.drawio` ERD to match so they
stay accurate as documentation.

**Adding a new source file / subject area**: follow the existing pattern —
one `extract_*()` function, one or more `transform_*()` functions, one or
more `load_*()` functions, wired into `run_etl.py` in dependency order
(does it need `order_sk_map` or `employee_sk_map`? load it after those
exist). Give it its own try/except branch in `run_etl.py` so a new,
less-trusted data source can't take down the whole pipeline.

**Changing the retention window for raw placement detail**: one setting —
`PLACEMENT_DETAIL_RETENTION_DAYS` in `etl/.env`. No code change needed.

**"SSL Provider: The certificate chain was issued by an authority that is
not trusted"** (common with ODBC Driver 18, which enforces strict cert
validation by default unlike Driver 17): set
`SQL_TRUST_SERVER_CERTIFICATE=true` in `.env` (already the default in
`.env.example`). This is fine for an internal network; for an
internet-facing production server, install a properly trusted certificate
instead and set this to `false`.

**"Login failed for user 'sa'" (or similar) when you're using Windows
Authentication:** make sure `.env` has `SQL_TRUSTED_CONNECTION=true` set
explicitly - if it's missing or misspelled, the ETL defaults to SQL
Authentication and tries to log in as `sa` with a blank password, which
will always fail. `SQL_USERNAME`/`SQL_PASSWORD` are ignored entirely when
trusted connection is on.

**"Data source name not found" / driver errors:** confirm the exact ODBC
driver name installed on the machine matches `SQL_DRIVER` in `.env`. Check
installed drivers with:

```powershell
Get-OdbcDriver | Where-Object {$_.Name -like "*SQL Server*"}
```

Common values: `ODBC Driver 17 for SQL Server`, `ODBC Driver 18 for SQL Server`.

**Named instance (e.g. `SQLSERVER\SQLEXPRESS`)**: put the full
`hostname\instance` string directly in `SQL_SERVER` - the connection
string builder (`config.py`) uses SQLAlchemy's `URL.create()`, which
escapes the backslash correctly, so no extra quoting is needed in `.env`.

## 7. File index

| File | Phase | Purpose |
| --- | --- | --- |
| `README.md` | — | Public-facing project overview (GitHub landing page) |
| `Project_Order.xlsx`, `Project_Log.csv`, `Feeder_Log.csv`, `Error_Log.csv`, `Placement_Log.csv`, `Employee_Master.csv` | 0-1 | source data (customer/order + production) |
| `Purchase.xlsx`, `Project_Sale_Invoice.xlsx`, `Payroll.xlsx`, `Attendance.xlsx`, `Transaction.xlsx` | 2 | source data (finance/HR) |
| `dwh_schema.sql` | 3 | Star schema DDL - run this first against a fresh database |
| `smdsmart_dwh_erd.drawio` | 3 | Full ERD, editable in diagrams.net |
| `smdsmart_etl.zip` (`etl/` folder) | 4 | Python ETL package - config, extract, transform, load, orchestrator |
| `KPI_Catalog_and_DAX_Measures.md` | 5 | KPI definitions + ready-to-paste DAX |
| `SMDsmart_Dashboard.pbix`, `SMDsmart_PowerBI_Theme.json` | 6 | 10-page dashboard + custom theme |
| `SMDsmart_ETL_Task.xml`, `run_etl.ps1`, `setup.ps1` | 7 | First-time setup + scheduling |
| `System_Documentation.md` | 7 | Master reference tying it all together (this document) |
| `Data_Dictionary.md` | 7 (added post-review) | Business-facing column definitions, valid values, source lineage |
| `.gitignore` | 7 (added post-review) | Excludes `.env`, `smtp_password.txt`, logs, `__pycache__` from version control |

## 8. Physical Schema Design: Key Decisions & Why

### The core pattern: FactOrder as an accumulating snapshot

Most fact tables are append-only (a row is written once and never touched again). FactOrder is deliberately different — it's an accumulating snapshot: one row per order, with six date-milestone columns (RegisteredDateKey → JobStartDateKey → JobEndDateKey → AnnouncedDeliveryDateKey → DeliveredDateKey → InvoiceDateKey) that get filled in as the order progresses, and the ETL genuinely UPDATEs the row rather than inserting a new one each time. This is the right pattern whenever a business process has a defined sequence of milestones and you want "where is this order right now" to always be a single, current row — as opposed to a transaction fact table (like FactTransaction), where every event really is immutable and append-only.

### Role-playing dimension: one DimDate, six relationships

Those six date columns on FactOrder all point at the same DimDate table — that's a role-playing dimension. The alternative (a separate DimRegisteredDate, DimDeliveredDate, etc.) would just be six physical copies of the same 7,300 rows, multiplying maintenance for zero benefit. One date table, many FK columns, each playing a different "role" — this is why DimDate has 7 relationship lines converging on it in the ERD.

### Junk dimension: DimOrderAttributes

FactorType, StencilBy, and the three special-component flags are all low-cardinality (≤64 possible combinations total) and almost never queried independently — they're always sliced together ("official orders with BGA components"). Bundling them into one small dimension instead of six separate flag columns on FactOrder keeps the fact table narrower and gives you one clean join instead of scattering booleans everywhere.

### Surrogate keys everywhere, business keys preserved

Every dimension has both an IDENTITY surrogate key (CustomerSK) and the original business key (CustomerID). The surrogate is what facts actually reference — it insulates the warehouse from anything happening upstream (an OrderID numbering scheme changing, a customer ID getting reissued) and is what makes SCD possible at all. The business key stays for traceability back to the source file and for the ETL's upsert lookups.

### INT vs BIGINT — a deliberate split

FactOrder, FactPurchase, FactPayroll use INT surrogate keys (fine into the billions, and these grow slowly — hundreds of rows a month). FactError, FactFeederEvent, FactAttendance, FactTransaction use BIGINT — these accumulate much faster (attendance alone is 25 employees × ~300 working days/year) and are exactly the tables that would eventually need the extra headroom. Small decision, but it's the kind of thing that's annoying to fix later if you guess wrong.

### DECIMAL(18,0), not DECIMAL(18,2)

Every Toman amount uses zero decimal places. Toman doesn't have a circulating subunit in practice — nobody invoices fractional Toman — so carrying two decimal places everywhere would just be wasted storage and a false precision. Worth revisiting only if you ever price in a currency that does use subunits.

### Nullable FKs model real optionality

FactError.OrderSK, FactFeederEvent.OrderSK, and FactPurchase.OrderSK are all nullable — because in reality, not every error is tied to a specific job (calibration checks), and not every purchase is for a specific order (consumables, equipment). Forcing these to be non-null would mean inventing a fake "no order" row in FactOrder, which is a common anti-pattern that just moves the null-handling problem around instead of solving it.

### Schema separation: dw vs ods

ods.PlacementDetail deliberately sits outside the star schema, with no enforced FK to FactOrder — on purpose. It's a drill-through/troubleshooting table, not a reporting table: at real full-population volume it needs independent purge/archive policy (the 90-day retention job in the ETL), and an enforced FK would fight against fast bulk deletes. The clustered columnstore index on it is the other half of that decision — it's built for large sequential scans, not point lookups.

### A gotcha we actually hit: BIT columns and pandas

Worth flagging since it bit us (pun intended) during the ETL build: SQL Server's BIT type round-trips through pyodbc/pandas inconsistently as bool vs int depending on the path data takes. The junk-dimension lookup logic depends on exact value matching, so I cast HasBGA/Has0402/Has0201 to int (0/1) everywhere rather than leaving them as Python bool — a small thing, but it's a real, silent-failure-prone trap in any SQL Server + pandas pipeline.

### The one real modeling debt: ComponentSourcing

It's inferred (via a hash function) rather than stored, because the source Project_Order.xlsx doesn't actually capture it. It's a genuine business fact known at order intake — it just isn't captured yet. This is the one place where the physical model is compensating for a gap in the source system rather than reflecting it, and it's worth fixing at the source before this schema goes into real production use.

## 9. File map

```text
config.py       - connection string & file paths from .env
jalali.py       - Gregorian <-> Jalali conversion (verified against Nowruz dates)
extract.py      - reads the 11 source files into typed DataFrames
transform.py    - all business logic (fully unit-testable, no DB needed)
db.py           - SQLAlchemy engine + generic upsert/get-or-create helpers
load.py         - one function per target table, wires transform -> db
run_etl.py      - orchestrator (this is what you schedule)
```
