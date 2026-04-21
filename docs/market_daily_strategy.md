# 市场观察日报策略文档

## 1. 文档目的

这份文档描述当前 `FinCrawlerAI` 项目里“市场观察日报”策略的真实实现口径。重点不是泛泛而谈“看情绪、看主线、看龙头”，而是明确说明：

- 数据从哪里进入系统
- 每一层如何加工
- 板块和个股是怎么打分的
- 观察池是怎么筛出来的
- 日报页面展示的字段到底来自哪里
- 当天数据不完整时应该如何回补和重跑

本文档对应的是当前代码实现，而不是理想化设计稿。

## 2. 策略目标

当前策略的目标不是做自动交易信号，也不是做严格意义上的量化回测因子库，而是做一套**交易日级别的市场结构观察系统**。它试图回答四个问题：

1. 今天市场处于什么阶段
2. 今天最强的主线板块是谁
3. 主线内部谁更像龙头、中军、扩散或补位
4. 最后应该把哪 20 只股票放进重点观察池

因此，这套策略本质上是一个**盘后复盘 + 次日盘前观察框架**。它的输出结果是：

- 板块级强度排序
- 个股级角色分层
- Top20 观察池
- Backup 备选池
- HTML 日报页面

## 3. 整体链路

服务器上的完整执行入口是：

- [run_market_daily_job.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/scripts/run_market_daily_job.py:108)

完整链路按顺序分为六层：

1. 采集层：收集股票日线、涨停池、板块行情、新闻、热度等原始数据
2. 归属层：建立股票和行业板块的映射关系
3. 板块层：计算板块强度、阶段、热度和延续性
4. 个股层：对每只股票计算龙头分、中军分、跟随分、风险分和最终分
5. 选择层：把高分个股按角色配额和板块约束装入观察池
6. 展示层：生成 JSON / Markdown / HTML 并发布到 Web 目录

## 4. 数据底座

当前策略最核心的数据表包括：

- `daily_stock_quotes`：股票日线行情
- `daily_stock_limits`：涨停、炸板、连板等信息
- `stock_board_membership`：股票与板块映射
- `daily_board_quotes`：板块行情
- `daily_market_breadth`：市场总览
- `news_items` / `news_item_symbols` / `news_item_themes`：新闻及其股票、题材映射
- `daily_stock_attention`：热度、连涨、突破、新高等关注度数据
- `daily_board_features`：板块特征结果
- `daily_stock_features`：个股特征结果
- `daily_observation_pool`：最终观察池

在策略视角里，可以把这些表分成三类：

- 原始输入：`daily_stock_quotes`、`daily_stock_limits`、`news_items`、`daily_stock_attention`
- 中间层特征：`daily_board_features`、`daily_stock_features`
- 最终结果：`daily_observation_pool`

## 5. 采集层口径

### 5.1 行情数据

股票日线的主表是 `daily_stock_quotes`。每个交易日按 `(trade_date, symbol)` 唯一约束写入，因此同一天回跑不会产生重复行，而是补齐缺失数据或更新已有数据。

这个设计的意义是：

- 支持断点续跑
- 支持补数据
- 支持同一天回补后重建日报

### 5.2 涨停和情绪数据

`daily_stock_limits` 提供：

- 是否涨停
- 是否炸板
- 连板高度
- 涨停原因

这些字段在个股角色判断里很重要，尤其影响：

- 龙头候选识别
- 风险识别
- 观察点生成

### 5.3 新闻和题材数据

新闻数据进入 `news_items`，再通过：

- `news_item_symbols` 关联股票
- `news_item_themes` 关联题材

当前策略里，新闻不直接“下结论”，而是作为热度和逻辑增强项。尤其会把 `jygs` 数据拆出更细的信号，例如：

- `core_signal`
- `follow_signal`
- `streak_signal`
- `risk_signal`

### 5.4 关注度和技术形态数据

`daily_stock_attention` 用来补充“市场注意力”和“技术状态”，当前会汇总这些维度：

- 东财热股排名
- 东财飙升榜排名
- 雪球关注人数
- 雪球讨论热度
- THS 新高
- THS 连涨
- THS 突破标签

这部分不决定主线，但会影响个股得分和入选理由描述。

## 6. 板块层策略

板块特征构建入口：

- [board_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/board_feature_builder.py:19)

板块层要解决两个问题：

1. 哪些板块是今天的强板块
2. 强度所处阶段是启动、扩散、加速还是衰退

