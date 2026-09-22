# SMDsmart DWH — Data Dictionary

Column-level business reference. For physical types/keys/relationships,
see `dwh_schema.sql` and `smdsmart_dwh_erd.drawio` — this document answers
a different question: **what does each field mean, and where did it come
from.**

Legend: **PK** primary key · **FK** foreign key · **UK** business/unique key

---

## dw.DimDate

Conformed date dimension — every fact table's date columns reference this
one table (see System Documentation §1 on role-playing dimensions).

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| DateKey (PK) | Surrogate key, `YYYYMMDD` as integer (Gregorian) | e.g. `20260415` |
| GregorianDate | The calendar date | Standard date |
| JalaliYear/Month/Day | Same date, Shamsi calendar | Business's actual operating calendar |
| JalaliDateText | Human-readable Jalali date | `'YYYY/MM/DD'` |
| JalaliMonthName | Persian month name | فروردین … اسفند |
| JalaliYearMonth | Jalali year-month | `'YYYY/MM'` — used to join `FactPayroll` pay periods |
| JalaliQuarter | 1-4 | Derived from Jalali month |
| DayOfWeekName | Persian weekday name | شنبه … جمعه |
| IsWeekend | Friday flag | `1` only on Friday (single-day weekend) |
| IsWorkingDay | Inverse of IsWeekend | Does **not** distinguish Thursday's half-day — see Line Utilization DAX for how that's handled |

## dw.DimCustomer

