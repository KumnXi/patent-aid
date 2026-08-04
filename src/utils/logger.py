"""统一日志模块

用法：
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("消息")

日志同时输出到控制台和 logs/app.log（按大小轮转）。
安全：文件 handler 限制 INFO 级别，避免调试信息泄露到日志文件。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def _init_root():
    """初始化根日志器（仅一次）"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("patent_assistant")
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # 文件 handler：INFO 级（避免记录调试敏感数据），5MB 轮转，保留 3 份
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台 handler：INFO 级
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器

    Args:
        name: 通常传 __name__，会归到 patent_assistant 命名空间下

    Returns:
        logging.Logger 实例
    """
    _init_root()
    short = name.split(".")[-1] if "." in name else name
    return logging.getLogger(f"patent_assistant.{short}")
