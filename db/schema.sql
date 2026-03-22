-- =============================================================
-- 股票数据库表结构
-- 数据库: PostgreSQL
-- 数据来源: Tushare Pro
-- =============================================================


-- -------------------------------------------------------------
-- 1. 股票基本资料
--    来源: pro.stock_basic()
--    建议更新频率: 每日（收盘后）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code      VARCHAR(12)  NOT NULL,          -- TS代码，如 000001.SZ
    symbol       VARCHAR(8)   NOT NULL,           -- 股票代码，如 000001
    name         VARCHAR(20)  NOT NULL,           -- 股票名称
    area         VARCHAR(20),                     -- 地域
    industry     VARCHAR(30),                     -- 所属行业
    fullname     VARCHAR(80),                     -- 股票全称
    enname       VARCHAR(120),                    -- 英文全称
    cnspell      VARCHAR(30),                     -- 拼音缩写
    market       VARCHAR(10),                     -- 市场类型（主板/创业板/科创板等）
    exchange     VARCHAR(10),                     -- 交易所代码（SSE/SZSE）
    curr_type    VARCHAR(5),                      -- 交易货币
    list_status  CHAR(1),                         -- 上市状态: L上市 D退市 P暂停上市
    list_date    DATE,                            -- 上市日期
    delist_date  DATE,                            -- 退市日期
    is_hs        CHAR(1),                         -- 是否沪深港通标的: N/H/S
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code)
);


-- -------------------------------------------------------------
-- 2. 指数基本资料
--    来源: pro.index_basic()
--    建议更新频率: 不常变化，手动维护即可
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_basic (
    ts_code      VARCHAR(32)  NOT NULL,          -- 指数代码，如 000001.SH
    name         VARCHAR(50)  NOT NULL,           -- 指数简称
    market       VARCHAR(10),                     -- 交易所或市场（SSE/SZSE/SW等）
    publisher    VARCHAR(30),                     -- 发布方（中证/上交所等）
    index_type   VARCHAR(20),                     -- 指数风格
    category     VARCHAR(30),                     -- 指数类别
    base_date    DATE,                            -- 基期
    base_point   NUMERIC(14, 4),                  -- 基点
    list_date    DATE,                            -- 发布日期
    weight_rule  VARCHAR(100),                    -- 加权方式
    description  TEXT,                            -- 描述
    exp_date     DATE,                            -- 终止日期
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code)
);


