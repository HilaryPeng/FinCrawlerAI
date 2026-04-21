# 日频市场观察系统 V1 设计

## 1. 目标

在现有 `FinCrawlerAI` 项目基础上，新增一套日频市场观察系统，用于：

- 每日收集行情、涨停、板块、新闻数据
- 识别主线板块、市场阶段、核心角色股
- 产出 `今日重点观察 20 只`
- 跟踪 1/3/5 日表现，形成观察闭环
- 为后续 AI 分析和回测提供统一结构化底座

本系统定位为：

- `日频复盘与市场观察工具`
- 不是自动交易系统
- AI 负责归纳、解释、提示风险
- 规则和结构化特征负责候选筛选与可回测性

---

## 2. 与现有项目的关系

当前项目已具备的能力：

- 财联社抓取：`src/scraper/cailian_scraper.py`
- 韭菜公社抓取：`src/scraper/jiuyangongshe_scraper.py`
- 新闻清洗：`src/processor/cleaner.py`
- 新闻事件聚合：`src/processor/aggregator.py`
- Markdown/JSON 输出：`src/output/`
- 飞书推送：`src/notifier/`

V1 的实现方式不是推翻重做，而是新增一条链路：

`市场数据采集 -> 特征构建 -> 板块/个股打分 -> 观察池筛选 -> 日报输出 -> 观察跟踪`

新闻链路继续保留，作为市场观察系统的输入之一。

---

## 3. 推荐数据库方案

## 3.1 选型建议

V1 推荐：

- 默认数据库：`SQLite`
- 分析导出：继续保留 `JSON/Markdown`
- 后续扩展：预留迁移到 `PostgreSQL`

原因：

- 当前项目是本地 Python 工具，日频写入量不大
- SQLite 部署成本最低，适合先快速落地
- 数据规模在 V1 阶段可控，足够支撑日频观察与轻量回测
- 后续若加入多人协作、定时服务、Web 接口，再迁移 PostgreSQL 更合理

不建议 V1 直接上复杂数据库栈的原因：

- 当前核心问题不是并发，而是数据口径和特征设计
- 过早引入复杂存储会拖慢落地速度

## 3.2 存储策略

推荐采用“双写”：

- 结构化主数据写入 `SQLite`
- 产出结果继续落盘 `JSON/Markdown`

这样兼顾：

- 查询、去重、关联、回测方便
- 每日结果可直接阅读、备份、喂给 AI

## 3.3 建议新增目录

- `data/db/market_daily.db`
- `docs/market_daily_system_design.md`
- `src/db/`
- `src/market/`
- `src/backtest/`

---

## 4. 数据分层设计

推荐把数据分为四层：

### 4.1 原始层 Raw

用途：

- 保留原始响应
- 便于排障、重放、数据修复

来源：

- 财联社原始新闻
- 韭菜公社原始异动解析
- AkShare/东方财富原始行情和板块接口响应

落地方式：

- 文件缓存：`data/raw/...`

### 4.2 标准层 Staging

用途：

- 不同来源字段统一
- 做基础清洗和标准编码

典型对象：

- 标准新闻条目
- 标准股票日行情
- 标准板块快照
- 标准涨停事件

落地方式：

- SQLite 表
- 必要时同步输出 JSON

### 4.3 特征层 Feature

用途：

- 生成板块和股票的评分输入
- 保证后续 AI 和回测使用同一套特征

典型对象：

- 个股日特征
- 板块日特征
- 市场情绪特征

### 4.4 应用层 Application

用途：

- 重点观察池
- AI 分析输入
- 日报
- 观察跟踪和回测结果

---

## 5. 数据库表设计

以下为 V1 推荐的核心表。

## 5.1 `news_items`

用途：

