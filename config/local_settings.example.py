"""Local-only settings template (copy to config/local_settings.py).

Do not commit real secrets.
"""

# -----------------------------
# 韭菜公社
# -----------------------------
JYGS_PHONE = "你的手机号"
JYGS_PASSWORD = "你的密码"
# 某些接口需要签名种子；没有就先留空
JYGS_TOKEN_SEED_PREFIX = ""

# -----------------------------
# 飞书机器人
# -----------------------------
# 默认机器人：日报成功通知
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
FEISHU_SECRET = ""

# 可选：按用途拆分多个机器人
FEISHU_STATUS_WEBHOOK = ""
FEISHU_STATUS_SECRET = ""

FEISHU_NEWS_WEBHOOK = ""
FEISHU_NEWS_SECRET = ""

FEISHU_ERROR_WEBHOOK = ""
FEISHU_ERROR_SECRET = ""

# -----------------------------
# 服务器部署
# -----------------------------
# SSH alias，建议与 ~/.ssh/config 一致
SERVER_HOST_ALIAS = "fincrawler-vps"
SERVER_HOST = "167.179.78.250"
SERVER_SSH_USER = "root"
SERVER_SSH_PORT = 22

# 对外访问地址
SERVER_BASE_URL = "http://167.179.78.250"

# 服务器目录
SERVER_PROJECT_DIR = "/opt/FinCrawlerAI"
SERVER_WEB_ROOT = "/var/www/html"
SERVER_STAGING_DIR = "/root/market_daily"
SERVER_DATA_BASE_DIR = "/root/market_daily_data"
SERVER_ARCHIVE_DIR = "/root/market_daily_archives"
