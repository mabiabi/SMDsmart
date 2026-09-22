/* =============================================================================
   SMDsmart Data Warehouse - Star Schema DDL
   Target: SQL Server 2016 SP1+

   Layers:
     dw  = the star schema (dimensions + facts) that Power BI connects to
     ods = operational-detail store for drill-through only (raw placement log)
   (raw/stg landing-zone schemas are defined in Phase 4 - ETL)
   ============================================================================= */

CREATE DATABASE SMDsmart_DWH;
GO
USE SMDsmart_DWH;
GO

CREATE SCHEMA dw;
GO
CREATE SCHEMA ods;
GO

/* =============================================================================
   DIMENSIONS
   ============================================================================= */

-- Conformed Date dimension. Jalali is the business calendar; Gregorian kept
-- for interoperability with anything Gregorian-only.
CREATE TABLE dw.DimDate (
    DateKey            INT          NOT NULL PRIMARY KEY,   -- YYYYMMDD (Gregorian)
    GregorianDate       DATE         NOT NULL,
    JalaliYear          SMALLINT     NOT NULL,
    JalaliMonth         TINYINT      NOT NULL,
    JalaliDay           TINYINT      NOT NULL,
    JalaliDateText       CHAR(10)     NOT NULL,              -- 'YYYY/MM/DD'
    JalaliMonthName      NVARCHAR(20) NOT NULL,
    JalaliYearMonth      CHAR(7)      NOT NULL,              -- 'YYYY/MM' - handy for Payroll joins
    JalaliQuarter        TINYINT      NOT NULL,
    DayOfWeekName        NVARCHAR(20) NOT NULL,
    IsWeekend            BIT          NOT NULL,              -- Friday
    IsWorkingDay          BIT          NOT NULL
);
GO

CREATE TABLE dw.DimCustomer (
    CustomerSK      INT IDENTITY(1,1) PRIMARY KEY,
    CustomerID       VARCHAR(10)   NOT NULL UNIQUE,
    CustomerName      NVARCHAR(200) NOT NULL,
    CustomerType      VARCHAR(20)   NOT NULL,   -- Individual / Organization
    Address           NVARCHAR(300),
    PhoneNumber        VARCHAR(20),
    NationalID         VARCHAR(15),
    Email              VARCHAR(100),
    PostalCode         VARCHAR(15),
    EconomicCode       VARCHAR(15)
    -- SCD Type 1 (overwrite on change) - see design note above
);
GO

CREATE TABLE dw.DimEmployee (
    EmployeeSK    INT IDENTITY(1,1) PRIMARY KEY,
    EmployeeID     VARCHAR(10)  NOT NULL UNIQUE,
    FullName        NVARCHAR(100) NOT NULL,
    Role            NVARCHAR(50)  NOT NULL,
    HomeLine        VARCHAR(10)   NULL,
    Shift           VARCHAR(10)   NULL,
    HireDate        DATE          NULL
);
GO

CREATE TABLE dw.DimLine (
    LineSK        INT IDENTITY(1,1) PRIMARY KEY,
    LineID         VARCHAR(10)  NOT NULL UNIQUE,   -- LINE-A / LINE-B
    MachineModel    NVARCHAR(50),                   -- Samsung SM421
    OvenModel       NVARCHAR(50)
);
GO

-- Junk dimension: low-cardinality order flags bundled to keep FactOrder lean
CREATE TABLE dw.DimOrderAttributes (
    OrderAttributesSK  INT IDENTITY(1,1) PRIMARY KEY,
    FactorType          VARCHAR(15) NOT NULL,   -- Official / Non-official
    StencilBy           VARCHAR(10) NOT NULL,   -- Customer / Executor
    HasBGA              BIT NOT NULL,
    Has0402             BIT NOT NULL,
    Has0201             BIT NOT NULL,
    ComponentSourcing    VARCHAR(20) NOT NULL,   -- Turnkey / Customer-Furnished
    CONSTRAINT UQ_OrderAttributes UNIQUE (FactorType, StencilBy, HasBGA, Has0402, Has0201, ComponentSourcing)
);
GO

