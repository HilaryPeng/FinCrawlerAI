# 多源金融资讯自动化采集与分析

用于自动化收集多平台金融资讯，完成清洗、聚合并推送到飞书，支持本地留存与定时调度。

## 项目简介

- 覆盖来源：财联社、韭研公社（可扩展其他平台）
- 数据处理：清洗、聚合、去重
- 输出形式：Markdown，适合阅读与二次处理
- 推送能力：飞书群机器人（支持长消息拆分）

## 架构概览

流程：采集 → 清洗 → 聚合 → 推送 → 存档

- scraper：抓取多平台原始数据
- processor：清洗与聚合
- output：输出 Markdown
- output：输出 Markdown
- notifier：消息推送（飞书）

## 设计文档

- 日频市场观察系统 V1 设计：`docs/market_daily_system_design.md`

## 目录结构

```
FinCrawlerAI/
├── src/
│   ├── scraper/           # 抓取模块（财联社/韭研公社）
│   ├── processor/         # 清洗与聚合
│   ├── notifier/          # 飞书推送
│   ├── output/            # 输出生成（Markdown）
├── data/
│   ├── raw/               # 原始数据
│   └── processed/         # 处理后数据与分析结果
├── logs/                  # 日志文件
├── config/
│   ├── settings.py        # 默认配置
│   └── local_settings.py  # 本地配置（不提交）
├── main.py                # 主入口
├── requirements.txt       # 依赖
└── README.md
```

## 运行方式

安装依赖：

```bash
pip install -r requirements.txt
```

常用命令：

```bash
# 只收集（不推送）
python main.py collect

# 只推送已有输出（不重新抓取，摘要+全量各一条）
python main.py notify

# 一键采集并推送原始汇总
python main.py all --notify
```

单独抓取：

```bash
# 财联社
python main.py cailian

# 韭研公社异动解析（指定日期）
python main.py jygs --action-date 2026-01-26
```

### 下载股票日线（关代理后运行）

如果 AkShare 在代理环境下访问股票日线失败，可直接运行下面的脚本。脚本会在当前进程内清理常见代理环境变量，并全量下载股票日线到 SQLite。

```bash
python scripts/collect_quotes_only.py --date 2026-03-18
```

下载结果写入：

```bash
data/db/market_daily.db
```

### 生成日报并部署到服务器

先生成日报页面：

```bash
python scripts/generate_market_daily_report.py --date 2026-03-18
```

如果服务器已安装并启用 `nginx`，可直接生成并部署 HTML 到远端 Web 目录：

```bash
python scripts/deploy_market_daily_report.py \
  --date 2026-03-18 \
  --host 167.179.78.250 \
  --user root \
  --publish-index
```

说明：

- 脚本默认通过 `ssh/scp` 部署到远端
- 默认暂存目录：`/root/market_daily`
- 默认站点目录：`/var/www/html`
- `--publish-index` 会同步更新远端 `/var/www/html/index.html`
- 如果你已经本地生成过 HTML，也可以跳过生成阶段：

```bash
python scripts/deploy_market_daily_report.py \
  --date 2026-03-18 \
  --host 167.179.78.250 \
  --user root \
  --skip-generate \
  --html-path data/processed/market_daily/market_daily_20260318.html \
  --publish-index
```

## 数据与输出

输出目录：`data/processed`

- 财联社：`cailian_news_*.md`（全量） / `cailian_news_summary_*.md`（摘要）
- 韭研公社：`jiuyangongshe_action_*.md`（全量） / `jiuyangongshe_action_*_summary_*.md`（摘要）

新闻条目结构（清洗后）：

```python
{
    "title": "新闻标题",
    "content": "新闻内容",
    "publish_time": "2024-01-26 10:30:00",
    "source": "财联社",
    "url": "新闻链接",
    "tags": ["股票", "A股", "财经"]
}
```

## 配置与安全

默认配置在 `config/settings.py`，本地密钥与账号建议放到 `config/local_settings.py`。

示例：

```python
# config/local_settings.py
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/<YOUR_WEBHOOK_TOKEN>"
FEISHU_SECRET = ""

JYGS_PHONE = "<YOUR_PHONE>"
JYGS_PASSWORD = "<YOUR_PASSWORD>"
# 用于部分需要签名的接口（如“关注的人”）；不要提交真实值到仓库
JYGS_TOKEN_SEED_PREFIX = "<YOUR_TOKEN_SEED_PREFIX>"
```

注意：`config/local_settings.py` 已在 `.gitignore` 中，不会提交到仓库。

### 稳定性与排障（推荐）

项目内置了两类“更稳”能力：

- **HTTP 重试/退避**：对超时、连接错误、429、5xx 自动重试，并做指数退避。
- **原始响应缓存**：把每次请求的响应保存到 `data/raw/http_cache/<source>/`，便于复现和排查站点结构变化（`data/` 已被 `.gitignore` 忽略）。

可在 `config/local_settings.py` 调整（可选）：

```python
# HTTP 稳定性
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_BASE_SECONDS = 0.8
HTTP_BACKOFF_CAP_SECONDS = 10.0

# 原始响应缓存/回放（调试用）
RAW_CACHE_ENABLED = True
RAW_CACHE_REPLAY = False   # True 时优先读缓存，不走网络

# 健康报告告警阈值（清洗保留率过低会提示）
HEALTH_MIN_KEEP_RATIO = 0.5
```

另外也支持环境变量快速切换回放模式：

- `RAW_CACHE_REPLAY=1`：开启回放
- `RAW_CACHE_ENABLED=0`：关闭缓存

## 定时调度示例（可选）

```bash
# 每 2 小时执行一次
0 */2 * * * /usr/bin/python3 /path/to/FinCrawlerAI/main.py collect
0 */2 * * * /usr/bin/python3 /path/to/FinCrawlerAI/main.py notify
```

## 推送格式说明

- 每个来源推送两条：摘要 + 全量
- 摘要用于快速浏览，全量用于完整阅读
- 韭研公社摘要会突出连板/高度条目（用符号标记）

本项目仅供个人学习研究使用，请遵守各平台使用条款。