- 存储标准化后的新闻条目
- 承接财联社和韭菜公社数据

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| source | TEXT | `cailian` / `jygs` |
| source_uid | TEXT | 来源侧唯一标识 |
| title | TEXT | 标题 |
| content | TEXT | 内容 |
| publish_time | TEXT | 原始时间字符串 |
| publish_ts | INTEGER | 时间戳 |
| url | TEXT | 原始链接 |
| event_id | TEXT | 聚合后的事件 ID |
| raw_json | TEXT | 原始标准化 JSON |
| created_at | TEXT | 入库时间 |

建议索引：

- `(source, source_uid)` 唯一索引
- `publish_ts`
- `event_id`

## 5.2 `news_item_symbols`

用途：

- 一条新闻可能关联多个股票

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| news_id | INTEGER | 对应 `news_items.id` |
| symbol | TEXT | 股票代码，统一为 `sz000001` 这种格式 |
| stock_name | TEXT | 股票名称 |
| relation_type | TEXT | `mentioned` / `core` / `limit_up_reason` |

建议索引：

- `news_id`
- `symbol`

## 5.3 `news_item_themes`

用途：

- 一条新闻可能关联多个题材/板块

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| news_id | INTEGER | 对应 `news_items.id` |
| theme_name | TEXT | 题材名称 |
| theme_type | TEXT | `industry` / `concept` / `policy` / `event` |

建议索引：

- `news_id`
- `theme_name`

## 5.4 `daily_stock_quotes`

用途：

- 股票日行情主表

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日，`YYYY-MM-DD` |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| prev_close | REAL | 昨收 |
| pct_chg | REAL | 涨跌幅 |
| chg | REAL | 涨跌额 |
| volume | REAL | 成交量 |
| amount | REAL | 成交额 |
| amplitude | REAL | 振幅 |
| turnover | REAL | 换手率 |
| total_mv | REAL | 总市值 |
| circ_mv | REAL | 流通市值 |
| source | TEXT | 数据来源 |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, symbol)`

建议索引：

- `trade_date`
- `symbol`
- `pct_chg`
- `amount`

## 5.5 `daily_stock_limits`

用途：

- 存储涨停、炸板、连板等事件

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| limit_up | INTEGER | 是否涨停，0/1 |
| broken_limit | INTEGER | 是否炸板，0/1 |
| limit_up_streak | INTEGER | 连板数 |
| first_limit_time | TEXT | 首次涨停时间 |
| final_limit_time | TEXT | 最终封板时间 |
| limit_reason | TEXT | 涨停原因摘要 |
| source | TEXT | 数据来源 |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, symbol)`

## 5.6 `stock_board_membership`

用途：

- 存储股票和板块映射

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| symbol | TEXT | 股票代码 |
| board_name | TEXT | 板块名称 |
| board_type | TEXT | `industry` / `concept` |
| is_primary | INTEGER | 是否主归属 |
| source | TEXT | 数据来源 |

建议索引：

- `(trade_date, symbol)`
- `(trade_date, board_name)`

## 5.7 `daily_board_quotes`

用途：

