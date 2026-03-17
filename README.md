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
