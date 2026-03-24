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
--    字段: ts_code, trade_date, open, high, low, close,
--          pre_close, change, pct_chg, vol, amount
--    建议更新频率: 每周收盘后（周五）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_weekly (
    ts_code    VARCHAR(12)  NOT NULL,            -- 股票代码
    trade_date DATE         NOT NULL,            -- 本周最后一个交易日
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
-- 11. 个股资金流向（东财 DC）
--     来源: pro.moneyflow_dc()
--     限量: 单次最大 6000 行，可按日期或股票代码循环提取
--     数据起始: 20230911，每日盘后更新
--     所需积分: 5000
--     建议更新频率: 每交易日收盘后
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS moneyflow_dc (
    trade_date         DATE         NOT NULL,           -- 交易日期
    ts_code            VARCHAR(12)  NOT NULL,           -- 股票代码
    name               VARCHAR(20),                     -- 股票名称
    pct_change         NUMERIC(10, 4),                  -- 涨跌幅（%）
    close              NUMERIC(12, 4),                  -- 最新价（元）
    net_amount         NUMERIC(20, 4),                  -- 主力净流入额（万元）
    net_amount_rate    NUMERIC(10, 4),                  -- 主力净流入占比（%）
    buy_elg_amount     NUMERIC(20, 4),                  -- 超大单净流入额（万元）
    buy_elg_amount_rate NUMERIC(10, 4),                 -- 超大单净流入占比（%）
    buy_lg_amount      NUMERIC(20, 4),                  -- 大单净流入额（万元）
    buy_lg_amount_rate NUMERIC(10, 4),                  -- 大单净流入占比（%）
    buy_md_amount      NUMERIC(20, 4),                  -- 中单净流入额（万元）
    buy_md_amount_rate NUMERIC(10, 4),                  -- 中单净流入占比（%）
    buy_sm_amount      NUMERIC(20, 4),                  -- 小单净流入额（万元）
    buy_sm_amount_rate NUMERIC(10, 4),                  -- 小单净流入占比（%）
    created_at         TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_moneyflow_dc_date    ON moneyflow_dc (trade_date);
CREATE INDEX IF NOT EXISTS idx_moneyflow_dc_ts_code ON moneyflow_dc (ts_code);


-- -------------------------------------------------------------
-- 12. 东财概念及行业板块资金流向（DC）
--     来源: pro.moneyflow_ind_dc()
--     限量: 单次最大 5000 行，可按日期和代码循环提取
--     每日盘后更新，所需积分: 6000
--     content_type: 行业 / 概念 / 地域
--     注意: 金额单位为元（非万元）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS moneyflow_ind_dc (
    trade_date              DATE         NOT NULL,       -- 交易日期
    ts_code                 VARCHAR(20)  NOT NULL,       -- DC板块代码
    content_type            VARCHAR(10),                 -- 数据类型（行业/概念/地域）
    name                    VARCHAR(40),                 -- 板块名称
    pct_change              NUMERIC(10, 4),              -- 板块涨跌幅（%）
    close                   NUMERIC(20, 4),              -- 板块最新指数
    net_amount              NUMERIC(24, 4),              -- 主力净流入额（元）
    net_amount_rate         NUMERIC(10, 4),              -- 主力净流入占比（%）
    buy_elg_amount          NUMERIC(24, 4),              -- 超大单净流入额（元）
    buy_elg_amount_rate     NUMERIC(10, 4),              -- 超大单净流入占比（%）
    buy_lg_amount           NUMERIC(24, 4),              -- 大单净流入额（元）
    buy_lg_amount_rate      NUMERIC(10, 4),              -- 大单净流入占比（%）
    buy_md_amount           NUMERIC(24, 4),              -- 中单净流入额（元）
    buy_md_amount_rate      NUMERIC(10, 4),              -- 中单净流入占比（%）
    buy_sm_amount           NUMERIC(24, 4),              -- 小单净流入额（元）
    buy_sm_amount_rate      NUMERIC(10, 4),              -- 小单净流入占比（%）
    buy_sm_amount_stock     VARCHAR(20),                 -- 主力净流入最大股
    rank                    INT,                         -- 序号
    created_at              TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_moneyflow_ind_dc_date         ON moneyflow_ind_dc (trade_date);
CREATE INDEX IF NOT EXISTS idx_moneyflow_ind_dc_ts_code      ON moneyflow_ind_dc (ts_code);
CREATE INDEX IF NOT EXISTS idx_moneyflow_ind_dc_content_type ON moneyflow_ind_dc (content_type);


-- -------------------------------------------------------------
-- 13. 大盘资金流向（东财 DC）
--     来源: pro.moneyflow_mkt_dc()
--     限量: 单次最大 3000 行，可按日期区间循环提取
--     每日盘后更新，所需积分: 6000（120积分可试用）
--     注意: 金额单位为元
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS moneyflow_mkt_dc (
    trade_date              DATE         NOT NULL,       -- 交易日期（主键）
    close_sh                NUMERIC(12, 4),              -- 上证收盘价（点）
    pct_change_sh           NUMERIC(10, 4),              -- 上证涨跌幅（%）
    close_sz                NUMERIC(12, 4),              -- 深证收盘价（点）
    pct_change_sz           NUMERIC(10, 4),              -- 深证涨跌幅（%）
    net_amount              NUMERIC(24, 4),              -- 主力净流入额（元）
    net_amount_rate         NUMERIC(10, 4),              -- 主力净流入占比（%）
    buy_elg_amount          NUMERIC(24, 4),              -- 超大单净流入额（元）
    buy_elg_amount_rate     NUMERIC(10, 4),              -- 超大单净流入占比（%）
    buy_lg_amount           NUMERIC(24, 4),              -- 大单净流入额（元）
    buy_lg_amount_rate      NUMERIC(10, 4),              -- 大单净流入占比（%）
    buy_md_amount           NUMERIC(24, 4),              -- 中单净流入额（元）
    buy_md_amount_rate      NUMERIC(10, 4),              -- 中单净流入占比（%）
    buy_sm_amount           NUMERIC(24, 4),              -- 小单净流入额（元）
    buy_sm_amount_rate      NUMERIC(10, 4),              -- 小单净流入占比（%）
    created_at              TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date)
);
CREATE INDEX IF NOT EXISTS idx_moneyflow_mkt_dc_date ON moneyflow_mkt_dc (trade_date);


-- -------------------------------------------------------------
-- 14. 用户账号
--    无注册功能，由管理员通过 scripts/create_user.py 添加
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(32)  NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    is_admin      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);

ALTER TABLE users
    -- 兼容老库升级：已有 users 表时补齐管理员标记字段。
    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;


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


-- -------------------------------------------------------------
-- 12. 申万行业分类
--    来源: pro.index_classify()
--    支持 SW2014 / SW2021 两个版本，L1/L2/L3 三级
--    建议更新频率: 不常变化，手动维护即可
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sw_industry_class (
    index_code    VARCHAR(12)  NOT NULL,          -- 指数代码，如 801010.SI
    industry_name VARCHAR(50)  NOT NULL,           -- 行业名称
    parent_code   VARCHAR(12)  NOT NULL DEFAULT '0', -- 父级代码（一级行业为 '0'）
    level         VARCHAR(4)   NOT NULL,           -- 行业层级：L1 / L2 / L3
    industry_code VARCHAR(10)  NOT NULL,           -- 行业代码，如 110000
    is_pub        VARCHAR(2)   NOT NULL DEFAULT '1', -- 是否发布了指数（'1'/'0'）
    src           VARCHAR(10)  NOT NULL,           -- 版本：SW2014 / SW2021
    updated_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, src)
);
CREATE INDEX IF NOT EXISTS idx_sw_industry_class_level  ON sw_industry_class(level, src);
CREATE INDEX IF NOT EXISTS idx_sw_industry_class_parent ON sw_industry_class(parent_code, src);