### 6.1 板块特征组成

当前 `board_score` 由以下部分综合得到：

- 板块涨跌幅强度
- 涨停家数强度
- 板块内部涨多跌少的广度
- 新闻热度
- 龙头强度
- 容量中军强度
- 近 5 日延续性

代码口径见：

- [board_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/board_feature_builder.py:335)

实际公式为：

```text
board_score =
  0.20 * pct_strength
  + 0.20 * limit_strength
  + 0.15 * breadth_score
  + 0.15 * news_heat_score
  + 0.15 * dragon_strength
  + 0.10 * center_strength
  + 0.05 * continuity_score
```

其中还会对负涨幅板块做惩罚：

- 板块下跌时整体分数打折
- 下跌较深时再次打折
- 涨停数很少且板块下跌时继续打折

这意味着当前策略天然倾向于：

- 喜欢上涨中的板块
- 喜欢有涨停、有龙头、有容量的板块
- 讨厌单日冲高但整体转弱的板块

### 6.2 板块内部子分项

#### 6.2.1 广度分 `breadth_score`

由两部分组成：

- 板块涨跌幅转换得到的 `pct_score`
- 上涨家数占比转换得到的 `breadth_ratio_score`

因此，板块不是只看指数涨幅，而是兼顾“板块内部是否普涨”。

#### 6.2.2 龙头强度 `dragon_strength`

由以下因素组成：

- 龙头涨幅
- 板块内最高连板数
- 板块内涨停股数量

代码口径见：

- [board_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/board_feature_builder.py:320)

这体现了策略对“领涨核心”的偏好。

#### 6.2.3 中军强度 `center_strength`

由以下因素组成：

- 板块总成交额
- 板块内最大成交额个股

这意味着策略不仅关注情绪爆点，也关注容量承接。

#### 6.2.4 延续性 `continuity_score`

基于该板块历史最近 5 个交易日的表现：

- 正收益天数越多越好
- 平均涨幅越高越好

这一步是为了避免只看当天脉冲。

### 6.3 板块阶段 `phase_hint`

板块阶段不是单独输入，而是由板块分数、涨跌幅、涨停数和延续性共同推断，取值包括：

- `accelerate`
- `expand`
- `start`
- `fade`

代码口径见：

- [board_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/board_feature_builder.py:367)

大体含义是：

- `accelerate`：强板块继续加速
- `expand`：主线从核心向外扩散
- `start`：板块刚形成启动迹象
- `fade`：板块转弱或处于退潮

后续个股角色允许与否，会强依赖这个阶段判断。

## 7. 个股层策略

个股特征构建入口：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:19)

个股层的核心思想不是“给每只股票一个统一打分”，而是先分别计算三类角色分：

- 龙头分 `dragon_score`
- 中军分 `center_score`
- 扩散分 `follow_score`

然后再根据角色适配条件选出该股更像什么角色，最后计算 `final_score`。

### 7.1 个股输入特征

当前个股计算会用到以下信息：

- 当日涨跌幅
- 成交额
- 换手率
- 振幅
- 总市值 / 流通市值
- 是否涨停 / 是否炸板 / 连板高度
- 所属行业板块
- 板块参考分 `board_score_ref`
- 板块阶段 `board_phase_hint`
- 近 20 日涨停次数
- 近 3 日 / 5 日收益
- 新闻热度
- 韭研公社信号
- 热度 / 新高 / 连涨 / 突破等 attention 数据

### 7.2 龙头分 `dragon_score`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:530)

核心加分项包括：

- 当日涨幅
- 是否涨停
- 连板高度
- 所属板块强度
- 新闻热度
- 韭研公社核心信号
- 热度关注度

并且在不同板块阶段下会乘以系数：

- `fade` 明显打折
- `start` 和 `accelerate` 略微放大

因此，龙头分本质上是在找：

- 身位高
- 辨识度强
- 板块支持强
- 叙事和热度同步强化

的股票。

### 7.3 中军分 `center_score`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:550)

中军更偏容量和承接，核心加分项包括：

- 成交额
- 市值区间适配
- 在板块内的成交额排名
- 近 3 日趋势延续
- 板块强度
- 新闻和关注度
- 技术面 bonus

这意味着：

- 不是最会涨的股票才是中军
- 而是有容量、有趋势、有板块支撑的承接核心

### 7.4 扩散分 `follow_score`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:579)

扩散分更偏“主线外溢过程中的受益股”，核心因素包括：