- 板块日快照

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| board_name | TEXT | 板块名称 |
| board_type | TEXT | `industry` / `concept` |
| pct_chg | REAL | 板块涨跌幅 |
| up_count | INTEGER | 上涨家数 |
| down_count | INTEGER | 下跌家数 |
| leader_symbol | TEXT | 领涨股代码 |
| leader_name | TEXT | 领涨股名称 |
| leader_pct_chg | REAL | 领涨股涨幅 |
| source | TEXT | 数据来源 |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, board_type, board_name)`

## 5.8 `daily_market_breadth`

用途：

- 存储市场情绪和宽度数据

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | TEXT PK | 交易日 |
| sh_index_pct | REAL | 上证指数涨跌幅 |
| sz_index_pct | REAL | 深证指数涨跌幅 |
| cyb_index_pct | REAL | 创业板涨跌幅 |
| total_amount | REAL | 两市成交额 |
| up_count | INTEGER | 上涨家数 |
| down_count | INTEGER | 下跌家数 |
| limit_up_count | INTEGER | 涨停家数 |
| limit_down_count | INTEGER | 跌停家数 |
| broken_limit_count | INTEGER | 炸板家数 |
| highest_streak | INTEGER | 连板高度 |
| created_at | TEXT | 入库时间 |

## 5.9 `daily_stock_features`

用途：

- 股票日特征快照
- 这是评分和回测的核心输入表

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| primary_board_name | TEXT | 主板块 |
| primary_board_type | TEXT | 主板块类型 |
| pct_chg | REAL | 涨跌幅 |
| amount | REAL | 成交额 |
| turnover | REAL | 换手率 |
| amplitude | REAL | 振幅 |
| total_mv | REAL | 总市值 |
| circ_mv | REAL | 流通市值 |
| limit_up | INTEGER | 是否涨停 |
| broken_limit | INTEGER | 是否炸板 |
| limit_up_streak | INTEGER | 连板数 |
| days_in_limit_up_last_20 | INTEGER | 近 20 日涨停次数 |
| news_count | INTEGER | 新闻条数 |
| cls_news_count | INTEGER | 财联社新闻数 |
| jygs_news_count | INTEGER | 韭菜公社提及数 |
| news_heat_score | REAL | 新闻热度分 |
| board_score_ref | REAL | 所属板块参考分 |
| dragon_score | REAL | 龙头候选分 |
| center_score | REAL | 中军候选分 |
| follow_score | REAL | 补涨候选分 |
| risk_score | REAL | 风险分 |
| final_score | REAL | 最终观察分 |
| role_tag | TEXT | `dragon` / `center` / `follow` / `watchlist` |
| risk_flags | TEXT | JSON 数组 |
| feature_json | TEXT | 扩展特征 JSON |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, symbol)`

## 5.10 `daily_board_features`

用途：

