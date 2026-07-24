import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = ROOT_DIR / "data" / "backend.log"
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "appid",
    "authorization",
    "key",
    "secret",
    "signature",
    "token",
    "x-oss-access-key-id",
    "x-oss-credential",
    "x-oss-security-token",
    "x-oss-signature",
}


def redact_url(value):
    if not value:
        return value
    parts = urlsplit(str(value))
    if not parts.query:
        return str(value)
    safe_query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in SENSITIVE_QUERY_KEYS or lowered.startswith("x-amz-"):
            item = "***"
        safe_query.append((key, item))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(safe_query), parts.fragment)
    )


def redact_text(value):
    if not value:
        return value
    return re.sub(
        r"(?i)((?:access_token|authorization|secret|signature|token|"
        r"x-oss-[\w-]+|x-amz-[\w-]+)=)[^&\s]+",
        r"\1***",
        str(value),
    )


def configure_logging():
    root_logger = logging.getLogger()
    if getattr(root_logger, "_mozhou_configured", False):
        return

    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)
    log_file = Path(os.getenv("LOG_FILE", str(DEFAULT_LOG_FILE)))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    if not root_logger.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(level)
    root_logger._mozhou_configured = True

    # 避免开发日志被底层连接池刷屏；业务请求仍由 Notion/微信客户端记录。
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger(__name__).info(
        "日志系统已启动 level=%s file=%s", level_name, log_file
    )
