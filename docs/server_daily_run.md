# 服务器日跑部署

目标：

- 把市场观察日报项目部署到服务器
- 每天自动更新数据库与 HTML 页面
- 跑完后通过飞书把日报链接推送给你

## 1. 服务器准备

建议服务器具备：

- Python 3.10+
- `git`
- `nginx`
- `sqlite3`

建议目录：

```bash
/opt/FinCrawlerAI
```

## 2. 拉代码与安装依赖

```bash
cd /opt
git clone https://github.com/HilaryPeng/FinCrawlerAI.git FinCrawlerAI
cd /opt/FinCrawlerAI

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 3. 配置本地参数

创建：

```bash
config/local_settings.py
```

最少配置：

```python
FEISHU_NEWS_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
FEISHU_NEWS_SECRET = ""

JYGS_PHONE = "你的韭菜公社手机号"
JYGS_PASSWORD = "你的韭菜公社密码"
JYGS_TOKEN_SEED_PREFIX = ""
```

如果服务器环境不该走代理，建议 cron 里也不要带代理环境变量。

## 4. Nginx 站点目录

默认页面发布到：

```bash
/var/www/html
```

确认 nginx 已启动：

```bash
systemctl enable nginx
systemctl restart nginx
```

## 5. 手动执行一次

先手动跑通：

```bash
cd /opt/FinCrawlerAI
source .venv/bin/activate

python scripts/run_market_daily_job.py \
  --date 2026-03-31 \
  --base-url http://你的服务器IP或域名 \
  --with-news \
  --news-sources jygs \
  --with-attention \
  --notify-feishu
```

说明：

- `--with-news`：入库新闻
- `--news-sources jygs`：先只跑韭菜公社更稳
- `--with-attention`：抓热度/技术榜单
- `--notify-feishu`：跑完推飞书

产出：

- SQLite：`data/db/market_daily.db`
- HTML：`/var/www/html/market_daily_YYYYMMDD.html`
- 首页：`/var/www/html/index.html`

## 6. 配置 cron

例如每天晚上 `21:00` 跑一次，由脚本自己判断这一天是不是 A 股交易日：

```cron
0 21 * * * cd /opt/FinCrawlerAI && . .venv/bin/activate && python scripts/run_market_daily_job.py --date $(date +\\%F) --base-url http://你的服务器IP或域名 --with-news --news-sources jygs --with-attention --check-trade-date --notify-feishu >> logs/server_daily_job.log 2>&1
```

说明：

- `--check-trade-date` 会先查 A 股交易日历
- 如果当天不是开盘日，会直接退出，不会误跑
- 如果你的服务器时区不是上海，先设置时区或在 cron 中显式处理日期

## 7. 推荐运行方式

第一阶段先这样跑：

- 新闻只用 `jygs`
- 热度启用 `--with-attention`
- 每天只跑一次日频任务

后面稳定后再考虑把 `cailian` 一起并进去。

## 8. 常用命令

更新服务器代码并校验：

```bash
cd /opt/FinCrawlerAI
bash scripts/deploy_server.sh
```

手动重跑某一天：

```bash
python scripts/run_market_daily_job.py \
  --date 2026-03-20 \
  --base-url http://你的服务器IP或域名 \
  --with-news \
  --news-sources jygs \
  --with-attention \
  --notify-feishu
```

查看日志：

```bash
tail -f logs/server_daily_job.log
```

检查页面：

```bash
curl -I http://你的服务器IP或域名/
curl -I http://你的服务器IP或域名/market_daily_20260320.html
```

## 9. 本地数据快照同步到服务器

如果你仍然在本地跑数据库，但希望把本地数据完整备份到服务器，可用：

```bash
python scripts/sync_market_data_snapshot.py \
  --host 你的服务器IP或域名 \
  --user root
```

这条会：

- 打包本地整个 `data/`
- 上传到服务器
- 解压到带时间戳的快照目录
- 更新服务器上的 `latest` 软链

默认远端目录：

- 归档包：`/root/market_daily_archives`
- 解压快照：`/root/market_daily_data/<snapshot_name>`
- 最新软链：`/root/market_daily_data/latest`

这样你本地数据仍然保留，服务器也会累计每次快照。