- 板块日特征快照

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| board_name | TEXT | 板块名称 |
| board_type | TEXT | 板块类型 |
| pct_chg | REAL | 涨跌幅 |
| up_count | INTEGER | 上涨家数 |
| down_count | INTEGER | 下跌家数 |
| limit_up_count | INTEGER | 涨停家数 |
| core_stock_count | INTEGER | 核心股票数 |
| news_count | INTEGER | 新闻数 |
| news_heat_score | REAL | 新闻热度分 |
| dragon_strength | REAL | 龙头强度 |
| center_strength | REAL | 中军强度 |
| breadth_score | REAL | 扩散度分 |
| continuity_score | REAL | 持续性分 |
| board_score | REAL | 板块总分 |
| phase_hint | TEXT | `start` / `expand` / `accelerate` / `fade` |
| feature_json | TEXT | 扩展特征 JSON |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, board_type, board_name)`

## 5.11 `daily_observation_pool`

用途：

- 存储当日重点观察池

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| trade_date | TEXT | 交易日 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| role_tag | TEXT | 角色 |
| board_name | TEXT | 所属板块 |
| board_rank | INTEGER | 板块排名 |
| stock_rank | INTEGER | 股票排名 |
| final_score | REAL | 最终分 |
| selected_reason | TEXT | 入选原因 |
| watch_points | TEXT | 观察要点 |
| risk_flags | TEXT | 风险标签 JSON |
| pool_group | TEXT | `top20` / `backup` |
| created_at | TEXT | 入库时间 |

建议唯一键：

- `(trade_date, symbol, pool_group)`

## 5.12 `observation_tracking`

用途：

- 跟踪观察池后续表现

主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| base_trade_date | TEXT | 入池日期 |
| symbol | TEXT | 股票代码 |
| name | TEXT | 股票名称 |
| role_tag | TEXT | 入池角色 |
| entry_price | REAL | 观察基准价，默认入池日收盘价 |
| next_1d_pct | REAL | 次日涨跌幅 |
| next_3d_pct | REAL | 3日涨跌幅 |
| next_5d_pct | REAL | 5日涨跌幅 |
| max_up_5d | REAL | 5日最大涨幅 |
| max_drawdown_5d | REAL | 5日最大回撤 |
| still_hot_3d | INTEGER | 3日内是否仍在热点池 |
| still_hot_5d | INTEGER | 5日内是否仍在热点池 |
| tracking_json | TEXT | 扩展跟踪明细 |
| updated_at | TEXT | 更新时间 |

建议唯一键：

- `(base_trade_date, symbol)`

---

## 6. 为什么这样设计更合理

核心原则：

- `原始事实` 和 `衍生特征` 分离
- `个股维度` 和 `板块维度` 分离
- `当日入选结果` 和 `后续跟踪结果` 分离

这样设计的好处：

- 可追溯：能回查某只票为什么被选中
- 可重算：更新评分逻辑时不需要重抓原始数据
- 可回测：观察池与后续表现天然关联
- 可扩展：后面接龙虎榜、资金流、公告，不需要改主表结构

不建议一开始把所有字段塞进一张总表，因为：

- 后续字段会膨胀
- 新闻和板块是多对多关系
- 回测和重算会变得很难维护

---

## 7. 每日处理流程

建议每日执行顺序如下：

### 7.1 第一步：采集原始数据

- 抓取财联社新闻
- 抓取韭菜公社异动解析
- 抓取股票日行情
- 抓取板块快照
- 抓取涨停/炸板/连板数据
- 抓取市场宽度数据

### 7.2 第二步：标准化入库

- 新闻条目标准化后写入 `news_items`
- 行情写入 `daily_stock_quotes`
- 涨停信息写入 `daily_stock_limits`
- 板块映射写入 `stock_board_membership`
- 板块快照写入 `daily_board_quotes`
- 市场情绪写入 `daily_market_breadth`

### 7.3 第三步：构建特征

- 生成 `daily_board_features`
- 生成 `daily_stock_features`

### 7.4 第四步：筛选观察池

- 根据板块分找出 Top 3-5 主线
- 根据角色分生成 `dragon` / `center` / `follow`
- 产出 `今日重点观察 20 只`
- 写入 `daily_observation_pool`

### 7.5 第五步：产出日报

- 生成 JSON
- 生成 Markdown
- 可选推送飞书

### 7.6 第六步：跟踪历史观察池

- 更新 1 日、3 日、5 日表现
- 写入 `observation_tracking`

---

## 8. 重点观察 20 只的构成

建议固定配比，避免全是同一种风格：

- 龙头：6 只
- 中军：6 只
- 补涨/扩散：6 只
- 预备切换/异动观察：2 只

如果当日某类不足：

- 优先从主线板块中补
- 再从次主线板块中补

不建议直接按总分前 20 名，因为那样常常会：

- 全挤在一个题材
- 全是小票连板
- 漏掉容量中军

---

## 9. 评分框架建议

## 9.1 板块评分

板块总分 `board_score` 建议由以下部分组成：

- 板块涨跌幅强度
- 板块涨停家数
- 板块扩散度
- 板块新闻热度
- 龙头强度
- 中军强度
- 近 3 日/5 日持续性

示意：

```text
board_score =
0.20 * pct_strength +
0.20 * limit_up_strength +
0.15 * breadth_score +
0.15 * news_heat_score +
0.15 * dragon_strength +
0.10 * center_strength +
0.05 * continuity_score
```

## 9.2 个股评分

个股先拆成三个角色分：

- `dragon_score`
- `center_score`
- `follow_score`

再根据角色映射出 `final_score`。

示意：

```text
dragon_score:
- 连板数
- 涨停辨识度
- 所属板块强度
- 新闻催化强度
- 是否板块龙一

center_score:
- 成交额
- 市值容量
- 趋势强度
- 所属板块强度
- 新闻与催化强度