CREATE TABLE dw.DimVendor (
    VendorSK       INT IDENTITY(1,1) PRIMARY KEY,
    VendorName      NVARCHAR(200) NOT NULL,
    VendorCategory  VARCHAR(30)   NOT NULL   -- Component / Stencil / Consumables / Equipment
);
GO

CREATE TABLE dw.DimComponent (
    ComponentSK    INT IDENTITY(1,1) PRIMARY KEY,
    PartNumber      VARCHAR(50) NOT NULL UNIQUE,
    ComponentType    VARCHAR(30),               -- Resistor/Capacitor/IC/Diode-LED/Connector
    Package          VARCHAR(20)                -- 0402/0603/0201/SOIC/BGA/THD
);
GO

CREATE TABLE dw.DimErrorCategory (
    ErrorCategorySK  INT IDENTITY(1,1) PRIMARY KEY,
    ErrorCategory     NVARCHAR(50) NOT NULL UNIQUE,
    ErrorGroup        VARCHAR(30)               -- Machine Fault / Material / Calibration
);
GO

/* =============================================================================
   FACTS
   ============================================================================= */

-- FactOrder: accumulating snapshot, grain = one row per order (= one invoice)
CREATE TABLE dw.FactOrder (
    OrderSK                   INT IDENTITY(1,1) PRIMARY KEY,
    OrderID                    VARCHAR(20) NOT NULL UNIQUE,
    CustomerSK                 INT NOT NULL REFERENCES dw.DimCustomer(CustomerSK),
    LineSK                     INT NOT NULL REFERENCES dw.DimLine(LineSK),
    OrderAttributesSK           INT NOT NULL REFERENCES dw.DimOrderAttributes(OrderAttributesSK),

    -- milestone dates (accumulating snapshot pattern)
    RegisteredDateKey           INT NOT NULL REFERENCES dw.DimDate(DateKey),
    JobStartDateKey             INT NULL     REFERENCES dw.DimDate(DateKey),
    JobEndDateKey               INT NULL     REFERENCES dw.DimDate(DateKey),
    AnnouncedDeliveryDateKey     INT NOT NULL REFERENCES dw.DimDate(DateKey),
    DeliveredDateKey             INT NULL     REFERENCES dw.DimDate(DateKey),
    InvoiceDateKey               INT NULL     REFERENCES dw.DimDate(DateKey),

    -- order/board attributes
    BoardName                  NVARCHAR(100),
    BoardQty                   INT NOT NULL,
    PadSMDTopQty                INT, PadSMDBottomQty INT,
    PadTHDTopQty                INT, PadTHDBottomQty INT,
    DistinctComponentCount       INT,

    -- production outcomes
    ProducedGoodQty              INT,
    ProducedRejectQty            INT,
    TotalStoppageMinutes         INT,

    -- derived timing measures (populate at ETL/DAX time)
    LeadTimeDays                INT NULL,     -- AnnouncedDeliveryDate - RegisteredDate
    IsOnTime                    BIT NULL,     -- DeliveredDate <= AnnouncedDeliveryDate

    -- financials (Toman) - reconciled 1:1 with Project_Sale_Invoice.xlsx
    SMDMontageTotal              DECIMAL(18,0),
    THDMontageTotal              DECIMAL(18,0),
    BoardMontageTotal            DECIMAL(18,0),
    StencilTotal                 DECIMAL(18,0),
    PackagingTotal               DECIMAL(18,0),
    NonReelCountingTotal          DECIMAL(18,0),
    LineStoppingTotal             DECIMAL(18,0),
    ComponentCostTotal            DECIMAL(18,0),
    InvoiceSubtotal               DECIMAL(18,0),
    VATAmount                     DECIMAL(18,0),
    InvoiceGrandTotal             DECIMAL(18,0),
    AmountPaid                    DECIMAL(18,0),
    PaymentStatus                 VARCHAR(10)
);
GO
CREATE INDEX IX_FactOrder_Customer ON dw.FactOrder(CustomerSK);
CREATE INDEX IX_FactOrder_RegisteredDate ON dw.FactOrder(RegisteredDateKey);
CREATE INDEX IX_FactOrder_DeliveredDate ON dw.FactOrder(DeliveredDateKey);
GO

