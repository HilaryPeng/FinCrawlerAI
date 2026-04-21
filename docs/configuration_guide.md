# 配置说明

## 1. 配置文件位置

默认配置：

- [config/settings.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/config/settings.py)

本地覆盖配置：

- `config/local_settings.py`

建议从模板复制：

- [config/local_settings.example.py](/Users/huangzhipeng/Projects/peng_economic/FinCrawlerAI/config/local_settings.example.py)

```bash
cp config/local_settings.example.py config/local_settings.py
```

---

## 2. 配置分层原则

`settings.py` 里放：

- 默认值
- 目录结构
- 非敏感配置

`local_settings.py` 里放：

- 账号密码
- webhook
- 服务器地址
- 只属于你自己的部署信息

---

## 3. 韭菜公社配置

用于：

- 登录
- 抓取异动解析
- 抓取涨停语义增强

配置项：

```python
JYGS_PHONE = "你的手机号"
JYGS_PASSWORD = "你的密码"
JYGS_TOKEN_SEED_PREFIX = ""
```

说明：

- `JYGS_PHONE` / `JYGS_PASSWORD`
  - 登录必需

- `JYGS_TOKEN_SEED_PREFIX`
  - 某些带签名接口才需要
  - 没有就先留空

---

## 4. 飞书配置

### 4.1 默认通知机器人

当前代码默认使用：

```python
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
FEISHU_SECRET = ""
```

用途：

- 每日市场日报通知
- 成功跑完后的总结消息

### 4.2 多机器人配置

当前已经把多套配置项预留在配置文件中：

```python
FEISHU_STATUS_WEBHOOK = ""
FEISHU_STATUS_SECRET = ""

FEISHU_NEWS_WEBHOOK = ""
FEISHU_NEWS_SECRET = ""

FEISHU_ERROR_WEBHOOK = ""
FEISHU_ERROR_SECRET = ""
```

建议分法：

- `FEISHU_WEBHOOK`
  - 正常日报推送

- `FEISHU_STATUS_WEBHOOK`
  - 运行状态、任务成功

- `FEISHU_NEWS_WEBHOOK`
  - 只发新闻相关消息

- `FEISHU_ERROR_WEBHOOK`
  - 异常、失败、告警

说明：

- 当前主代码仍默认使用 `FEISHU_WEBHOOK`
- 其他 webhook 现在是**预留配置位**
- 后面如果需要按用途拆分机器人，可以直接接入

---

## 5. 服务器部署配置

这些配置项现在已经统一放入默认配置结构中：

```python
SERVER_HOST_ALIAS = "fincrawler-vps"
SERVER_HOST = "167.179.78.250"
SERVER_SSH_USER = "root"
SERVER_SSH_PORT = 22

SERVER_BASE_URL = "http://167.179.78.250"

SERVER_PROJECT_DIR = "/opt/FinCrawlerAI"
SERVER_WEB_ROOT = "/var/www/html"
SERVER_STAGING_DIR = "/root/market_daily"
SERVER_DATA_BASE_DIR = "/root/market_daily_data"
SERVER_ARCHIVE_DIR = "/root/market_daily_archives"
```

含义：

- `SERVER_HOST_ALIAS`
  - 你本机 `~/.ssh/config` 里的 SSH 别名

- `SERVER_HOST`
  - 服务器 IP / 域名

- `SERVER_SSH_USER`
  - SSH 用户

- `SERVER_SSH_PORT`
  - SSH 端口

- `SERVER_BASE_URL`
  - 页面访问地址前缀

- `SERVER_PROJECT_DIR`
  - 服务器上的项目目录

- `SERVER_WEB_ROOT`
  - nginx 站点目录

- `SERVER_STAGING_DIR`
  - HTML 上传暂存目录

- `SERVER_DATA_BASE_DIR`
  - 服务器端数据快照目录

- `SERVER_ARCHIVE_DIR`
  - 数据压缩包归档目录

---

## 6. 本地自动化与服务器自动化的关系

当前推荐：

- 本地电脑负责主采集
- 服务器负责托管 HTML 和保留快照

因此：

- 本地 `launchd` 会用到服务器配置
- 服务器自己的 `cron` 也会用到飞书配置

---

## 7. 推荐最小配置

如果你只想先跑起来，`local_settings.py` 最少填这些：

```python
JYGS_PHONE = "你的手机号"
JYGS_PASSWORD = "你的密码"

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
FEISHU_SECRET = ""

SERVER_HOST_ALIAS = "fincrawler-vps"
SERVER_HOST = "你的服务器IP"
SERVER_SSH_USER = "root"
SERVER_SSH_PORT = 22
SERVER_BASE_URL = "http://你的服务器IP"
```

其他目录项如果你沿用当前默认值，可以不改。