follow_score:
- 低位补涨
- 板块扩散度
- 近几日首次显著走强
- 题材共振
```

风险分建议单独扣减，不要混在正向因子里。

---

## 10. AI 在系统中的角色

AI 不直接负责打分。

AI 更适合做：

- 主线板块归纳
- 市场阶段判断
- 候选股解释
- 风险提示

AI 输入应为：

- 市场总览
- 板块特征 Top 列表
- 观察池 20 只的结构化信息
- 相关新闻摘要
- 近几日跟踪表现

AI 输出固定建议：

- 当前市场阶段
- 当前主线板块
- 最强龙头 / 中军 / 补涨
- 次日需要重点盯的变化点
- 风险提示

---

## 11. 建议新增代码结构

```text
src/
├── db/
│   ├── __init__.py
│   ├── connection.py
│   ├── schema.py
│   └── repository.py
├── market/
│   ├── __init__.py
│   ├── collectors/
│   │   ├── quotes_collector.py
│   │   ├── boards_collector.py
│   │   ├── limit_up_collector.py
│   │   └── market_breadth_collector.py
│   ├── features/
│   │   ├── news_feature_builder.py
│   │   ├── stock_feature_builder.py
│   │   └── board_feature_builder.py
│   ├── ranker/
│   │   ├── board_ranker.py
│   │   ├── stock_ranker.py
│   │   └── selector.py
│   ├── report/
│   │   └── daily_report_generator.py
│   └── storage/
│       └── file_store.py
└── backtest/
    └── observer_tracker.py