- 当前涨幅
- 所属板块强度
- 最近 3 日动量
- 近 20 日涨停次数的新鲜度
- 韭研公社扩散信号
- 热度关注度

策略会偏好：

- 跟得上主线
- 但还没有过度消耗
- 并且处于主线扩散阶段的个股

### 7.5 风险标记 `risk_flags`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:657)

当前风险标签包括：

- `high_streak`：连板过高
- `high_turnover`：换手过高
- `high_amplitude`：振幅过大
- `isolated_spike`：单股暴冲但板块不够强
- `weak_close`：弱收
- `fading_board`：所在板块退潮

风险分是按标签加权求和得到的。它不会单独决定角色，但会：

- 影响最终总分
- 限制角色分配
- 进入观察池的风险提示文本

### 7.6 角色选择 `role_tag`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:693)

当前角色包括：

- `dragon`
- `center`
- `follow`
- `watchlist`

这一步不是单纯看三种得分谁最高，而是先判断“有没有资格成为某类角色”。

例如：

- 龙头必须处于 `start / expand / accelerate`
- 龙头不能落在 `fading_board`
- 中军要求成交额足够大、板块内成交额排名靠前、近 3 日趋势为正
- 扩散要求主线阶段允许，且不能是退潮板块

如果没有任何角色通过门槛，或者最高角色分低于 20，则归为 `watchlist`。

这一步非常重要，因为它保证了：

- 角色不是简单按分数硬分
- 而是先满足交易语义，再看分数高低

### 7.7 最终分 `final_score`

代码口径见：

- [stock_feature_builder.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/features/stock_feature_builder.py:739)

公式很直接：

```text
final_score = role_score + board_score_ref * 0.2 + news_heat_score * 0.1 - risk_score
```

其中 `role_score` 取决于当前角色：

- 龙头取 `dragon_score`
- 中军取 `center_score`
- 扩散取 `follow_score`
- 观察补位取三者最大值

所以 `final_score` 是一套**带板块加成和风险扣分的角色总分**，而不是纯行情分。

## 8. 观察池选择策略

观察池构建入口：

- [selector.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/ranker/selector.py:18)

### 8.1 目标结构

当前 Top20 观察池采用角色配额制：

- 龙头 `6`
- 中军 `6`
- 扩散 `6`
- 观察补位 `2`

如果某类角色不够，再从全市场高分股里补足到 20 只。

### 8.2 板块约束

为了避免观察池全被单一板块塞满，当前有两个限制：

- 单一板块最多 `6` 只
- 单一板块内同一角色最多 `2` 只

这体现了策略在“主线集中”和“适度分散”之间的折中。

### 8.3 主线优先

角色候选默认优先从前 10 个板块中选。如果前 10 板块里某类角色不够，才会退回到全市场同角色股票里补。

这说明当前观察池不是单纯全市场取前 20 名，而是：

- 先强调主线板块
- 再强调角色完整性
- 最后再考虑整体分数

### 8.4 备选池

除 Top20 外，还会顺手生成 10 只 `backup`。

备选池不是随机候补，而是：

- 从未进入 Top20 的高分股中顺位取前 10
- 用于轮动补位和第二梯队观察

## 9. 文案与展示层策略

HTML 日报生成入口：

- [daily_report_generator.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/report/daily_report_generator.py:289)

当前页面展示并不是简单查表，而是把策略结果进一步包装成：

- 市场总览
- 策略决策链路
- 主线板块
- 重点观察 20 只
- 结构分布
- 备选池

其中个股卡片里的几项核心文案：

- `selected_reason`
- `watch_points`
- `risk_flags`

来自观察池构建阶段，不是前端硬编码。

对应代码：

- [selector.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/ranker/selector.py:180)
- [selector.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/ranker/selector.py:211)
- [selector.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/src/market/ranker/selector.py:283)

这一步的意义是把量化特征翻译成可读的交易语言，例如：

- “高强度龙头候选”
- “容量中军候选”
- “板块扩散跟随候选”
- “观察补位候选”

以及：

- “观察是否继续涨停或维持高辨识度”
- “观察成交额与趋势承接是否延续”
- “留意板块热度回落”

所以页面本身是策略结果的解释层，不是独立逻辑层。

## 10. 数据不完整时的处理策略

这是当前系统最重要的运行问题之一。

### 10.1 什么叫“不完整”

最典型的场景是：

