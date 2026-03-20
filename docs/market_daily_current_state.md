# 日频市场观察系统当前实现状态

## 1. 文档用途

这份文档记录当前项目里“已经真实落地”的市场观察系统实现状态，供：

- 后续 AI 接手时快速理解上下文
- 你自己回头查看当前系统到底做到了哪里
- 后续优化逻辑时区分“设计目标”和“现状实现”

和 [market_daily_system_design.md](./market_daily_system_design.md) 的区别是：

- 设计文档：描述目标架构和实施计划
- 当前状态文档：描述已经实现的代码、数据口径、命令、已知问题

---

## 2. 当前结论

当前项目已经具备一个可用的日频闭环：

`采集 -> 入库 -> 特征 -> 观察池 -> 日报 -> HTML 页面 -> 服务器部署`

也就是说，系统已经从“想法和脚本试验”进入“可以每天跑结果”的阶段。

当前更适合做的事是：

- 优化数据质量
- 优化角色识别和选择器逻辑
- 增强新闻层
- 做观察跟踪

而不是继续无边界扩模块。

---

## 3. 当前阶段状态

### A. 数据库底座

状态：`已完成`

已实现：

- SQLite 数据库
- schema 初始化
- repository / upsert
- 日频表设计

核心目录：

- `src/db/connection.py`
- `src/db/schema.py`
- `src/db/repository.py`

数据库文件：

- `data/db/market_daily.db`

### B. 市场基础采集

状态：`已完成，可用`

已实现：

- 股票日线
- 板块快照
- 涨停池
- 市场宽度
- 行业板块归属

核心目录：

- `src/market/collectors/quotes_collector.py`
- `src/market/collectors/boards_collector.py`
- `src/market/collectors/limit_up_collector.py`
- `src/market/collectors/market_breadth_collector.py`

### C. 新闻入库与关联增强

状态：`链路完成，数据量仍偏小`

已实现：

- `news_items`
- `news_item_symbols`
- `news_item_themes`
- 股票/主题提取

但当前库里新闻量仍然只有测试级别，新闻层还没有进入高质量生产状态。

### D. 特征构建

状态：`已完成`

已实现：

- 板块特征
- 股票特征
- 角色分
- 风险分

核心目录：

- `src/market/features/board_feature_builder.py`
- `src/market/features/stock_feature_builder.py`

### E. 20只观察池

状态：`已完成`

已实现：

- 板块/股票 ranker
- 观察池选择器
- `top20 + backup10`

核心目录：

- `src/market/ranker/board_ranker.py`
- `src/market/ranker/stock_ranker.py`
- `src/market/ranker/selector.py`

### F. 日报输出

状态：`已完成`

已实现：

- JSON
- Markdown
- HTML 页面

核心目录：

- `src/market/report/daily_report_generator.py`
- `scripts/generate_market_daily_report.py`

### G. 观察跟踪

状态：`尚未正式实现`

也就是说：

- 系统已经能每天产出观察池
- 但后续 1/3/5 日观察闭环还没做完

---

## 4. 当前代码入口

### 数据库初始化

```bash
python scripts/init_market_db.py
```

### 只跑股票日线

```bash
python scripts/collect_quotes_only.py --date 2026-03-19
```

说明：

- 脚本内部会清理常见代理环境变量
- 支持断点续跑
- 已存在的 `symbol` 会自动跳过

### 补行业 membership

```bash
python scripts/collect_board_membership.py --date 2026-03-19 --source baostock
```

### 生成统一 CSRC 行业板块快照

```bash
python scripts/build_unified_board_quotes.py --date 2026-03-19
```

### 构建特征

```bash
python scripts/build_daily_features.py --date 2026-03-19
```

### 生成观察池

```bash
python scripts/build_observation_pool.py --date 2026-03-19
```

### 生成日报

```bash
python scripts/generate_market_daily_report.py --date 2026-03-19
```

### 生成日报索引页

```bash
python scripts/generate_market_daily_index.py
```

### 部署日报到服务器

```bash
python scripts/deploy_market_daily_report.py \
  --date 2026-03-19 \
  --host 167.179.78.250 \
  --user root \
  --publish-index
```

---

## 5. 当前核心表

### 已在用

- `daily_stock_quotes`
- `daily_board_quotes`
- `daily_stock_limits`
- `daily_market_breadth`
- `stock_board_membership`
- `news_items`
- `news_item_symbols`
- `news_item_themes`
- `daily_board_features`
- `daily_stock_features`
- `daily_observation_pool`

### 尚未真正发挥作用

- 新闻层的真实生产数据量还不够
- 观察跟踪类表还没有正式落地

---

## 6. 当前数据源口径

### 股票日线

主链路：

- `AkShare -> stock_zh_a_daily()`

fallback：

- `AkShare -> stock_zh_a_hist_tx()`

说明：

- 之前 `stock_zh_a_hist()` 在当前环境不稳定，已经弃用为主路径
- 现在 `quotes_collector` 对 AkShare 的 `requests.get` 增加了默认超时保护，避免单个 symbol 无限卡死

### 板块快照

主链路：

- `THS / AkShare` 行业、概念板块快照

说明：

- `EM` 板块接口在当前环境不稳定
- `THS` 板块快照当前可用性更好

### 行业 membership

主链路：

- `BaoStock`

板块类型：

- `industry_csrc`

说明：