-- -------------------------------------------------------------
-- 13. 申万行业成分构成（分级）
--    来源: pro.index_member_all()
--    记录每只股票归属哪个三级行业，含历史变更记录
--    建议更新频率: 行业调整时（通常每季度或年度）手动更新
--
--    主键设计：(l3_code, ts_code, in_date)
--      - 同一股票历史上可多次进出同一 L3 行业
--      - in_date 不可为 NULL（API 实测总有值；极端情形填哨兵 1900-01-01）
--
--    关联关系：
--      l3_code → sw_industry_class.index_code (level='L3')
--      l2_code → sw_industry_class.index_code (level='L2')
--      l1_code → sw_industry_class.index_code (level='L1')
--      ts_code → stock_basic.ts_code
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sw_industry_member (
    l3_code    VARCHAR(12)  NOT NULL,          -- 三级行业指数代码，如 850531.SI
    l2_code    VARCHAR(12),                     -- 二级行业指数代码（冗余，方便查询）
    l1_code    VARCHAR(12),                     -- 一级行业指数代码（冗余，方便查询）
    ts_code    VARCHAR(12)  NOT NULL,           -- 成分股票代码，如 000506.SZ
    name       VARCHAR(20),                     -- 成分股票名称
    in_date    DATE         NOT NULL,           -- 纳入日期
    out_date   DATE,                            -- 剔除日期（NULL = 仍在成分中）
    is_new     VARCHAR(2)   NOT NULL DEFAULT 'Y', -- 是否最新成分 Y/N
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (l3_code, ts_code, in_date)
);
-- 按股票查询其行业归属（最常用）
CREATE INDEX IF NOT EXISTS idx_sw_ind_member_ts     ON sw_industry_member(ts_code);
-- 按一级 / 二级行业筛选成分
CREATE INDEX IF NOT EXISTS idx_sw_ind_member_l1     ON sw_industry_member(l1_code);
CREATE INDEX IF NOT EXISTS idx_sw_ind_member_l2     ON sw_industry_member(l2_code);
-- 快速取当前成分（is_new='Y'）
CREATE INDEX IF NOT EXISTS idx_sw_ind_member_is_new ON sw_industry_member(is_new, l3_code);