- 某天 `daily_stock_quotes` 只采到一部分股票
- 数量明显低于正常交易日水平
- 但你已经继续算了板块、个股和日报

这时后续输出都会失真，因为：

- 板块成员行情不全，板块分会失真
- 市场总览失真
- 个股角色判断失真
- 观察池也会失真

### 10.2 是否会重复入库

不会。因为主表设计为幂等写入：

- `daily_stock_quotes` 以 `(trade_date, symbol)` 唯一
- 入库逻辑走 `upsert`

所以回头重跑同一天时：

- 已有数据不会重复新增
- 缺失股票会补齐
- 已存在数据可以被更新

### 10.3 正确的回补方式

补当天数据后，不能只重新生成 HTML，必须重跑整条策略链路。

服务器上应直接执行：

```bash
cd /opt/FinCrawlerAI
. .venv/bin/activate
python scripts/run_market_daily_job.py \
  --date 2026-03-19 \
  --base-url http://你的公网地址
```

如果需要一起补新闻和热度：

```bash
cd /opt/FinCrawlerAI
. .venv/bin/activate
python scripts/run_market_daily_job.py \
  --date 2026-03-19 \
  --base-url http://你的公网地址 \
  --with-news \
  --news-sources jygs,cailian \
  --with-attention
```

这会依次重跑：

- 行情采集
- 板块成员归属
- 板块行情构建
- 板块特征
- 个股特征
- 观察池
- HTML 和首页

## 11. 当前策略的优点

### 11.1 优点一：结构完整

当前实现不是单点选股器，而是一个完整框架：

- 从市场层到板块层再到个股层
- 从打分到角色再到观察池
- 从数据库到页面展示

### 11.2 优点二：可解释性强

每只入池股票都有：

- 角色
- 板块归属
- 分数
- 入选原因
- 观察要点
- 风险标签

这比单一排行榜更适合做复盘和群分享。

### 11.3 优点三：支持回补和重算

底层表采用幂等写入，中间层和结果层支持按日重建，因此系统天然支持：

- 当天回补
- 历史重跑
- 报告修正

## 12. 当前策略的局限

### 12.1 局限一：更偏盘后观察，不是严格交易系统

当前得分更像“观察优先级”，而不是“买卖点信号”。它擅长告诉你今天该盯谁，不擅长直接告诉你什么时候买、什么时候卖。

### 12.2 局限二：高度依赖数据完整性

只要当日行情、板块归属或涨停数据缺失，后面所有层都会偏差。

### 12.3 局限三：角色划分依赖手工规则

当前角色门槛和权重都是规则驱动，优点是透明，缺点是：

- 参数需要持续调
- 不同市场阶段下未必总是最优

### 12.4 局限四：行业板块口径较强

当前主板块逻辑主要依赖 `industry_csrc`，这更适合行业主线，不一定完全覆盖事件驱动型短题材。

## 13. 后续优化方向

如果后面继续迭代，这套策略建议优先优化以下四件事。

### 13.1 优先做数据完整性闸门

在生成日报之前先判断：

- `daily_stock_quotes` 数量是否达标
- 板块成员覆盖是否达标
- `daily_market_breadth` 是否生成成功

不达标就拒绝生成正式日报。

### 13.2 增加“正式版 / 临时版”区分

当日数据未完成时，可以生成：

- 临时版：仅自己看
- 正式版：数据完整后再对外分享

### 13.3 为角色增加历史验证

后续可以把：

- Top20 次日表现
- 不同角色的命中率
- 不同板块阶段下的表现

回写到统计表里，形成策略闭环。

### 13.4 增加首页级运营能力

如果未来要接广告、做群传播，建议首页继续增强：

- 最新日报入口
- 历史归档
- 赞助位
- 风险声明
- 访问统计

## 14. 一句话总结

当前“市场观察日报”策略是一套**以板块强度为主线、以角色分层为核心、以观察池为最终输出的交易日级观察系统**。

它的逻辑核心不是“预测哪只股票一定涨”，而是：

- 先判断市场和主线
- 再判断主线内部谁是龙头、中军、扩散
- 最后把最值得跟踪的 20 只股票整理成一份可复盘、可传播、可持续迭代的日报

从工程角度看，这套策略当前已经具备：

- 完整数据链路
- 幂等回补能力
- 可解释的打分结构
- 可直接对外分发的 HTML 产物

接下来最需要补的不是再加更多花哨因子，而是先把**数据完整性闸门、正式版口径和后验验证闭环**补齐。