-- -------------------------------------------------------------
-- 3. 个股日线行情（未复权）
--    来源: pro.daily()
--    字段: ts_code, trade_date, open, high, low, close,
--          pre_close, change, pct_chg, vol, amount
--    建议更新频率: 每个交易日收盘后
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_daily (
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票代码
    trade_date DATE         NOT NULL,            -- 交易日期

    -- 除权（未复权）价格
    open       NUMERIC(12, 4),                   -- 开盘价（元）
    high       NUMERIC(12, 4),                   -- 最高价（元）
    low        NUMERIC(12, 4),                   -- 最低价（元）
    close      NUMERIC(12, 4),                   -- 收盘价（元）
    pre_close  NUMERIC(12, 4),                   -- 昨收价（元）
    change     NUMERIC(12, 4),                   -- 涨跌额（元）
    pct_chg    NUMERIC(12, 4),                   -- 涨跌幅（%，未复权；北交所新股首日可超 10000%）

    -- 前复权价格（以当前价为基准，向历史调整；适合技术分析/画图）
    open_qfq   NUMERIC(12, 4),                   -- 前复权开盘价
    high_qfq   NUMERIC(12, 4),                   -- 前复权最高价
    low_qfq    NUMERIC(12, 4),                   -- 前复权最低价
    close_qfq  NUMERIC(12, 4),                   -- 前复权收盘价

    -- 后复权价格（以上市首日为基准，向当前调整；适合计算实际收益率）
    open_hfq   NUMERIC(12, 4),                   -- 后复权开盘价
    high_hfq   NUMERIC(12, 4),                   -- 后复权最高价
    low_hfq    NUMERIC(12, 4),                   -- 后复权最低价
    close_hfq  NUMERIC(12, 4),                   -- 后复权收盘价

    vol        NUMERIC(20, 2),                   -- 成交量（手）
    amount     NUMERIC(20, 4),                   -- 成交额（千元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_date
    ON stock_daily (trade_date);


-- -------------------------------------------------------------
-- 4. 个股每日指标（市值、PE、PB等）
--    来源: pro.daily_basic()
--    字段含市值、换手率、市盈率等基本面指标
--    建议与 stock_daily 同步更新
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_daily_basic (
    ts_code        VARCHAR(12)  NOT NULL,        -- 股票代码
    trade_date     DATE         NOT NULL,        -- 交易日期
    close          NUMERIC(12, 4),               -- 当日收盘价（元）
    turnover_rate  NUMERIC(10, 4),               -- 换手率（%）
    turnover_rate_f NUMERIC(10, 4),              -- 换手率（自由流通股，%）
    volume_ratio   NUMERIC(10, 4),               -- 量比
    pe             NUMERIC(14, 4),               -- 市盈率（总市值/净利润，亏损为空）
    pe_ttm         NUMERIC(14, 4),               -- 市盈率TTM
    pb             NUMERIC(14, 4),               -- 市净率（总市值/净资产）
    ps             NUMERIC(14, 4),               -- 市销率
    ps_ttm         NUMERIC(14, 4),               -- 市销率TTM
    dv_ratio       NUMERIC(10, 4),               -- 股息率（%）
    dv_ttm         NUMERIC(10, 4),               -- 股息率TTM
    total_share    NUMERIC(20, 4),               -- 总股本（万股）
    float_share    NUMERIC(20, 4),               -- 流通股本（万股）
    free_share     NUMERIC(20, 4),               -- 自由流通股本（万股）
    total_mv       NUMERIC(24, 4),               -- 总市值（万元）
    circ_mv        NUMERIC(24, 4),               -- 流通市值（万元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_basic_date
    ON stock_daily_basic (trade_date);


-- -------------------------------------------------------------
-- 5. 指数日线行情
--    来源: pro.index_daily()
--    字段同 stock_daily（无 adj 概念）
--    建议更新频率: 每个交易日收盘后
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_daily (
    ts_code    VARCHAR(32)  NOT NULL,            -- 指数代码
    trade_date DATE         NOT NULL,            -- 交易日期
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    pre_close  NUMERIC(12, 4),
    change     NUMERIC(12, 4),
    pct_chg    NUMERIC(8,  4),
    vol        NUMERIC(20, 2),                   -- 成交量（手）
    amount     NUMERIC(20, 4),                   -- 成交额（千元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_index_daily_date
    ON index_daily (trade_date);


-- -------------------------------------------------------------
-- 6. 分钟线行情（个股 + 指数共用）
--    来源: pro.stk_mins()
--    freq: 1min / 5min / 15min / 30min / 60min
--
--    设计说明：
--    采用5张独立表（每个频率一张），而非单表加 freq 列。
--    原因：
--      - 1min 数据量极大（~5000股 × 240条/日 × 250日 ≈ 3亿行/年），
--        独立表便于分区、清理和备份策略差异化管理。
--      - 不同频率的查询不互相干扰，索引更高效。
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kline_1min (
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票/指数代码
    trade_time TIMESTAMP    NOT NULL,            -- K线时间（收盘时刻）
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    vol        NUMERIC(20, 2),                   -- 成交量（手）
    amount     NUMERIC(20, 4),                   -- 成交额（元）
    PRIMARY KEY (ts_code, trade_time)
);
CREATE INDEX IF NOT EXISTS idx_kline_1min_time  ON kline_1min (trade_time);

CREATE TABLE IF NOT EXISTS kline_5min (
    ts_code    VARCHAR(12)  NOT NULL,
    trade_time TIMESTAMP    NOT NULL,
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    vol        NUMERIC(20, 2),
    amount     NUMERIC(20, 4),
    PRIMARY KEY (ts_code, trade_time)
);
CREATE INDEX IF NOT EXISTS idx_kline_5min_time  ON kline_5min (trade_time);

CREATE TABLE IF NOT EXISTS kline_15min (
    ts_code    VARCHAR(12)  NOT NULL,
    trade_time TIMESTAMP    NOT NULL,
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    vol        NUMERIC(20, 2),
    amount     NUMERIC(20, 4),
    PRIMARY KEY (ts_code, trade_time)
);
CREATE INDEX IF NOT EXISTS idx_kline_15min_time ON kline_15min (trade_time);

CREATE TABLE IF NOT EXISTS kline_30min (
    ts_code    VARCHAR(12)  NOT NULL,
    trade_time TIMESTAMP    NOT NULL,
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    vol        NUMERIC(20, 2),
    amount     NUMERIC(20, 4),
    PRIMARY KEY (ts_code, trade_time)
);
CREATE INDEX IF NOT EXISTS idx_kline_30min_time ON kline_30min (trade_time);

CREATE TABLE IF NOT EXISTS kline_60min (
    ts_code    VARCHAR(12)  NOT NULL,
    trade_time TIMESTAMP    NOT NULL,
    open       NUMERIC(12, 4),
    high       NUMERIC(12, 4),
    low        NUMERIC(12, 4),
    close      NUMERIC(12, 4),
    vol        NUMERIC(20, 2),
    amount     NUMERIC(20, 4),
    PRIMARY KEY (ts_code, trade_time)
);
CREATE INDEX IF NOT EXISTS idx_kline_60min_time ON kline_60min (trade_time);


-- -------------------------------------------------------------
-- 7. 个股新闻
--    来源: pro.stock_news()
--    字段: datetime, content, title, source, url, doc_id
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_news (
    doc_id     VARCHAR(64)  NOT NULL,            -- 新闻唯一编号（tushare doc_id）
    ts_code    VARCHAR(12)  NOT NULL,            -- 关联股票代码
    datetime   TIMESTAMP    NOT NULL,            -- 新闻发布时间
    title      TEXT         NOT NULL,            -- 新闻标题
    content    TEXT,                             -- 新闻正文
    source     VARCHAR(50),                      -- 来源媒体（新浪财经等）
    url        VARCHAR(500),                     -- 原文链接
    created_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (doc_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_news_ts_code  ON stock_news (ts_code);
CREATE INDEX IF NOT EXISTS idx_stock_news_datetime ON stock_news (datetime);


-- -------------------------------------------------------------
-- 8. 个股周线行情
--    来源: pro.stk_weekly_monthly(freq='week')
--    字段: ts_code, trade_date, end_date, open, high, low, close,
--          pre_close, change, pct_chg, vol, amount
--    建议更新频率: 每周收盘后（周五）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_weekly (
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票代码
    trade_date DATE         NOT NULL,            -- 本周最后一个交易日
    end_date   DATE,                             -- 计算截至日期
    open       NUMERIC(12, 4),                   -- 周开盘价（元）
    high       NUMERIC(12, 4),                   -- 周最高价（元）
    low        NUMERIC(12, 4),                   -- 周最低价（元）
    close      NUMERIC(12, 4),                   -- 周收盘价（元）
    pre_close  NUMERIC(12, 4),                   -- 上周收盘价（元）
    change     NUMERIC(12, 4),                   -- 周涨跌额（元）
    pct_chg    NUMERIC(12, 4),                   -- 周涨跌幅（%，未复权）
    vol        NUMERIC(20, 2),                   -- 周成交量（手）
    amount     NUMERIC(20, 4),                   -- 周成交额（千元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_weekly_date
    ON stock_weekly (trade_date);


-- -------------------------------------------------------------
-- 9. 个股月线行情
--    来源: pro.stk_weekly_monthly(freq='month')
--    字段同上
--    建议更新频率: 每月收盘后
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_monthly (
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票代码
    trade_date DATE         NOT NULL,            -- 本月最后一个交易日
    end_date   DATE,                             -- 计算截至日期
    open       NUMERIC(12, 4),                   -- 月开盘价（元）
    high       NUMERIC(12, 4),                   -- 月最高价（元）
    low        NUMERIC(12, 4),                   -- 月最低价（元）
    close      NUMERIC(12, 4),                   -- 月收盘价（元）
    pre_close  NUMERIC(12, 4),                   -- 上月收盘价（元）
    change     NUMERIC(12, 4),                   -- 月涨跌额（元）
    pct_chg    NUMERIC(12, 4),                   -- 月涨跌幅（%，未复权）
    vol        NUMERIC(20, 2),                   -- 月成交量（手）
    amount     NUMERIC(20, 4),                   -- 月成交额（千元）
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_monthly_date
    ON stock_monthly (trade_date);


-- -------------------------------------------------------------
-- 10. 券商每月金股（荐股）
--     来源: pro.broker_recommend(month='YYYYMM')
--     限量: 单次最大 1000 行（单月数据通常 200~400 行），可按月循环
--     建议更新频率: 每月月初（数据一般于 1日~3日 更新）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS broker_recommend (
    month      CHAR(6)      NOT NULL,            -- 月度，格式 YYYYMM
    broker     VARCHAR(30)  NOT NULL,            -- 券商名称
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票代码
    name       VARCHAR(20),                      -- 股票简称
    created_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (month, broker, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_broker_recommend_month
    ON broker_recommend (month);
CREATE INDEX IF NOT EXISTS idx_broker_recommend_ts_code
    ON broker_recommend (ts_code);


-- -------------------------------------------------------------
-- 11. 用户账号
--    无注册功能，由管理员通过 scripts/create_user.py 添加
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(32)  NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);


-- -------------------------------------------------------------
-- 11. 用户持仓股
--    每个用户独立维护，关联 stock_basic
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_portfolio (
    id         SERIAL    PRIMARY KEY,
    user_id    INT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ts_code    VARCHAR(12) NOT NULL REFERENCES stock_basic(ts_code),
    added_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_user_portfolio_user ON user_portfolio(user_id);