-- -------------------------------------------------------------
-- 14. 申万行业日线行情
--    来源: pro.sw_daily()
--    描述: 申万行业（L1/L2/L3）每日行情 + 估值 + 权重
--    默认为申万2021版，ts_code 与 sw_industry_class.index_code 对应
--    建议更新频率: 每个交易日收盘后（--date 模式，1次API=全行业）
--
--    关联关系：
--      ts_code → sw_industry_class.index_code
--
--    两种拉取策略：
--      日常更新: sw_daily(trade_date=...) → 1次API = 当日全行业（约439条）
--      历史回填: sw_daily(ts_code=..., start_date=...) → 按代码分页，推荐首次导入
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sw_industry_daily (
    ts_code      VARCHAR(12)  NOT NULL,            -- 申万行业指数代码，如 801010.SI
    trade_date   DATE         NOT NULL,            -- 交易日期
    name         VARCHAR(40),                      -- 指数名称（冗余，方便展示）
    open         NUMERIC(12, 4),                   -- 开盘点位
    high         NUMERIC(12, 4),                   -- 最高点位
    low          NUMERIC(12, 4),                   -- 最低点位
    close        NUMERIC(12, 4),                   -- 收盘点位
    change       NUMERIC(12, 4),                   -- 涨跌点位
    pct_change   NUMERIC(8, 4),                    -- 涨跌幅（%）
    vol          NUMERIC(20, 4),                   -- 成交量（万股）
    amount       NUMERIC(20, 4),                   -- 成交额（万元）
    pe           NUMERIC(12, 4),                   -- 市盈率
    pb           NUMERIC(10, 4),                   -- 市净率
    float_mv     NUMERIC(20, 4),                   -- 流通市值（万元）
    total_mv     NUMERIC(20, 4),                   -- 总市值（万元）
    weight       NUMERIC(10, 6),                   -- 权重
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
-- 按日期查所有行业（日报/行业对比最常用）
CREATE INDEX IF NOT EXISTS idx_sw_ind_daily_date ON sw_industry_daily(trade_date);
-- 按代码查历史走势（通常 PK 已覆盖，显式索引供排序优化）
CREATE INDEX IF NOT EXISTS idx_sw_ind_daily_code ON sw_industry_daily(ts_code, trade_date);


-- -------------------------------------------------------------
-- 15. 中信行业成分构成
--    来源: pro.ci_index_member()
--    描述: 记录每只股票归属哪个中信三级行业，含历史变更记录
--    建议更新频率: 月度（每月初更新，行业调整不频繁）
--
--    与申万行业成分的关键差异：
--      ① 中信无独立行业分类 API，l1_name/l2_name/l3_name 反范式存储于本表
--      ② 全量拉取无需先建行业分类表，直接分页获取（约 2~5 次 API）
--
--    主键设计：(l3_code, ts_code, in_date)
--      同一股票历史上可多次进出同一 L3 行业
--
--    关联关系（概念上）：
--      ci_industry_daily.ts_code ∈ {l1_code ∪ l2_code ∪ l3_code}
--      ts_code → stock_basic.ts_code
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_industry_member (
    l3_code    VARCHAR(12)  NOT NULL,          -- 三级行业指数代码，如 CI005835.CI
    l2_code    VARCHAR(12),                     -- 二级行业指数代码（冗余，方便查询）
    l1_code    VARCHAR(12),                     -- 一级行业指数代码（冗余，方便查询）
    l3_name    VARCHAR(40),                     -- 三级行业名称（反范式，无独立分类表）
    l2_name    VARCHAR(40),                     -- 二级行业名称
    l1_name    VARCHAR(40),                     -- 一级行业名称
    ts_code    VARCHAR(12)  NOT NULL,           -- 成分股票代码，如 000001.SZ
    name       VARCHAR(20),                     -- 成分股票名称
    in_date    DATE         NOT NULL,           -- 纳入日期（NULL 数据填充 1900-01-01）
    out_date   DATE,                            -- 剔除日期（NULL = 仍在成分中）
    is_new     VARCHAR(2)   NOT NULL DEFAULT 'Y', -- 是否最新成分 Y/N
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (l3_code, ts_code, in_date)
);
-- 按股票查询其行业归属（最常用）
CREATE INDEX IF NOT EXISTS idx_ci_ind_member_ts     ON ci_industry_member(ts_code);
-- 按一级 / 二级行业筛选
CREATE INDEX IF NOT EXISTS idx_ci_ind_member_l1     ON ci_industry_member(l1_code);
CREATE INDEX IF NOT EXISTS idx_ci_ind_member_l2     ON ci_industry_member(l2_code);
-- 快速取当前成分（is_new='Y'）
CREATE INDEX IF NOT EXISTS idx_ci_ind_member_is_new ON ci_industry_member(is_new, l3_code);


-- -------------------------------------------------------------
-- 16. 中信行业指数日线行情
--    来源: pro.ci_daily()
--    描述: 中信行业指数每日行情（无 pe/pb/mv/weight，有 pre_close）
--    建议更新频率: 每个交易日收盘后（--date 模式，1次API=全行业约440条）
--
--    与申万行业日线（sw_industry_daily）的差异：
--      ① 有 pre_close（昨日收盘点位）
--      ② 无 pe / pb / float_mv / total_mv / weight
--
--    关联关系：
--      ts_code ∈ {ci_industry_member.l1_code ∪ l2_code ∪ l3_code}
--
--    两种拉取策略：
--      日常更新: ci_daily(trade_date=...) → 1次API = 当日全行业（约440条）
--      历史回填: ci_daily(ts_code=..., start_date=...) → 按代码分页，推荐首次导入
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ci_industry_daily (
    ts_code      VARCHAR(12)  NOT NULL,            -- 中信行业指数代码，如 CI005001.CI
    trade_date   DATE         NOT NULL,            -- 交易日期
    open         NUMERIC(12, 4),                   -- 开盘点位
    high         NUMERIC(12, 4),                   -- 最高点位
    low          NUMERIC(12, 4),                   -- 最低点位
    close        NUMERIC(12, 4),                   -- 收盘点位
    pre_close    NUMERIC(12, 4),                   -- 昨日收盘点位
    change       NUMERIC(12, 4),                   -- 涨跌点位
    pct_change   NUMERIC(8, 4),                    -- 涨跌幅（%）
    vol          NUMERIC(20, 4),                   -- 成交量（万股）
    amount       NUMERIC(20, 4),                   -- 成交额（万元）
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
-- 按日期查所有行业（日报/行业对比最常用）
CREATE INDEX IF NOT EXISTS idx_ci_ind_daily_date ON ci_industry_daily(trade_date);
-- 按代码查历史走势
CREATE INDEX IF NOT EXISTS idx_ci_ind_daily_code ON ci_industry_daily(ts_code, trade_date);


-- -------------------------------------------------------------
-- 17. 同花顺行业/概念板块基础信息
--    来源: pro.ths_index()
--    描述: 同花顺行业板块、概念板块、大盘指数基础信息
--    建议更新频率: 月度（每月初更新，与成分股联动）
--
--    板块类型（type 字段）：
--      N = 行业板块（同花顺行业分类）
--      I = 概念板块
--      S = 同花顺特色
--      W = 概念等其他板块
--      B = 大盘指数
--
--    关联关系：
--      ths_member.ts_code → ths_index.ts_code
--      ths_daily.ts_code  → ths_index.ts_code
--
--    主键：ts_code（板块代码唯一）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ths_index (
    ts_code    VARCHAR(16)  NOT NULL,          -- 板块代码，如 885650.TI
    name       VARCHAR(40),                    -- 板块名称
    count      INT,                            -- 成分股数量
    exchange   VARCHAR(8),                     -- 交易所，如 A（A股）
    list_date  DATE,                           -- 上市日期
    type       VARCHAR(4),                     -- 板块类型 N/I/S/W/B
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code)
);
-- 按类型过滤（行业/概念/大盘）
CREATE INDEX IF NOT EXISTS idx_ths_index_type ON ths_index(type);


-- -------------------------------------------------------------
-- 18. 同花顺板块成分股
--    来源: pro.ths_member()
--    描述: 同花顺行业/概念板块的成分股列表
--    建议更新频率: 月度（每月初更新）
--
--    主键设计：(ts_code, con_code)
--      接口 in_date 频繁返回 NULL，无法作为 PK 使用
--      以 (板块, 成分股) 唯一标识一条当前成分记录
--
--    关联关系：
--      ts_code  → ths_index.ts_code（板块）
--      con_code → stock_basic.ts_code（成分股）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ths_member (
    ts_code    VARCHAR(16)  NOT NULL,          -- 板块代码，如 885650.TI
    con_code   VARCHAR(12)  NOT NULL,          -- 成分股代码，如 000001.SZ
    con_name   VARCHAR(20),                    -- 成分股名称
    weight     NUMERIC(10, 4),                 -- 权重（%）
    in_date    DATE,                           -- 纳入日期（接口可能为 NULL）
    out_date   DATE,                           -- 剔除日期（NULL = 仍在成分中）
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, con_code)
);
-- 按股票查其所属板块（最常用）
CREATE INDEX IF NOT EXISTS idx_ths_member_con_code ON ths_member(con_code);
-- 按板块查其成分股
CREATE INDEX IF NOT EXISTS idx_ths_member_ts_code  ON ths_member(ts_code);