```

---

## 12. 推荐 CLI 规划

建议在 `main.py` 里新增以下命令：

- `market-daily`
  - 执行日频采集、特征构建、观察池筛选、日报输出

- `market-track`
  - 更新历史观察池的后续表现

- `market-all --notify`
  - 执行日频流程并推送结果

---

## 13. 实施顺序建议

建议分阶段推进：

### 阶段 1：数据库底座

- 建立 SQLite 连接模块
- 初始化表结构
- 实现基础 repository

### 阶段 2：市场数据采集

- 行情采集
- 板块采集
- 涨停采集
- 市场宽度采集

### 阶段 3：新闻结构化增强

- 新闻关联股票
- 新闻关联题材
- 生成新闻热度特征

### 阶段 4：特征与评分

- 板块特征
- 个股特征
- 角色分
- 风险分

### 阶段 5：观察池与日报

- 筛选 20 只重点观察
- 生成 Markdown/JSON 日报

### 阶段 6：观察跟踪

- 生成 1/3/5 日跟踪数据
- 评估观察池有效性

---

## 14. V1 不建议立即做的事

以下内容先不要在第一阶段投入太多精力：

- 盘中实时系统
- 高频资金流分钟级建模
- 黑箱机器学习直接预测涨跌
- 自动交易下单
- 过于复杂的因子优化

V1 的重点是：

- 数据口径统一
- 每日结构化可落地
- 观察池可跟踪
- AI 输出稳定可解释

---

## 15. 本文档对应的下一步

建议按下面顺序逐步实现：

1. 先落数据库模块和 schema
2. 再接市场采集器
3. 再做特征表
4. 再做评分和 20 只观察池
5. 最后做日报和观察跟踪

如果后续继续开发，应优先保证：

- 同一交易日数据可以重复跑
- 重跑不产生脏重复数据
- 任一评分规则调整后可以重算历史特征

这会直接决定后面项目是否好维护。

---

## 16. 最小可实现方案（MVP）

本节用于把整体方案收敛成可落地、可中断、可逐步验收的执行路径。

MVP 原则：

- 先打通完整链路，再补细节
- 每一步都能单独运行和验收
- 每一步失败时，不影响已完成部分复用
- 每一步都产出明确文件或表数据，便于中断后继续

### 16.1 MVP 目标

第一阶段只要求做到：

- 能抓取新闻、行情、板块基础数据
- 能将数据落入 SQLite
- 能生成股票和板块基础特征
- 能筛出 `今日重点观察 20 只`
- 能输出一份日频 Markdown/JSON 日报

第一阶段暂不要求：

- 高质量资金流因子
- 龙虎榜
- 分钟级数据
- 实盘级交易回测
- 复杂机器学习模型

### 16.2 MVP 必要输入

MVP 只依赖以下数据：

- 财联社新闻
- 韭菜公社异动解析
- 股票日行情
- 行业/概念板块快照
- 涨停/连板基础数据
- 市场宽度数据

### 16.3 MVP 最终产物

MVP 完成后，每天至少产出：

- `data/db/market_daily.db`
- `data/processed/market_daily/market_daily_YYYYMMDD.json`
- `data/processed/market_daily/market_daily_YYYYMMDD.md`
- `data/processed/market_daily/observation_pool_YYYYMMDD.json`

---

## 17. 可中断执行的实施计划

以下计划按“最小颗粒度”拆分。每个阶段都可以暂停，且有清晰的完成标准。

## 阶段 A：数据库底座

目标：

- 建立数据库连接
- 初始化 schema
- 为后续采集和特征入库提供统一接口

范围：

- 只做数据库，不做业务逻辑

建议文件：

- `src/db/__init__.py`
- `src/db/connection.py`
- `src/db/schema.py`
- `src/db/repository.py`

完成标准：

- 能执行数据库初始化
- 数据库文件自动生成到 `data/db/market_daily.db`
- 核心表能成功创建

可中断点：

- 数据库建好即可暂停

验收方式：

- 本地执行初始化命令无报错
- SQLite 中能看到表结构

## 阶段 B：市场基础采集

目标：

- 把“市场事实数据”拉下来并入库

范围：

- 股票日行情
- 板块快照
- 涨停基础数据
- 市场宽度数据

建议文件：

- `src/market/collectors/quotes_collector.py`
- `src/market/collectors/boards_collector.py`
- `src/market/collectors/limit_up_collector.py`
- `src/market/collectors/market_breadth_collector.py`

完成标准：

- 指定交易日可采集并落库
- 至少以下表有数据：
  - `daily_stock_quotes`
  - `daily_board_quotes`
  - `daily_stock_limits`
  - `daily_market_breadth`

可中断点：

- 只要原始市场数据成功落库，即可暂停

验收方式：

- 指定某日后，数据库中股票、板块、涨停、宽度四类表均有记录

## 阶段 C：新闻入库与关联增强

目标：

- 将现有新闻链路纳入数据库
- 建立新闻与股票/题材的关联

范围：

- 财联社
- 韭菜公社
- 股票和题材映射

建议文件：

- 复用现有 scraper
- 新增新闻入库适配层
- 新增新闻解析增强逻辑

完成标准：

- `news_items` 有数据
- `news_item_symbols` 有数据
- `news_item_themes` 有数据

可中断点：

- 新闻条目和映射关系完成入库即可暂停

验收方式：

- 任意抽查一条财联社和一条韭菜公社记录，能关联到股票或题材

## 阶段 D：基础特征构建

目标：

- 为板块和股票生成可评分的基础特征

范围：

- 板块基础特征
- 股票基础特征

建议文件：

- `src/market/features/board_feature_builder.py`
- `src/market/features/stock_feature_builder.py`
- `src/market/features/news_feature_builder.py`

完成标准：

- `daily_board_features` 有数据
- `daily_stock_features` 有数据

最低要求字段：

- 板块：
  - `board_score`
  - `news_heat_score`
  - `limit_up_count`
  - `continuity_score`

- 股票：
  - `news_heat_score`
  - `dragon_score`
  - `center_score`
  - `follow_score`
  - `risk_score`
  - `final_score`

可中断点：

- 特征成功落库即可暂停

验收方式：

- 能查询某个交易日的板块分和股票分

## 阶段 E：20只观察池筛选

目标：

- 从特征表里筛出每日重点观察池

范围：

- 角色划分
- Top20 组合

建议文件：

- `src/market/ranker/board_ranker.py`
- `src/market/ranker/stock_ranker.py`
- `src/market/ranker/selector.py`

完成标准：

- `daily_observation_pool` 有 20 条 `top20`
- 每条记录有角色、分数、入选理由、风险标签

可中断点：

- 观察池成功入库即可暂停

验收方式：

- 指定交易日，`top20` 正好 20 条
- 角色分布基本符合预期

## 阶段 F：日报输出

目标：

- 生成可读日报

范围：

- JSON 报告
- Markdown 报告

建议文件：

- `src/market/report/daily_report_generator.py`

完成标准：

- 输出日报文件
- 报告包含市场总览、主线板块、重点观察 20 只、风险提示

可中断点：

- 日报生成成功即可暂停

验收方式：

- 输出文件存在
- 内容结构完整

## 阶段 G：观察跟踪

目标：

- 形成最小闭环

范围：

- 1日、3日、5日跟踪

建议文件：

- `src/backtest/observer_tracker.py`

完成标准：

- `observation_tracking` 有数据
- 可回查任一观察池股票后续表现

可中断点：

- 跟踪表生成成功即可暂停

验收方式：

- 任意一只入池股票可查到后续 1/3/5 日表现

---

## 18. 最小执行顺序

如果按最稳妥路线执行，推荐严格按以下顺序：

1. 阶段 A：数据库底座
2. 阶段 B：市场基础采集
3. 阶段 C：新闻入库与关联增强
4. 阶段 D：基础特征构建
5. 阶段 E：20只观察池筛选
6. 阶段 F：日报输出
7. 阶段 G：观察跟踪

不要跳序。原因：

- 没有数据库底座，后续流程会反复返工
- 没有事实数据，特征构建会变成空转
- 没有特征层，观察池筛选无法稳定
- 没有观察池，日报和跟踪没有意义

---

## 19. 每阶段输入/输出定义

为保证可中断、可恢复，每阶段的输入输出固定如下。

### 阶段 A

输入：

- 配置文件

输出：

- `market_daily.db`
- 已创建的数据库表

### 阶段 B

输入：

- 数据库
- 交易日参数
- 市场数据源

输出：

- `daily_stock_quotes`
- `daily_board_quotes`
- `daily_stock_limits`
- `daily_market_breadth`

### 阶段 C

输入：

- 财联社/韭菜公社抓取结果
- 数据库

输出：

- `news_items`
- `news_item_symbols`
- `news_item_themes`

### 阶段 D

输入：

- 市场事实表
- 新闻事实表

输出：

- `daily_board_features`
- `daily_stock_features`

### 阶段 E

输入：

- 板块特征
- 股票特征

输出：

- `daily_observation_pool`

### 阶段 F

输入：

- 市场宽度
- 板块特征
- 观察池

输出：

- `market_daily_YYYYMMDD.json`
- `market_daily_YYYYMMDD.md`

### 阶段 G

输入：

- 历史观察池
- 后续行情

输出：

- `observation_tracking`

---

## 20. 开发时的约束

为了保证后续维护成本可控，建议开发时遵守以下约束：

- 所有阶段都支持按交易日重跑
- 重跑时采用 upsert，不重复插入
- 原始事实表不混入评分字段
- 评分逻辑尽量写在特征/排序模块，不写死在采集器里
- 报告生成器不直接依赖外部接口，只读数据库和产出文件
- 所有关键中间结果都能单独检查

---

## 21. 建议你后续如何按文档执行

后续可以严格按以下方式推进：

1. 先只做阶段 A，验收后停止
2. 再做阶段 B，验收后停止
3. 再做阶段 C 和 D，验收后停止
4. 再做阶段 E 和 F，验收后停止
5. 最后做阶段 G

这样可以保证：

- 每一步都可控
- 每一步都容易 review
- 不会一口气铺太大导致后期难以修正

如果后续继续扩展，优先补：

- 资金流
- 封板细节
- 龙虎榜
- 更精细的板块持续性因子
