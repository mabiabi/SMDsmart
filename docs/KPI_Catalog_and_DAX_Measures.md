# SMDsmart Power BI — KPI Catalog & DAX Measure Library

## 0. Semantic model setup

### 0.1 — Role-playing DimDate: only one relationship is "active"

`FactOrder` has six FK columns pointing at `DimDate` (Registered, JobStart, JobEnd,
AnnouncedDelivery, Delivered, Invoice). Power BI only lets ONE relationship
between two tables be active by default. **Set `RegisteredDateKey → DimDate`
as the active relationship** (most natural default — "when did this order
enter the pipeline"). Every measure that needs a *different* date role uses
`USERELATIONSHIP()` explicitly — you'll see this throughout the catalog below.

### 0.2 — Create a dedicated `_Measures` table

Don't attach measures to physical tables. Create one empty table (Home →
Enter Data → 0 rows) named `_Measures`, pin it to the top of the fields
list, and put every measure below into it. Keeps the model navigable once
you have 25+ measures.

### 0.3 — Grain limitations to know about (so results aren't misread)

- **`FactOrder` date columns are DAY-grain**, not timestamp-grain (Phase 4
  ETL stored `JobStartDateKey`/`JobEndDateKey`, not time-of-day). Line
  Utilization below is therefore built from `TotalStoppageMinutes` against
  a calendar-capacity model, not from exact run-time subtraction — it's a
  valid and standard approach, just worth knowing why.
- **Defect Rate is board-level** (`ProducedRejectQty` / `BoardQty` on
  `FactOrder`), covering all 370 orders. Component/placement-level defect
  root-cause is only available for the 15 sampled orders in
  `ods.PlacementDetail` — use that table for drill-through investigation,
  not for a company-wide defect KPI (it isn't a representative sample by
  volume, only by variety).
- **CLV here is historical** (cumulative revenue per customer), not
  predictive. A churn/retention-based predictive CLV needs 18-24+ months
  of history to fit reliably — six months isn't enough signal. Revisit
  once more history accumulates.

---

## 1. Order Fulfillment & Delivery

**Total Orders** — count of orders in the current filter context.

```dax
Total Orders = COUNTROWS(FactOrder)
```