-- -------------------------------------------------------------
-- 19. 同花顺板块指数日线行情
--    来源: pro.ths_daily()
--    描述: 同花顺行业/概念板块每日行情及涨跌家数
--    建议更新频率: 每个交易日收盘后（--date 模式，1次API=当日全板块）
--
--    与申万/中信行业日线的差异：
--      ① 有 avg_price（均价）、turnover_rate（换手率）
--      ② 有 total_mv / float_mv（总市值/流通市值，万元）
--      ③ 有 up_count / down_count（上涨/下跌家数）
--      ④ 无 pe / pb / weight
--
--    两种拉取策略：
--      日常更新: ths_daily(trade_date=...) → 1次API = 当日全板块
--      历史回填: ths_daily(ts_code=..., start_date=...) → 按代码分页
--
--    关联关系：
--      ts_code → ths_index.ts_code
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ths_daily (
    ts_code        VARCHAR(16)  NOT NULL,          -- 板块代码，如 885650.TI
    trade_date     DATE         NOT NULL,           -- 交易日期
    open           NUMERIC(12, 4),                 -- 开盘点位
    high           NUMERIC(12, 4),                 -- 最高点位
    low            NUMERIC(12, 4),                 -- 最低点位
    close          NUMERIC(12, 4),                 -- 收盘点位
    pre_close      NUMERIC(12, 4),                 -- 昨日收盘点位
    change         NUMERIC(12, 4),                 -- 涨跌点位
    pct_chg        NUMERIC(8, 4),                  -- 涨跌幅（%）
    avg_price      NUMERIC(12, 4),                 -- 均价
    turnover_rate  NUMERIC(10, 4),                 -- 换手率（%）
    total_mv       NUMERIC(20, 4),                 -- 总市值（万元）
    float_mv       NUMERIC(20, 4),                 -- 流通市值（万元）
    vol            NUMERIC(20, 4),                 -- 成交量（万股）
    amount         NUMERIC(20, 4),                 -- 成交额（万元）
    up_count       INT,                            -- 上涨家数
    down_count     INT,                            -- 下跌家数
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
-- 按日期查所有板块（日报/板块对比最常用）
CREATE INDEX IF NOT EXISTS idx_ths_daily_date ON ths_daily(trade_date);
-- 按代码查历史走势
CREATE INDEX IF NOT EXISTS idx_ths_daily_code ON ths_daily(ts_code, trade_date);


-- -------------------------------------------------------------
-- 20. 东方财富概念板块每日快照（dc_index）
--     来源: pro.dc_index()
--     描述: 获取东方财富每个交易日的概念板块数据，支持按日期查询
--     限量: 单次最大 5000 条，历史数据可根据日期循环获取
--     所需积分: 6000
--     idx_type: 行业板块 / 概念板块 / 地域板块（查询时必填）
--     建议更新频率: 每个交易日收盘后（1次API=当日全量板块）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dc_index (
    ts_code        VARCHAR(20)  NOT NULL,       -- 概念代码，如 BK1186.DC
    trade_date     DATE         NOT NULL,        -- 交易日期
    name           VARCHAR(40),                  -- 概念名称
    leading_name   VARCHAR(20),                  -- 领涨股票名称
    leading_code   VARCHAR(12),                  -- 领涨股票代码
    pct_change     NUMERIC(10, 4),               -- 涨跌幅（%）
    leading_pct    NUMERIC(10, 4),               -- 领涨股票涨跌幅（%）
    total_mv       NUMERIC(24, 4),               -- 总市值（万元）
    turnover_rate  NUMERIC(10, 4),               -- 换手率（%）
    up_num         INT,                          -- 上涨家数
    down_num       INT,                          -- 下降家数
    idx_type       VARCHAR(10),                  -- 板块类型（行业板块/概念板块/地域板块）
    level          VARCHAR(10),                  -- 行业层级
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
-- 按日期查全量板块（最常用）
CREATE INDEX IF NOT EXISTS idx_dc_index_date     ON dc_index (trade_date);
-- 按代码查板块历史走势
CREATE INDEX IF NOT EXISTS idx_dc_index_ts_code  ON dc_index (ts_code, trade_date);
-- 按板块类型过滤
CREATE INDEX IF NOT EXISTS idx_dc_index_idx_type ON dc_index (idx_type, trade_date);


-- -------------------------------------------------------------
-- 21. 东方财富板块成分股（dc_member）
--     来源: pro.dc_member()
--     描述: 获取东方财富板块每日成分数据，可根据概念板块代码和交易日期查询
--     限量: 单次最大 5000 条，可通过日期和代码循环获取
--     所需积分: 6000
--     说明: 成分可每日变动，以 (ts_code, con_code, trade_date) 为主键记录历史
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dc_member (
    trade_date     DATE         NOT NULL,        -- 交易日期
    ts_code        VARCHAR(20)  NOT NULL,        -- 板块代码，如 BK1184.DC
    con_code       VARCHAR(12)  NOT NULL,        -- 成分股代码，如 002117.SZ
    name           VARCHAR(20),                  -- 成分股名称
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, ts_code, con_code)
);
-- 按板块代码查全部成分（最常用）
CREATE INDEX IF NOT EXISTS idx_dc_member_ts_code  ON dc_member (ts_code, trade_date);
-- 按成分股查其所属板块
CREATE INDEX IF NOT EXISTS idx_dc_member_con_code ON dc_member (con_code, trade_date);
-- 按日期查全量成分快照
CREATE INDEX IF NOT EXISTS idx_dc_member_date     ON dc_member (trade_date);


-- -------------------------------------------------------------
-- 22. 东方财富板块行情（dc_daily）
--     来源: pro.dc_daily()
--     描述: 获取东方财富概念板块/行业指数板块/地域板块行情数据，历史数据起始于2020年
--     限量: 单次最大 2000 条，可根据日期参数循环获取
--     所需积分: 6000
--     建议更新频率: 每个交易日收盘后（1次API=当日全量板块）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dc_daily (
    ts_code        VARCHAR(20)  NOT NULL,        -- 板块代码，如 BK1063.DC
    trade_date     DATE         NOT NULL,         -- 交易日期
    open           NUMERIC(12, 4),                -- 开盘点位
    high           NUMERIC(12, 4),                -- 最高点位
    low            NUMERIC(12, 4),                -- 最低点位
    close          NUMERIC(12, 4),                -- 收盘点位
    change         NUMERIC(12, 4),                -- 涨跌点位
    pct_change     NUMERIC(10, 4),                -- 涨跌幅（%）
    vol            NUMERIC(24, 4),                -- 成交量（股）
    amount         NUMERIC(24, 4),                -- 成交额（元）
    swing          NUMERIC(10, 4),                -- 振幅（%）
    turnover_rate  NUMERIC(10, 4),                -- 换手率（%）
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
-- 按日期查全量板块行情（日报/板块轮动最常用）
CREATE INDEX IF NOT EXISTS idx_dc_daily_date    ON dc_daily (trade_date);
-- 按代码查板块历史K线
CREATE INDEX IF NOT EXISTS idx_dc_daily_ts_code ON dc_daily (ts_code, trade_date);


-- -------------------------------------------------------------
-- 23. 同花顺涨跌停榜单（limit_list_ths）
--     来源: pro.limit_list_ths()
--     描述: 获取同花顺每日涨跌停榜单数据，历史数据从20231101开始提供
--     限量: 单次最大 4000 条，limit_type 一次只能传一个值
--     所需积分: 8000
--     建议更新频率: 每个交易日收盘后，依次拉取 5 种类型
--     limit_type 取值: 涨停池 | 连板池 | 冲刺涨停 | 炸板池 | 跌停池
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS limit_list_ths (
    trade_date         DATE         NOT NULL,        -- 交易日期
    ts_code            VARCHAR(12)  NOT NULL,        -- 股票代码
    limit_type         VARCHAR(10)  NOT NULL,        -- 板单类别（主键一部分）
    name               VARCHAR(20),                  -- 股票名称
    price              NUMERIC(12, 4),               -- 收盘价（元）
    pct_chg            NUMERIC(10, 4),               -- 涨跌幅%
    open_num           INTEGER,                      -- 打开次数
    lu_desc            TEXT,                         -- 涨停原因
    tag                VARCHAR(100),                 -- 涨停标签
    status             VARCHAR(30),                  -- 涨停状态（N连板、一字板等）
    first_lu_time      VARCHAR(20),                  -- 首次涨停时间
    last_lu_time       VARCHAR(20),                  -- 最后涨停时间
    first_ld_time      VARCHAR(20),                  -- 首次跌停时间
    last_ld_time       VARCHAR(20),                  -- 最后跌停时间
    limit_order        NUMERIC(20, 2),               -- 封单量（元）
    limit_amount       NUMERIC(20, 2),               -- 封单额（元）
    turnover_rate      NUMERIC(10, 4),               -- 换手率%
    free_float         NUMERIC(20, 2),               -- 实际流通（元）
    lu_limit_order     NUMERIC(20, 2),               -- 最大封单（元）
    limit_up_suc_rate  NUMERIC(10, 4),               -- 近一年涨停封板率
    turnover           NUMERIC(20, 2),               -- 成交额
    rise_rate          NUMERIC(10, 4),               -- 涨速
    sum_float          NUMERIC(16, 4),               -- 总市值（亿元）
    market_type        VARCHAR(20),                  -- 股票类型（HS沪深主板/GEM创业板/STAR科创板）
    updated_at         TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, ts_code, limit_type)
);
-- 按日期查当日全部涨跌停榜单
CREATE INDEX IF NOT EXISTS idx_limit_list_ths_date      ON limit_list_ths (trade_date);
-- 按股票代码查历史涨跌停记录
CREATE INDEX IF NOT EXISTS idx_limit_list_ths_ts_code   ON limit_list_ths (ts_code, trade_date);
-- 按板单类别查询
CREATE INDEX IF NOT EXISTS idx_limit_list_ths_type_date ON limit_list_ths (limit_type, trade_date);


-- -------------------------------------------------------------
-- 26. 开盘啦涨跌停榜单
--    来源: pro.kpl_list()
--    描述: 获取开盘啦涨停、炸板、跌停等榜单数据
--    tag 可选值: 涨停 / 炸板 / 跌停 / 自然涨停 / 竞价（默认涨停）
--    限量: 单次最大 8000 条，可按日期区间循环提取
--    所需积分: 8000
--    注意: 数据更新时间为次日 8:30，晚间 pipeline 拉取的是昨日及之前数据
--
--    主键设计: (ts_code, trade_date, tag)
--      同一股票同一天可出现在多个榜单（如先涨停后炸板）
--      同一 tag 视为同一条记录，upsert 覆盖
--
--    拉取策略:
--      涨停/跌停: 按 15 天分批（极端行情 ~500只/天 × 15 = 7500 < 8000）
--      炸板/自然涨停/竞价: 按 30 天分批（数据量较少）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpl_list (
    ts_code        VARCHAR(12)   NOT NULL,   -- 股票代码
    trade_date     DATE          NOT NULL,   -- 交易日期
    tag            VARCHAR(20)   NOT NULL,   -- 板单类型（涨停/炸板/跌停/自然涨停/竞价）
    name           VARCHAR(20),              -- 股票名称
    lu_time        VARCHAR(8),               -- 涨停时间（HH:MM 或 HH:MM:SS）
    ld_time        VARCHAR(8),               -- 跌停时间
    open_time      VARCHAR(8),               -- 开板时间
    last_time      VARCHAR(8),               -- 最后涨幅时间
    lu_desc        TEXT,                     -- 涨停原因
    theme          TEXT[],                   -- 板块（数组，支持 GIN 精确过滤）
    net_change     NUMERIC(20, 4),           -- 主力净额（元）
    bid_amount     NUMERIC(20, 4),           -- 竞价成交额（元）
    status         VARCHAR(30),              -- 状态（首板/2连板/N连板）
    bid_change     NUMERIC(20, 4),           -- 竞价净额
    bid_turnover   NUMERIC(12, 4),           -- 竞价换手%
    lu_bid_vol     NUMERIC(20, 4),           -- 涨停委买额
    pct_chg        NUMERIC(12, 4),           -- 涨跌幅%
    bid_pct_chg    NUMERIC(12, 4),           -- 竞价涨幅%
    rt_pct_chg     NUMERIC(12, 4),           -- 实时涨幅%
    limit_order    NUMERIC(20, 4),           -- 封单
    amount         NUMERIC(20, 4),           -- 成交额
    turnover_rate  NUMERIC(12, 4),           -- 换手率%
    free_float     NUMERIC(20, 4),           -- 实际流通
    lu_limit_order NUMERIC(20, 4),           -- 最大封单
    updated_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date, tag)
);
-- 按日期查当日全部榜单（最常用）
CREATE INDEX IF NOT EXISTS idx_kpl_list_date     ON kpl_list (trade_date);
-- 按日期+类型过滤
CREATE INDEX IF NOT EXISTS idx_kpl_list_date_tag ON kpl_list (trade_date, tag);
-- 按板块精确过滤（GIN，支持 '某板块' = ANY(theme)）
CREATE INDEX IF NOT EXISTS idx_kpl_list_theme    ON kpl_list USING GIN (theme);


