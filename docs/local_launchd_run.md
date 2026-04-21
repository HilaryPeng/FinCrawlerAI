# 本地 `launchd` 自动运行

当前推荐模式：

- 数据库和原始数据保留在本地
- 每次本地跑完后：
  - 生成页面
  - 同步 `data/` 快照到服务器
  - 更新服务器上的 HTML
  - 通过服务器发飞书通知

## 手动运行

```bash
python scripts/run_local_market_daily_job.py \
  --date 2026-03-31 \
  --check-trade-date \
  --with-news \
  --news-sources cailian,jygs \
  --with-attention \
  --host fincrawler-vps \
  --user root \
  --base-url http://167.179.78.250 \
  --sync-data \
  --notify-via-server
```

## `launchd` 调度策略

- 开机后自动跑一次
- 每周一到周五 `21:00` 跑一次
- 脚本内部再判断是否为 A 股开盘日，节假日自动跳过

## 日志

默认写入：

- `logs/local_market_daily_launchd.log`
- `logs/local_market_daily_launchd.error.log`
