# 多源金融资讯自动化采集与分析

用于自动化收集多平台金融资讯，完成清洗、聚合、LLM 分析并推送到飞书，支持本地留存与定时调度。

## 项目简介

- 覆盖来源：财联社、韭研公社（可扩展其他平台）
- 数据处理：清洗、聚合、去重、主题/热度分析
- 输出形式：Markdown/JSON，适合阅读与二次处理
- 推送能力：飞书群机器人（支持长消息拆分）

## 架构概览

流程：采集 → 清洗 → 聚合 → 分析 → 推送 → 存档

- scraper：抓取多平台原始数据
- processor：清洗与聚合
- analyzer：基于 LLM 的分析与摘要
- output：输出 Markdown/JSON
- notifier：消息推送（飞书）

## 目录结构

```
peng_news/
├── src/
│   ├── scraper/           # 抓取模块（财联社/韭研公社）
│   ├── processor/         # 清洗与聚合
│   ├── analyzer/          # LLM 分析
│   ├── notifier/          # 飞书推送
│   ├── output/            # 输出生成（Markdown/JSON）
│   └── llm/               # LLM 客户端（api易）
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

# LLM 分析（不推送）
python main.py analyze

# 分析并推送（简版）
python main.py analyze --notify

# 分析并推送（含全量清单）
python main.py analyze --notify --full-list

# 只推送已有输出（不重新抓取）
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

- 财联社：`cailian_news_*.md/json`
- 韭研公社：`jiuyangongshe_action_*.md/json`
- 分析结果：`analysis_*.md/json`

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
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
FEISHU_SECRET = ""

APIYI_BASE_URL = "https://api.apiyi.com/v1/chat/completions"
APIYI_API_KEY = "sk-xxx"
APIYI_MODEL = "gpt-4o-mini"

JYGS_PHONE = "155xxxx"
JYGS_PASSWORD = "your_password"
```

注意：`config/local_settings.py` 已在 `.gitignore` 中，不会提交到仓库。

## 推送结构说明（简版）

- 总览（时间窗口、来源数、总条数）
- 主题（5 条）
- 平台分段（每平台：要点 2 条 + Top 5）
- 总体热度 Top 15

需要全量清单时使用：

```bash
python main.py analyze --notify --full-list
```

## 定时调度示例（可选）

```bash
# 每 2 小时执行一次
0 */2 * * * /usr/bin/python3 /path/to/peng_news/main.py collect
0 */2 * * * /usr/bin/python3 /path/to/peng_news/main.py analyze --notify
```

本项目仅供个人学习研究使用，请遵守各平台使用条款。