-- -------------------------------------------------------------
-- 同花顺热榜（hot_list_ths）
--    来源: pro.ths_hot()
--    描述: 同花顺App热榜数据，含热股/ETF/可转债/行业板块/
--          概念板块/期货/港股/热基/美股等多类型
--    拉取策略: 每15分钟拉取一次最新快照（is_new=Y），
--              存储全量快照用于盘中热度变化分析
--    建议更新频率: 工作日 9:00~22:00 每15分钟
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hot_list_ths (
    trade_date     DATE         NOT NULL,          -- 交易日期
    data_type      VARCHAR(20)  NOT NULL,          -- 热榜类型（热股/ETF/可转债/行业板块/概念板块/期货/港股/热基/美股）
    rank_time      TIMESTAMP    NOT NULL,          -- 快照时间（排行榜获取时间）
    ts_code        VARCHAR(32)  NOT NULL,          -- 标的代码
    ts_name        VARCHAR(100),                   -- 标的名称
    rank           INTEGER,                        -- 排行
    pct_change     NUMERIC(8,4),                   -- 涨跌幅%
    current_price  NUMERIC(12,4),                  -- 当前价格
    concept        TEXT,                           -- 标签
    rank_reason    TEXT,                           -- 上榜解读
    hot            NUMERIC(16,4),                  -- 热度值
    PRIMARY KEY (trade_date, data_type, rank_time, ts_code)
);

-- 按日期查询（最常用）
CREATE INDEX IF NOT EXISTS idx_hot_list_ths_date
    ON hot_list_ths (trade_date);

-- 按标的查询历史热度
CREATE INDEX IF NOT EXISTS idx_hot_list_ths_code
    ON hot_list_ths (ts_code);

-- 取某日最新快照（MAX rank_time）高效索引
CREATE INDEX IF NOT EXISTS idx_hot_list_ths_latest
    ON hot_list_ths (trade_date, data_type, rank_time DESC);

-- 兼容升级：rank 从 SMALLINT 改为 INTEGER（Tushare 返回值可能超出 32767）
ALTER TABLE hot_list_ths ALTER COLUMN rank TYPE INTEGER;
