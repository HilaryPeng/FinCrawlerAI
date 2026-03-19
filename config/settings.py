"""
财联社新闻收集工具配置文件
"""

from pathlib import Path
from typing import Dict, List
import importlib


class Config:
    """配置类"""
    
    # 项目根目录
    PROJECT_ROOT = Path(__file__).parent.parent
    
    # 数据目录
    DATA_DIR = PROJECT_ROOT / "data"
    RAW_DATA_DIR = DATA_DIR / "raw"
    PROCESSED_DATA_DIR = DATA_DIR / "processed"
    LOGS_DIR = PROJECT_ROOT / "logs"
    
    # 网站配置
    CAILIAN_BASE_URL = "https://www.cls.cn"
    CAILIAN_API_URL = "https://www.cls.cn/api"
    CAILIAN_TELEGRAPH_API_PATH = "/v1/roll/get_roll_list"
    
    # 请求配置
    REQUEST_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    # 请求限制
    REQUEST_DELAY = 2  # 请求间隔（秒）
    MAX_RETRIES = 3  # 最大重试次数
    TIMEOUT = 30  # 请求超时（秒）
    # 网络增强（更稳）：额外重试/退避配置（不影响原有 MAX_RETRIES/TIMEOUT）
    HTTP_MAX_RETRIES = 3
    HTTP_BACKOFF_BASE_SECONDS = 0.8
    HTTP_BACKOFF_CAP_SECONDS = 10.0
    # 原始响应缓存（便于回放排错，默认开启；data/ 已被 .gitignore）
    RAW_CACHE_ENABLED = True
    # 回放模式：优先使用 data/raw/http_cache 里的缓存响应（调试时开启）
    RAW_CACHE_REPLAY = False

    # 健康报告告警阈值：清洗保留率过低会提示
    HEALTH_MIN_KEEP_RATIO = 0.5
    PAGE_SIZE = 20  # 每次请求条数
    MAX_PAGES = 30  # 最大翻页次数
    
    # 输出配置
    OUTPUT_FORMATS = ["markdown"]
    MARKDOWN_TEMPLATE = "default"
    JSON_INDENT = 2
    STATE_FILE = PROJECT_ROOT / "data" / "processed" / "crawl_state.json"
    CRAWL_LOOKBACK_SECONDS = 86400  # 默认回看最近1天
    
    # 数据清洗配置
    MIN_CONTENT_LENGTH = 10  # 最小内容长度
    MAX_CONTENT_LENGTH = 50000  # 最大内容长度
    DUPLICATE_THRESHOLD = 0.8  # 重复内容阈值
    
    # 日志配置
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # 数据库配置
    DB_DIR = DATA_DIR / "db"
    MARKET_DAILY_DB = DB_DIR / "market_daily.db"
    
    # 调度配置
    ENABLE_SCHEDULED_RUNS = False
    SCHEDULE_INTERVAL = 3600  # 定时运行间隔（秒）

    # 韭研公社（韭菜公社）登录（建议放到 config/local_settings.py 或环境变量）
    JYGS_PHONE = ""
    JYGS_PASSWORD = ""
    # 韭研公社部分接口签名种子（建议放到 config/local_settings.py 或环境变量）
    # 用于“关注的人”等需要签名的接口；不要提交真实值到仓库。
    JYGS_TOKEN_SEED_PREFIX = ""

    # 飞书机器人（建议放到 config/local_settings.py）
    FEISHU_WEBHOOK = ""
    FEISHU_SECRET = ""

    # api易（已停用，如需启用请在 config/local_settings.py 配置）
    # APIYI_BASE_URL = "https://api.apiyi.com/v1/chat/completions"
    # APIYI_API_KEY = ""
    # APIYI_MODEL = "gpt-4o-mini"

    
    @classmethod
    def ensure_directories(cls):
        """确保所有必要的目录存在"""
        for directory in [cls.DATA_DIR, cls.RAW_DATA_DIR, cls.PROCESSED_DATA_DIR, cls.LOGS_DIR, cls.DB_DIR]:
            directory.mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """获取配置实例"""
    # 允许本地覆盖（不要提交到仓库）
    try:
        local = importlib.import_module("config.local_settings")
        for k in dir(local):
            if k.isupper():
                setattr(Config, k, getattr(local, k))
    except Exception:
        pass
    return Config()