-- FactError: grain = one stoppage event
CREATE TABLE dw.FactError (
    ErrorSK                BIGINT IDENTITY(1,1) PRIMARY KEY,
    ErrorLogID              VARCHAR(20) NOT NULL UNIQUE,
    DateKey                 INT NOT NULL REFERENCES dw.DimDate(DateKey),
    ErrorTime                TIME(0) NULL,
    LineSK                   INT NOT NULL REFERENCES dw.DimLine(LineSK),
    OrderSK                  INT NULL REFERENCES dw.FactOrder(OrderSK),  -- nullable: general line errors
    ErrorCategorySK           INT NOT NULL REFERENCES dw.DimErrorCategory(ErrorCategorySK),
    ResolvedByEmployeeSK      INT NULL REFERENCES dw.DimEmployee(EmployeeSK),
    DurationMinutes           INT NOT NULL
);
GO
CREATE INDEX IX_FactError_Order ON dw.FactError(OrderSK);
CREATE INDEX IX_FactError_Category ON dw.FactError(ErrorCategorySK);
GO

-- FactFeederEvent: grain = one feeder-slot load event
CREATE TABLE dw.FactFeederEvent (
    FeederEventSK          BIGINT IDENTITY(1,1) PRIMARY KEY,
    FeederLogID             VARCHAR(20) NOT NULL UNIQUE,
    DateKey                  INT NOT NULL REFERENCES dw.DimDate(DateKey),
    LineSK                   INT NOT NULL REFERENCES dw.DimLine(LineSK),
    OrderSK                  INT NULL REFERENCES dw.FactOrder(OrderSK),
    ComponentSK              INT NOT NULL REFERENCES dw.DimComponent(ComponentSK),
    LoadedByEmployeeSK        INT NULL REFERENCES dw.DimEmployee(EmployeeSK),
    FeederSlotNo             INT,
    ComponentsLoadedQty       INT,
    ComponentsConsumedQty     INT,
    ComponentsRemainingQty    INT
);
GO

-- FactPurchase: grain = one purchase order line
CREATE TABLE dw.FactPurchase (
    PurchaseSK    INT IDENTITY(1,1) PRIMARY KEY,
    PurchaseID     VARCHAR(20) NOT NULL UNIQUE,
    DateKey         INT NOT NULL REFERENCES dw.DimDate(DateKey),
    VendorSK        INT NOT NULL REFERENCES dw.DimVendor(VendorSK),
    OrderSK         INT NULL REFERENCES dw.FactOrder(OrderSK),
    Category        VARCHAR(30),
    Quantity        INT,
    UnitPrice       DECIMAL(18,0),
    TotalAmount     DECIMAL(18,0),
    PaymentStatus   VARCHAR(10)
);
GO

-- FactPayroll: grain = one employee x one Jalali pay period
CREATE TABLE dw.FactPayroll (
    PayrollSK       INT IDENTITY(1,1) PRIMARY KEY,
    PayrollID        VARCHAR(20) NOT NULL UNIQUE,
    EmployeeSK        INT NOT NULL REFERENCES dw.DimEmployee(EmployeeSK),
    PayPeriodJalali    CHAR(7) NOT NULL,   -- 'YYYY/MM'
    PaymentDateKey     INT NULL REFERENCES dw.DimDate(DateKey),
    BaseSalary         DECIMAL(18,0),
    OvertimeHours      DECIMAL(6,1),
    OvertimePay        DECIMAL(18,0),
    Bonus              DECIMAL(18,0),
    GrossPay           DECIMAL(18,0),
    Deductions         DECIMAL(18,0),
    NetPay             DECIMAL(18,0)
);
GO