- 当前 membership 来自证监会行业分类
- 这是当前系统里最稳定的免费行业归属来源

### 板块统一策略

当前项目不是强行把所有板块来源统一成一个名字体系，而是保留两层：

1. 热点板块快照
- `daily_board_quotes`
- `board_type=industry/concept`
- `source=akshare_ths`

2. 统一行业归属与行业快照
- `stock_board_membership`
- `board_type=industry_csrc`
- `source=baostock`

- `daily_board_quotes`
- `board_type=industry_csrc`
- `source=derived_baostock`

这样做的目的：

- 保留热点板块视角
- 保证股票和行业板块有一套稳定可 join 的统一底座

---

## 7. 当前真实数据状态

以下内容会随运行变化，但目前系统大体处于以下状态：

- `2026-03-16` 已有完整 quotes，并已补齐 features / observation pool / report
- `2026-03-18` 是最早一批完整跑通的数据日
- `2026-03-19` 已在网络恢复后补齐到完整量级，并已重新生成页面

当前已生成的日报文件目录：

- `data/processed/market_daily/`

当前已生成 HTML：

- `market_daily_20260316.html`
- `market_daily_20260318.html`
- `market_daily_20260319.html`
- `market_daily_index.html`

---

## 8. 当前服务器部署状态

服务器：

- `167.179.78.250`

当前部署方式：

- `nginx`
- Web 根目录：`/var/www/html`

当前页面：

- 首页索引：`http://167.179.78.250/`
- 历史索引页：`http://167.179.78.250/market_daily_index.html`
- 单日报页面：`/market_daily_YYYYMMDD.html`

已验证可访问的页面：

- `http://167.179.78.250/market_daily_20260316.html`
- `http://167.179.78.250/market_daily_20260318.html`
- `http://167.179.78.250/market_daily_20260319.html`

---

## 9. 当前实现的主要限制

### 9.1 新闻层还太弱

问题：

- `news_items` 数据量仍偏小
- 新闻还没有成为高质量评分输入

影响：

- 当前系统仍然主要依赖行情/板块/涨停，不是完整“新闻驱动观察系统”

### 9.2 `market_breadth` 存在已知 bug

当前已知问题：

- 从 `daily_stock_quotes` 聚合市场汇总时，会报：
  - `'numpy.ndarray' object has no attribute 'fillna'`

影响：

- `up_count/down_count/limit_up_count` 还能写
- 但 `total_amount` 等部分 summary 字段并不稳定

这是当前最明确需要修的 bug 之一。

### 9.3 观察池去集中化不足

当前问题：

- 选择器容易让观察池过度集中在某个单一板块

影响：

- 观察池更像“单板块强势股列表”
- 不够像真正的“市场观察池”

### 9.4 概念 membership 不完整

当前行业 membership 已有稳定来源，但概念板块成分仍不稳定。

影响：

- 行业层已可用
- 概念层的股票归属能力还不够强

### 9.5 观察跟踪尚未正式实现

现在系统已经能选出 20 只，但还没有：

- 1 日跟踪
- 3 日跟踪
- 5 日跟踪
- 最大涨幅 / 最大回撤

---

## 10. 当前最值得做的优化顺序

建议后续按下面顺序继续：

1. 修 `market_breadth` bug
2. 提升新闻层数据量和可用性
3. 优化角色识别逻辑
4. 优化 20 只观察池去集中化
5. 实现观察跟踪 G 阶段
6. 最后再优化 AI 解释层

原因：

- 先把底层数据和打分逻辑修稳
- 再优化阅读体验和 AI 输出

### 当前达成共识的 4 个重点

为了避免后续优化发散，当前先固定只做这 4 件事：

1. 先修数据底座
   - 修 `market_breadth` bug
   - 加数据完整性检查
   - 提升 quotes 稳定性

2. 强化量价 + 角色判断
   - 让 `龙头 / 中军 / 补涨` 更依赖量价行为和板块地位
   - 不再单纯依赖静态总分

3. 优化 20 只观察池
   - 解决单板块过度集中
   - 让观察池更像“市场地图”

4. 做观察跟踪闭环
   - 增加 1/3/5 日观察结果
   - 用结果反推评分和筛选逻辑

---

## 11. AI 接手时应优先知道的事实

如果后续有 AI 继续接手本项目，优先应知道：

1. 当前系统已经不是从 0 开始，而是 A~F 基本打通
2. 当前最重要的不是继续扩模块，而是优化逻辑质量
3. `industry_csrc` 是当前最稳定的股票行业归属口径
4. `THS` 板块快照当前可用，但 `EM` 和 `THS detail membership` 都不稳定
5. `2026-03-16`、`2026-03-18`、`2026-03-19` 已有可用日报页面
6. `market_breadth` 聚合 bug 是当前明确缺陷
7. `quotes_collector` 已支持断点续跑和超时保护

---

## 12. 建议阅读顺序

如果是第一次接手当前代码，建议按这个顺序看：

1. 本文档：`docs/market_daily_current_state.md`
2. 设计文档：`docs/market_daily_system_design.md`
3. 采集层：
   - `src/market/collectors/`
4. 特征层：
   - `src/market/features/`
5. 选择器：
   - `src/market/ranker/`
6. 输出层：
   - `src/market/report/`
7. 命令脚本：
   - `scripts/`

这样能最快建立完整上下文。