**On-Time Delivery Rate** — of orders actually delivered, what % arrived on
or before the announced date. Excludes still-pending orders from the
denominator (they haven't had a chance to be late or on-time yet).

```dax
On-Time Delivery Rate =
VAR DeliveredOrders = CALCULATE(COUNTROWS(FactOrder), NOT ISBLANK(FactOrder[DeliveredDateKey]))
VAR OnTimeOrders = CALCULATE(COUNTROWS(FactOrder), FactOrder[IsOnTime] = TRUE())
RETURN DIVIDE(OnTimeOrders, DeliveredOrders)
```

**Average Promised Lead Time (days)** — what we told the customer to expect.

```dax
Avg Promised Lead Time = AVERAGE(FactOrder[LeadTimeDays])
```

**Average Actual Fulfillment Time (days)** — what actually happened
(Delivered − Registered). Needs both date roles active at once, hence the
double `USERELATIONSHIP`.

```dax
Avg Actual Fulfillment Time = 
AVERAGEX(
    FILTER(FactOrder, NOT ISBLANK(FactOrder[DeliveredDateKey])),
    DATEDIFF(
        RELATED(DimDate[GregorianDate]),   -- active relationship via FactOrder[RegisteredDateKey]
        LOOKUPVALUE(
            DimDate[GregorianDate],
            DimDate[DateKey],
            FactOrder[DeliveredDateKey]
        ),
        DAY
    )
)
```

> Simpler alternative if the above feels fragile in your model: add an
> `ActualFulfillmentDays` computed column back in the Phase 4 ETL
> (`transform_fact_order_base`), the same way `LeadTimeDays` was computed.
> Pushing simple date arithmetic upstream into the ETL is usually cleaner
> than juggling relationship paths in DAX — worth doing if this measure
> becomes central to a dashboard page.

**Orders In Progress (WIP)** — registered but not yet delivered.

```dax
Orders In Progress = CALCULATE(COUNTROWS(FactOrder), ISBLANK(FactOrder[DeliveredDateKey]))
```

**Late Orders Count** -

```dax
Late Orders = CALCULATE(COUNTROWS(FactOrder), FactOrder[IsOnTime] = FALSE())
```

---

## 2. Quality & COPQ

**Defect Rate** — rejected boards as a share of all boards produced.

```dax
Defect Rate = DIVIDE(SUM(FactOrder[ProducedRejectQty]), SUM(FactOrder[BoardQty]))
```

**Total Rejected Boards** -

```dax
Rejected Boards = SUM(FactOrder[ProducedRejectQty])
```

**COPQ (Toman)** — line-stoppage cost (from BOM/parts discrepancies) plus
the production cost of every rejected board (approximated from that
order's own montage pricing, since we don't carry a separate standard-cost
table).

```dax
COPQ =
SUMX(
    FactOrder,
    FactOrder[LineStoppingTotal] +
    DIVIDE(
        FactOrder[SMDMontageTotal] + FactOrder[THDMontageTotal] + FactOrder[BoardMontageTotal],
        FactOrder[BoardQty], 0
    ) * FactOrder[ProducedRejectQty]
)
```

> This intentionally excludes the labor cost of non-BOM stoppages (feeder
> jams, vision faults, etc. in `FactError`) — we don't have an hourly labor
> rate to cost `DurationMinutes` against. If you want a fuller COPQ, add a
> `StandardLaborRatePerMinute` constant and extend this measure with
> `SUMX(FactError, FactError[DurationMinutes] * [rate])`.

**COPQ % of Revenue** -

```dax
COPQ % of Revenue = DIVIDE([COPQ], SUM(FactOrder[InvoiceGrandTotal]))
```

**Line Stoppage Incidents** -

```dax
Stoppage Incidents = COUNTROWS(FactError)
```

**Average Stoppage Duration (minutes)** -

```dax
Avg Stoppage Duration = AVERAGE(FactError[DurationMinutes])
```

---

## 3. Financial / Revenue

**Total Revenue** -

```dax
Total Revenue = SUM(FactOrder[InvoiceGrandTotal])
```

**Total Collected** -

```dax
Total Collected = SUM(FactOrder[AmountPaid])
```

**Outstanding Receivables (AR)** -

```dax
Outstanding AR = SUM(FactOrder[InvoiceGrandTotal]) - SUM(FactOrder[AmountPaid])
```

**Collection Rate %** -

```dax
Collection Rate = DIVIDE(SUM(FactOrder[AmountPaid]), SUM(FactOrder[InvoiceGrandTotal]))
```

**Average Order Value** -

```dax
Avg Order Value = AVERAGE(FactOrder[InvoiceGrandTotal])
```

---

## 4. Customer / CLV

**Customer Lifetime Value (Historical)** — cumulative revenue per customer;
put `DimCustomer[CustomerName]` on rows/axis to see it per customer.

```dax
CLV (Historical) = SUM(FactOrder[InvoiceGrandTotal])
```

**Active Customers** — distinct customers with at least one order in the
current filter context.

```dax
Active Customers = DISTINCTCOUNT(FactOrder[CustomerSK])
```

**Average Orders per Customer** -

```dax
Avg Orders per Customer = DIVIDE([Total Orders], [Active Customers])
```

**Top 10 Customer Revenue Concentration** — how reliant revenue is on your
biggest accounts (a classic job-shop risk metric).

```dax
Top 10 Customer Revenue % =
VAR Top10Revenue =
    SUMX(
        TOPN(10, VALUES(DimCustomer[CustomerSK]), CALCULATE(SUM(FactOrder[InvoiceGrandTotal]))),
        CALCULATE(SUM(FactOrder[InvoiceGrandTotal]))
    )
RETURN DIVIDE(Top10Revenue, [Total Revenue])
```

---

## 5. Production / Line Performance

**Line Utilization %** — actual busy time vs. theoretical available time,
built from `TotalStoppageMinutes` against a calendar-capacity model (see
§0.3 on why this approach was chosen over exact run-time subtraction).
Capacity assumption: 16h/day Sat–Wed, 8h Thursday, 0 Friday, × 2 lines
(matches the Phase 1 shift pattern you confirmed). Uses `WEEKDAY()` on the
Gregorian date rather than matching the Persian `DayOfWeekName` text —
string-matching localized text is fragile (invisible Unicode characters,
encoding differences) where a numeric weekday check is not.

```dax
Available Production Minutes =
SUMX(
    DimDate,
    VAR WD = WEEKDAY(DimDate[GregorianDate], 2)   -- 1=Monday ... 7=Sunday
    RETURN
        SWITCH(
            TRUE(),
            WD = 5, 0,           -- Friday: closed
            WD = 4, 8 * 60,      -- Thursday: single shift
            16 * 60              -- Sat-Wed: two shifts
        )
) * 2   -- 2 production lines

Line Utilization =
DIVIDE(
    [Available Production Minutes] - SUM(FactOrder[TotalStoppageMinutes]),
    [Available Production Minutes]
)
```

> Filter this to the date range in question (e.g. current month) — over the
> full 6-month window it's a broad average and less actionable.

**Total Good Boards Produced** -

```dax
Good Boards Produced = SUM(FactOrder[ProducedGoodQty])
```

**Turnkey Order Share** — % of orders where SMDsmart sourced components
(uses `DimOrderAttributes[ComponentSourcing]`).

```dax
Turnkey Order Share =
DIVIDE(
    CALCULATE(COUNTROWS(FactOrder), DimOrderAttributes[ComponentSourcing] = "Turnkey"),
    [Total Orders]
)
```

---

## 6. Procurement / Vendor

**Total Purchase Spend** -

```dax
Total Purchase Spend = SUM(FactPurchase[TotalAmount])
```

**Purchase Spend by Category** — put `FactPurchase[Category]` on an axis;
the measure itself is just the amount.

```dax
Purchase Spend = SUM(FactPurchase[TotalAmount])
```

**Vendor Payments Outstanding** -

```dax
Vendor Payments Outstanding =
CALCULATE(SUM(FactPurchase[TotalAmount]), FactPurchase[PaymentStatus] = "Pending")
```

---

## 7. HR / Payroll

**Total Payroll Cost** -

```dax
Total Payroll Cost = SUM(FactPayroll[NetPay])
```

**Average Overtime Hours (per employee per period)** -

```dax
Avg Overtime Hours = AVERAGE(FactPayroll[OvertimeHours])
```

**Attendance Rate %** -

```dax
Attendance Rate =
DIVIDE(
    CALCULATE(COUNTROWS(FactAttendance), FactAttendance[Status] = "Present"),
    COUNTROWS(FactAttendance)
)
```

**Labor Cost per Order** — a rough allocation (total payroll in period ÷
orders completed in that period). Directional, not precise activity-based
costing.

```dax
Labor Cost per Order = DIVIDE([Total Payroll Cost], [Total Orders])
```

---

## 8. Suggested 10-page dashboard mapping

| Page | Primary KPIs |
| --- | --- |
| 1. Executive Overview | Total Orders, Total Revenue, On-Time Delivery Rate, Defect Rate, COPQ |
| 2. Order Fulfillment | Lead time, WIP, Late Orders, On-Time trend |
| 3. Quality & COPQ | Defect Rate, COPQ, Stoppage incidents by category |
| 4. Financial Summary | Revenue, AR, Collection Rate, Average Order Value |
| 5. Customer / CLV | CLV by customer, Top 10 concentration, Active Customers |
| 6. Production & Line Performance | Line Utilization, Good Boards, Turnkey mix |
| 7. Procurement / Vendor | Purchase spend by category/vendor, outstanding payments |
| 8. HR & Payroll | Payroll cost trend, overtime, attendance rate |
| 9. Error & Root-Cause Drill-through | FactError by category/line, `ods.PlacementDetail` drill-through |
| 10. Data Quality / Admin | Row counts per table, last ETL run time, orders missing data |
