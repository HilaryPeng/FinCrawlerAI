# FinCrawlerAI

当前项目已经收敛成一套可用的 **A 股日频市场观察系统**。

主链路：

- 采集市场数据
- 入库到本地 SQLite
- 构建板块 / 个股特征
- 生成核心标的池
- 生成 HTML 日报
- 部署到服务器
- 可选推送飞书

数据库默认仍保留在本地机器，服务器主要用于：

- 托管 HTML 页面
- 保留数据快照
- 后续可切换为服务器本地定时跑

## OpenSpec

- 正式规则源位于 `openspec/specs/`
- 影响日报结果的改动，先在 `openspec/changes/` 建 proposal，再改代码
- 运行时会直接读取 `strategy` / `runtime` / `presentation` 当前 spec

校验命令：

```bash
python scripts/validate_market_daily_spec.py
```

## 1. 当前核心目录

```text
FinCrawlerAI/
├── config/
├── data/
│   ├── db/
│   ├── processed/market_daily/
│   └── raw/
├── docs/
├── logs/
├── scripts/
└── src/
```

## 2. 最常用脚本

### 2.1 初始化数据库

```bash
python scripts/init_market_db.py
```

### 2.2 采集当天市场数据

```bash
python scripts/collect_market_data.py --date 2026-03-31 --with-news --news-sources jygs --with-attention
```

说明：

- `--with-news`：采集新闻
- `--news-sources jygs`：当前建议先用韭菜公社
- `--with-attention`：采集热度 / 技术榜单

### 2.3 补行业 membership

```bash
python scripts/collect_board_membership.py --date 2026-03-31 --source baostock
```

### 2.4 生成统一行业板块快照

```bash
python scripts/build_unified_board_quotes.py --date 2026-03-31
```

### 2.5 构建特征

```bash
python scripts/build_daily_features.py --date 2026-03-31
```

### 2.6 生成观察池

```bash
python scripts/build_observation_pool.py --date 2026-03-31
```

### 2.7 生成日报

```bash
python scripts/generate_market_daily_report.py --date 2026-03-31
python scripts/generate_market_daily_index.py
```

## 3. 本地一键流程

如果你还保持“本地跑数据库 + 服务器只展示页面”的模式，日常顺序是：

```bash
python scripts/collect_market_data.py --date 2026-03-31 --with-news --news-sources jygs --with-attention
python scripts/collect_board_membership.py --date 2026-03-31 --source baostock
python scripts/build_unified_board_quotes.py --date 2026-03-31
python scripts/build_daily_features.py --date 2026-03-31
python scripts/build_observation_pool.py --date 2026-03-31
python scripts/generate_market_daily_report.py --date 2026-03-31
python scripts/generate_market_daily_index.py
```

## 4. 部署 HTML 到服务器

```bash
python scripts/deploy_market_daily_report.py \
  --date 2026-03-31 \
  --host 167.179.78.250 \
  --user root \
  --publish-index
```

## 5. 同步本地数据到服务器

如果数据库仍保留在本地，但你想把本地 `data/` 全量备份到服务器：

```bash
python scripts/sync_market_data_snapshot.py \
  --host 167.179.78.250 \
  --user root
```

同步结果：

- 服务器保留时间戳快照
- 同时更新一个 `latest` 软链
- 本地数据不会删除

## 6. 服务器本地日跑

如果后面切换成“服务器自己每天跑”，直接用：

```bash
python scripts/run_market_daily_job.py \
  --date 2026-03-31 \
  --base-url http://你的服务器IP或域名 \
  --with-news \
  --news-sources jygs \
  --with-attention \
  --check-trade-date \
  --notify-feishu
```

这条会：

- 检查是否 A 股交易日
- 跑完整条市场链路
- 发布到 nginx
- 推送飞书

## 7. 推荐 cron

每天晚上 21:00 运行，由脚本自己判断是不是 A 股开盘日：

```cron
0 21 * * * cd /opt/FinCrawlerAI && . .venv/bin/activate && python scripts/run_market_daily_job.py --date $(date +\%F) --base-url http://你的服务器IP或域名 --with-news --news-sources jygs --with-attention --check-trade-date --notify-feishu >> logs/server_daily_job.log 2>&1
```

## 8. 配置

本地配置文件：

```python
# config/local_settings.py
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/<YOUR_WEBHOOK_TOKEN>"
FEISHU_SECRET = ""

JYGS_PHONE = "<YOUR_PHONE>"
JYGS_PASSWORD = "<YOUR_PASSWORD>"
JYGS_TOKEN_SEED_PREFIX = ""

SERVER_HOST_ALIAS = "fincrawler-vps"
SERVER_HOST = "你的服务器IP"
SERVER_SSH_USER = "root"
SERVER_SSH_PORT = 22
SERVER_BASE_URL = "http://你的服务器IP"
```

## 9. 相关文档

- 项目说明：`docs/project_overview.md`
- 配置说明：`docs/configuration_guide.md`
- 当前实现状态：`docs/market_daily_current_state.md`
- 设计文档：`docs/market_daily_system_design.md`
- 服务器部署：`docs/server_daily_run.md`
- 本地开机自启：`docs/local_launchd_run.md`
