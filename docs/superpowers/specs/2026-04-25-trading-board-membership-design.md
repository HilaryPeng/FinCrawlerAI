# 交易型板块归属增强设计（2026-04-25）

## 背景

强势股池已经能按个股强度筛出主池和备选池，但当前报告里的强势股聚集度主要使用 `industry_csrc`，也就是证监会行业分类。

这会产生一个问题：

- 报告显示 `C39计算机、通信和其他电子设备制造业`、`C38电气机械和器材制造业`。
- 这些分类适合做行业兜底，但不符合盘面观察习惯。
- 用户真正想看的方向更接近 `CPO`、`PCB概念`、`半导体`、`5G`、`铜缆高速连接`、`东数西算(算力)`。

2026-04-24 本地试验已验证：

- `daily_board_quotes` / `daily_board_features` 已经有同花顺行业与概念板块列表。
- `stock_board_membership` 可以存储 `industry`、`concept`、`industry_csrc` 三类归属。
- 小范围抓取同花顺成分股后，强势股可命中 `共封装光学(CPO)`、`PCB概念`、`5G`、`F5G概念`、`半导体` 等交易型板块。

当前缺口不是“没有板块列表”，而是“没有稳定的个股到交易型板块的归属链路”，以及报告没有优先使用交易型主板块。

## 目标

- 为强势股补充交易型板块归属。
- 报告中优先展示 `concept` / `industry`，不再把 `C38/C39` 作为主展示。
- 仍保留 `industry_csrc` 作为兜底归属。
- 让强势股聚集度更接近盘面语言，例如 `CPO`、`PCB概念`、`半导体`。
- 控制采集成本，避免每天全量抓取数百个板块导致任务不稳定。

## 非目标

- 不重新设计强势股入池分数。
- 不让板块强弱成为个股入池前置条件。
- 不依赖韭菜公社、财联社或新闻题材来决定交易板块。
- 第一版不追求完整覆盖所有概念板块，只做可用、稳定、可回退的重点覆盖。

## 数据来源

已有板块列表：

- `daily_board_quotes`
- `daily_board_features`

已有板块类型：

- `industry`：同花顺/东财交易行业，例如 `半导体`、`电池`、`能源金属`
- `concept`：同花顺/东财概念题材，例如 `共封装光学(CPO)`、`PCB概念`
- `industry_csrc`：证监会行业，例如 `C39计算机、通信和其他电子设备制造业`

成分股补充来源：

- 首选：`ak.stock_board_industry_cons_em`
- 首选：`ak.stock_board_concept_cons_em`
- 降级：同花顺板块详情页

试验结论：

- 东财成分股接口在本地网络下可能断连。
- 同花顺详情页可抓到部分数据，但翻页可能出现 `401/403`。
- 因此第一版必须接受“部分板块、部分页成功”的现实，并设计回退逻辑。

## 方案

### 1. 新增交易型板块成分股补充步骤

新增一个本地重建步骤：

```text
collect_trading_board_memberships(trade_date)
```

它从当天 `daily_board_features` 里选择重点板块，然后写入 `stock_board_membership`。

写入格式复用现有表：

```text
trade_date
symbol
board_name
board_type = concept / industry
is_primary
source
created_at
```

不新增数据库表。

### 2. 重点板块选择规则

第一版不全量抓所有板块，只抓重点集合：

```text
1. concept 板块：按 board_score DESC, pct_chg DESC 取前 80 个
2. industry 板块：按 board_score DESC, pct_chg DESC 取前 40 个
3. 额外强制包含关键词板块：
   CPO、PCB、光通信、通信、算力、铜缆、液冷、服务器、AI、半导体、电池
```

去重后再采集。

设计原因：

- 强势股聚集度只需要解释强票集中方向，不需要完整还原所有概念。
- 重点板块数量可控，失败影响范围小。
- 强制关键词能覆盖当前盘面高频方向。

### 3. 成分股采集策略

每个板块按如下顺序采集：

```text
1. 先尝试东财成分股接口
2. 东财失败或为空时，尝试同花顺详情页
3. 同花顺翻页失败时，保留已抓到的页
4. 单板块抓取失败不影响其它板块
```

每个板块第一版设置软上限：

```text
max_members_per_board = 120
```

原因：

- 同花顺大板块可能有数百只，完整抓取成本高且容易被限流。
- 对强势股主池解释来说，前 120 只通常已能覆盖核心成分。

### 4. 主交易板块选择

强势股报告中新增“主交易板块”概念。

一只股票可能属于多个 `concept` 和 `industry`，第一版只选一个用于主列表与聚集度统计。

选择优先级：

```text
1. concept 优先于 industry
2. industry 优先于 industry_csrc
3. 同类型内按 board_score DESC
4. board_score 相同时按 pct_chg DESC
5. 仍相同时按 board_name ASC
```

回退规则：

```text
如果没有 concept / industry 命中，则使用 industry_csrc。
如果 industry_csrc 也没有，则板块为空。
```

### 5. 附加标签

主列表展示一个主交易板块，同时在个股详情里展示若干附加标签。

附加标签规则：

```text
最多展示 5 个
concept 优先
按 board_score DESC, pct_chg DESC 排序
```

示例：

```text
亨通光电
主交易板块：共封装光学(CPO)
相关标签：6G概念 / F5G概念 / 通信设备
```

### 6. 强势股聚集度

报告里的“强势股板块聚集度”改为优先使用主交易板块。

统计字段保持不变：

```text
board_name
strong_count
strong_amount
avg_strong_score
top_stock_symbol
top_stock_name
top_stock_score
```

但 `board_name` 来源改为：

```text
trading_board_name -> fallback industry_csrc board_name
```

这样聚集度输出会从：

```text
C39计算机、通信和其他电子设备制造业
```

变成：

```text
共封装光学(CPO)
PCB概念
5G
半导体
```

### 7. 运行方式

本地回测或展示重建使用：

```text
1. 已有 daily_stock_quotes
2. 已有 daily_board_quotes / daily_board_features
3. collect_trading_board_memberships(trade_date)
4. build stock features
5. build observation pool
6. generate report
```

第一版不在主日频任务里默认开启全量交易型归属采集。

原因：

- 该链路依赖外部页面，稳定性需要实测。
- 先作为本地/手动增强步骤验证质量。
- 稳定后再决定是否并入服务器日跑。

### 8. 错误处理

采集层：

- 单板块失败只记录日志，不中断整体任务。
- 板块成分抓到部分页即可写入。
- 重跑同一天使用 upsert，不重复写入。

展示层：

- 没有交易型板块时回退到 `industry_csrc`。
- 没有任何板块时显示为空，不影响强势股池输出。

### 9. 测试

新增测试覆盖：

- 交易型板块优先于 `industry_csrc`。
- `concept` 优先于 `industry`。
- 同类型按 `board_score` 和 `pct_chg` 选择主板块。
- 无交易型板块时回退到 `industry_csrc`。
- 聚集度按主交易板块统计。
- 成分股采集失败时不影响已有强势股报告生成。

## 第一版验收标准

- 4/24 强势股主池仍为 30 只，排序不因板块归属改变。
- 报告主列表中出现交易型板块字段。
- 强势股聚集度优先显示 `CPO`、`PCB概念`、`5G`、`半导体` 等交易型板块。
- 没命中交易型板块的股票仍能显示 `C38/C39` 兜底行业。
- 外部板块成分股接口失败时，报告仍可生成。