SCD Type 1 (overwrite on change — see System Documentation §5 for why
Type 2 wasn't used).

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| CustomerSK (PK) | Surrogate key | |
| CustomerID (UK) | Business key from `Project_Order.xlsx` | `CUST-####` |
| CustomerName | Organization or individual name | Individual names prefixed آقای/خانم in source |
| CustomerType | Derived from name prefix | `Individual` \| `Organization` |
| Address, PhoneNumber, NationalID, Email, PostalCode, EconomicCode | Contact/identity fields as entered at order intake | NationalID uses Iran's real 10-digit checksum format |

## dw.DimEmployee

SCD Type 1.

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| EmployeeSK (PK) | Surrogate key | |
| EmployeeID (UK) | Business key | `EMP-###` |
| FullName, Role | Role determines shift pattern eligibility | Role ∈ {Production Operator, Line Supervisor, Quality Inspector, Maintenance Technician, Warehouse Staff, Order Intake / Sales, Finance / Accounting, Procurement, Management} |
| HomeLine | Which line this person is assigned to | `LINE-A` \| `LINE-B` \| blank (non-production roles) |
| Shift | Which shift they work | `Shift 1` \| `Shift 2` \| blank (non-production roles follow standard office hours) |
| HireDate | Jalali hire date, converted to Gregorian for storage | |

## dw.DimLine

Static, 2 rows (seeded directly in `dwh_schema.sql`, not loaded by the ETL).

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| LineSK (PK), LineID (UK) | `LINE-A` \| `LINE-B` | |
| MachineModel | Pick-and-place machine | Samsung SM421 (both lines) |
| OvenModel | Reflow oven | Generic descriptive name |

## dw.DimOrderAttributes

Junk dimension — bundles low-cardinality order flags to keep `FactOrder`
narrow (see System Documentation / earlier design discussion).

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| OrderAttributesSK (PK) | Surrogate key for the unique combination | |
| FactorType | Invoice type | `Official` (VAT-applicable) \| `Non-official` |
| StencilBy | Who supplies the stencil | `Customer` \| `Executor` (SMDsmart) |
| HasBGA, Has0402, Has0201 | Special/fine-pitch component flags | `0`/`1` |
| ComponentSourcing | Who sources the BOM components | `Turnkey` (SMDsmart buys parts) \| `Customer-Furnished` (~90% of orders — confirmed the norm) — **currently inferred, not captured at source; see Known Limitations in System Documentation** |

## dw.DimVendor

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| VendorSK (PK) | Surrogate key | |
| VendorName | Supplier name, from `Purchase.xlsx` | |
| VendorCategory | What this vendor supplies | `Component` \| `Stencil` \| `Consumables` \| `Equipment` |

## dw.DimComponent

Populated by parsing the `PartNumber` naming convention (e.g.
`RES-0402-10K` → Resistor/0402) — see `transform.parse_component_attributes()`.

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| ComponentSK (PK) | Surrogate key | |
| PartNumber (UK) | Component identifier as used in Feeder/Placement logs | |
| ComponentType | Parsed from part number prefix | Resistor \| Capacitor \| IC \| Diode/LED \| Connector \| Unknown (parser fallback) |
| Package | Physical package/footprint | 0201, 0402, 0603, SOIC, BGA, THD, etc. |

## dw.DimErrorCategory

Seeded with the 6 known categories in `dwh_schema.sql`; the ETL
auto-inserts any new category encountered (with blank `ErrorGroup`).

| Column | Definition | Valid values / notes |
| --- | --- | --- |
| ErrorCategorySK (PK) | Surrogate key | |
| ErrorCategory (UK) | Stoppage reason | Feeder Pickup Error, Vision System Fault, Nozzle Clog, Board Jam, BOM-Parts Mismatch, Calibration / Startup Check |
| ErrorGroup | Higher-level grouping | Machine Fault \| Material \| Calibration |

---

## dw.FactOrder

**Grain: one row per order.** Accumulating snapshot — columns get filled
in / updated as the order progresses (see System Documentation §1).

| Column | Definition | Notes |
| --- | --- | --- |
| OrderSK (PK), OrderID (UK) | | `ORD-YYYY-####` (Jalali year) |
| CustomerSK, LineSK, OrderAttributesSK (FK) | | |
| RegisteredDateKey | When the order was placed | Always populated |
| JobStartDateKey, JobEndDateKey | Production window | From `Project_Log.csv` |
| AnnouncedDeliveryDateKey | Promised delivery date | Always populated |
| DeliveredDateKey | Actual pickup/delivery date | **Nullable** — blank means still in production/pending |
| InvoiceDateKey | When invoiced | Nullable until Finance stage of ETL runs |
| BoardName, BoardQty | What was ordered | One board design per order (confirmed simple grain) |
| PadSMDTopQty/BottomQty, PadTHDTopQty/BottomQty | Pad counts per board | THD bottom-side is essentially unused in this business |
| DistinctComponentCount | Unique component types on the board | |
| ProducedGoodQty, ProducedRejectQty | Final QC outcome, board-level | Sums to `BoardQty` |
| TotalStoppageMinutes | Downtime attributed to this order's job | Sourced from `Project_Log.csv`, reconciled with `FactError` |
| LeadTimeDays | Promised lead time (Announced − Registered) | |
| IsOnTime | Delivered on/before announced date | **Nullable** — null means not yet delivered, not "unknown" |
| SMDMontageTotal … InvoiceGrandTotal, AmountPaid | Financial breakdown | All Toman, `DECIMAL(18,0)` — no subunit currency in circulating use |
| PaymentStatus | | `Paid` \| `Partial` \| `Unpaid` |

## dw.FactError

**Grain: one stoppage event.**

| Column | Definition | Notes |
| --- | --- | --- |
| ErrorSK (PK), ErrorLogID (UK) | | |
| DateKey, ErrorTime | When it happened | |
| LineSK | Which line | |
| OrderSK | Which order was running | **Nullable** — general/calibration errors aren't tied to a specific order |
| ErrorCategorySK | | |
| ResolvedByEmployeeSK | Who resolved it | Nullable |
| DurationMinutes | Stoppage length | Feeds COPQ and Line Utilization measures |

## dw.FactFeederEvent

**Grain: one feeder-slot load event.**

| Column | Definition | Notes |
| --- | --- | --- |
| FeederEventSK (PK), FeederLogID (UK) | | |
| DateKey, LineSK, OrderSK, ComponentSK, LoadedByEmployeeSK | | OrderSK nullable |
| FeederSlotNo | Physical slot number on the machine | |
| ComponentsLoadedQty/ConsumedQty/RemainingQty | Reel inventory tracking | Low `RemainingQty` = replenishment signal (see dashboard Page 9) |

## dw.FactPurchase

**Grain: one purchase line.**

| Column | Definition | Notes |
| --- | --- | --- |
| PurchaseSK (PK), PurchaseID (UK) | | |
| DateKey, VendorSK, OrderSK | | OrderSK populated only for `Category = 'Component (Order-linked)'` or `'Stencil'` purchases |
| Category | | Component (Order-linked) \| Stencil \| Consumables \| Equipment/Maintenance |
| Quantity, UnitPrice, TotalAmount | | Toman |
| PaymentStatus | | `Paid` \| `Pending` |

## dw.FactPayroll

**Grain: one employee × one Jalali pay period.**

| Column | Definition | Notes |
| --- | --- | --- |
| PayrollSK (PK), PayrollID (UK) | | |
| EmployeeSK | | |
| PayPeriodJalali | `'YYYY/MM'` | Joins to `DimDate[JalaliYearMonth]` if needed |
| PaymentDateKey | | |
| BaseSalary, OvertimeHours, OvertimePay, Bonus, GrossPay, Deductions, NetPay | | Overtime derived from actual `FactAttendance` hours, not estimated independently |

## dw.FactAttendance

**Grain: one employee × one calendar day.**

| Column | Definition | Notes |
| --- | --- | --- |
| AttendanceSK (PK), AttendanceID (UK) | | |
| EmployeeSK, DateKey | | |
| HoursWorked | | `0` when Status is Absent/Leave |
| Status | | `Present` \| `Absent` \| `Leave` |

## dw.FactTransaction

**Grain: one cash movement.** The company's full cash ledger — customer
payments, vendor payments, payroll payouts, and overhead in one table.

| Column | Definition | Notes |
| --- | --- | --- |
| TransactionSK (PK), TransactionID (UK) | | |
| DateKey | | |
| TransactionType | | Customer Payment \| Vendor Payment \| Payroll Payment \| Other Expense |
| RelatedReferenceID | Points back to an OrderID/InvoiceID/PurchaseID/PayrollID | **Not FK-enforced** — informational only, type varies by TransactionType |
| Amount | | Toman |
| Direction | | `Income` \| `Expense` |
| PaymentMethod | | Bank Transfer \| Cheque \| Cash |

## ods.PlacementDetail

**Grain: one component placement.** Drill-through only — not part of the
Power BI reporting model, no enforced FK, subject to rolling retention
purge (`PLACEMENT_DETAIL_RETENTION_DAYS`).

| Column | Definition | Notes |
| --- | --- | --- |
| PlacementLogID (PK) | | |
| OrderID | Informational link back to `FactOrder` | **Only 15 orders have data here** — a representative sample, not a complete population (see Phase 1 volume rationale in System Documentation) |
| LineID, BoardSerialNo, ReferenceDesignator, ComponentPartNumber, FeederSlotNo | | |
| PlacementX_mm, PlacementY_mm, HeadNo | Physical placement coordinates | For spatial defect-pattern analysis if ever needed |
| PlacementTimestamp | | |
| Result | | `OK` \| `NG` |
| NGReason | | Populated only when Result = NG: Pickup Error, Vision Recognition Fail, Placement Offset, Tombstoning |