-- FactAttendance: grain = one employee x one calendar day
CREATE TABLE dw.FactAttendance (
    AttendanceSK   BIGINT IDENTITY(1,1) PRIMARY KEY,
    AttendanceID    VARCHAR(20) NOT NULL UNIQUE,
    EmployeeSK       INT NOT NULL REFERENCES dw.DimEmployee(EmployeeSK),
    DateKey          INT NOT NULL REFERENCES dw.DimDate(DateKey),
    HoursWorked      DECIMAL(5,2),
    Status           VARCHAR(10)     -- Present / Absent / Leave
);
GO
CREATE INDEX IX_FactAttendance_Employee ON dw.FactAttendance(EmployeeSK);
GO

-- FactTransaction: grain = one cash movement (customer/vendor/payroll/overhead)
CREATE TABLE dw.FactTransaction (
    TransactionSK       BIGINT IDENTITY(1,1) PRIMARY KEY,
    TransactionID        VARCHAR(20) NOT NULL UNIQUE,
    DateKey               INT NOT NULL REFERENCES dw.DimDate(DateKey),
    TransactionType        VARCHAR(30),    -- Customer Payment / Vendor Payment / Payroll Payment / Other Expense
    RelatedReferenceID      VARCHAR(20),    -- OrderID/InvoiceID/PurchaseID/PayrollID, nullable
    Amount                 DECIMAL(18,0),
    Direction               VARCHAR(10),    -- Income / Expense
    PaymentMethod            VARCHAR(20)
);
GO
CREATE INDEX IX_FactTransaction_Date ON dw.FactTransaction(DateKey);
GO

/* =============================================================================
   ODS: raw placement detail - drill-through only, NOT part of the Power BI
   import model (would be ~22.6M rows at real full-population scale).
   Columnstore is used because this table exists purely for occasional,
   large analytical scans (feeder/component root-cause), never for
   transactional lookups.
   ============================================================================= */
CREATE TABLE ods.PlacementDetail (
    PlacementLogID          VARCHAR(20) NOT NULL,
    OrderID                  VARCHAR(20) NOT NULL,
    LineID                   VARCHAR(10),
    BoardSerialNo             VARCHAR(30),
    ReferenceDesignator       VARCHAR(10),
    ComponentPartNumber       VARCHAR(50),
    FeederSlotNo              INT,
    PlacementX_mm             DECIMAL(6,2),
    PlacementY_mm             DECIMAL(6,2),
    HeadNo                    TINYINT,
    PlacementTimestamp         DATETIME2(0),
    Result                    VARCHAR(5),
    NGReason                  VARCHAR(50)
);
GO
CREATE CLUSTERED COLUMNSTORE INDEX CCI_PlacementDetail ON ods.PlacementDetail;
GO
CREATE NONCLUSTERED INDEX IX_PlacementDetail_Order ON ods.PlacementDetail(OrderID);
GO

/* =============================================================================
   Seed static dimension rows that don't come from source files
   ============================================================================= */
INSERT INTO dw.DimLine (LineID, MachineModel, OvenModel) VALUES
    ('LINE-A', 'Samsung SM421', 'Reflow Oven A'),
    ('LINE-B', 'Samsung SM421', 'Reflow Oven B');
GO

INSERT INTO dw.DimErrorCategory (ErrorCategory, ErrorGroup) VALUES
    ('Feeder Pickup Error', 'Machine Fault'),
    ('Vision System Fault', 'Machine Fault'),
    ('Nozzle Clog', 'Machine Fault'),
    ('Board Jam', 'Machine Fault'),
    ('BOM-Parts Mismatch', 'Material'),
    ('Calibration / Startup Check', 'Calibration');
GO
