-- ============================================================
-- 无人售货机零售数据仓库 · 结构定义（SQLite 方言）
-- 分层：DWD（明细） -> DIM（维度） -> FACT（事实） -> ADS（应用）
-- ============================================================

DROP TABLE IF EXISTS dwd_order;
CREATE TABLE dwd_order (
    order_id           TEXT PRIMARY KEY,   -- 订单ID
    created_ts         TEXT NOT NULL,      -- 下单时间
    order_date         TEXT NOT NULL,      -- 下单日期 YYYY-MM-DD
    customer_id        TEXT,               -- 客户ID
    mobile_masked      TEXT,               -- 手机号（脱敏）
    total_price        REAL,               -- 订单总金额
    pay_price          REAL,               -- 实际支付金额
    discount_price     REAL,               -- 优惠金额
    status             TEXT,               -- WAIT / SUCCESS / FAIL
    source             TEXT,               -- ALIPAY_SHOPPING / WECHAT_SHOPPING
    order_type         TEXT,               -- SHOPPING / INIT
    boxid              TEXT,               -- 售货机ID
    payed_time         TEXT,               -- 支付时间
    order_num          TEXT,               -- 订单号
    external_order_num TEXT                -- 支付宝/微信订单号
);
CREATE INDEX idx_dwd_order_date     ON dwd_order(order_date);
CREATE INDEX idx_dwd_order_customer ON dwd_order(customer_id);
CREATE INDEX idx_dwd_order_box      ON dwd_order(boxid);

DROP TABLE IF EXISTS dwd_order_item;
CREATE TABLE dwd_order_item (
    detail_id        INTEGER PRIMARY KEY,  -- 明细自增ID
    created_ts       TEXT NOT NULL,        -- 下单时间
    order_date       TEXT NOT NULL,        -- 下单日期
    customer_id      TEXT,                 -- 客户ID
    boxid            TEXT,                 -- 售货机ID
    order_num        TEXT,                 -- 订单号
    status           TEXT,                 -- 订单状态
    order_type       TEXT,                 -- 订单类型
    product_name_raw TEXT,                 -- 商品名（清洗前）
    product_name     TEXT,                 -- 商品名（清洗后）
    amount           INTEGER,              -- 购买数量
    cost_price       REAL,                 -- 成本价
    sale_price       REAL,                 -- 销售价
    total_price      REAL,                 -- 商品总金额
    discount_price   REAL,                 -- 商品优惠金额
    pay_price        REAL,                 -- 商品实际支付金额
    profit           REAL                  -- 利润 = 实付 - 数量*成本价 - 优惠
);
CREATE INDEX idx_dwd_item_date  ON dwd_order_item(order_date);
CREATE INDEX idx_dwd_item_box   ON dwd_order_item(boxid, order_date);
CREATE INDEX idx_dwd_item_prod  ON dwd_order_item(product_name);

DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date (
    date_key      INTEGER PRIMARY KEY,     -- YYYYMMDD
    full_date     TEXT NOT NULL,
    year          INTEGER,
    month         INTEGER,
    day           INTEGER,
    quarter       INTEGER,
    weekday_num   INTEGER,                 -- 0=周一
    weekday_name  TEXT,
    is_weekend    INTEGER
);

-- 缓慢变化维 SCD2：商品价格随下单时间变化，保留历史版本
DROP TABLE IF EXISTS dim_product;
CREATE TABLE dim_product (
    product_key  INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    sale_price   REAL,
    valid_from   TEXT NOT NULL,
    valid_to     TEXT NOT NULL,            -- 9999-12-31 表示当前版本
    is_current   INTEGER
);
CREATE INDEX idx_dim_product_name ON dim_product(product_name);

DROP TABLE IF EXISTS dim_machine;
CREATE TABLE dim_machine (
    machine_key  INTEGER PRIMARY KEY,
    boxid        TEXT UNIQUE NOT NULL,
    name         TEXT,
    address      TEXT,
    city         TEXT,
    model_raw    TEXT,                     -- 原始型号
    model_norm   TEXT,                     -- 标准化型号
    status       TEXT,                     -- ONLINE / OFFLINE / BREAKDOWN / UNKNOWN
    serial_number TEXT,
    is_orphan    INTEGER                   -- 1 = 订单中出现但维表缺失
);

DROP TABLE IF EXISTS dim_customer;
CREATE TABLE dim_customer (
    customer_key    INTEGER PRIMARY KEY,
    customer_id     TEXT UNIQUE NOT NULL,
    mobile_masked   TEXT,
    first_order_date TEXT,
    last_order_date  TEXT,
    order_cnt        INTEGER,
    total_pay        REAL
);

DROP TABLE IF EXISTS fact_order_item;
CREATE TABLE fact_order_item (
    fact_key      INTEGER PRIMARY KEY,
    order_num     TEXT,
    order_date    TEXT,
    date_key      INTEGER,
    product_key   INTEGER,
    machine_key   INTEGER,
    customer_key  INTEGER,
    quantity      INTEGER,
    total_price   REAL,
    pay_price     REAL,
    discount_price REAL,
    cost_price    REAL,
    profit        REAL
);
CREATE INDEX idx_fact_date     ON fact_order_item(date_key);
CREATE INDEX idx_fact_machine  ON fact_order_item(machine_key);
CREATE INDEX idx_fact_product  ON fact_order_item(product_key);

-- ---------- ADS 应用层：对应实验2 的 4 个任务 ----------
DROP TABLE IF EXISTS ads_customer_rank;    -- 任务1 分组聚合客户订单
CREATE TABLE ads_customer_rank (
    customer_id   TEXT,
    mobile_masked TEXT,
    order_cnt     INTEGER,
    pay_amount    REAL
);

DROP TABLE IF EXISTS ads_product_sales;    -- 任务2 计算各商品销售金额
CREATE TABLE ads_product_sales (
    product_name TEXT,
    qty          INTEGER,
    sales_amount REAL
);

DROP TABLE IF EXISTS ads_machine_daily;    -- 任务3 统计各售货机日销售金额
CREATE TABLE ads_machine_daily (
    boxid        TEXT,
    sale_date    TEXT,
    sales_amount REAL
);

DROP TABLE IF EXISTS ads_machine_profit;   -- 任务4 整理各售货机情况
CREATE TABLE ads_machine_profit (
    boxid           TEXT,
    machine_name    TEXT,
    address         TEXT,
    profit          REAL,
    order_cnt       INTEGER,
    sales_amount    REAL,
    avg_order_value REAL
);
