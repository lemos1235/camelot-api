"""结构化日志配置。"""

from __future__ import annotations

import logging
import sys

from .config import get_config


def setup_logging() -> None:
    """初始化全局日志配置。"""
    config = get_config()

    if config.log_format == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger("camelot_api")
    root.setLevel(config.log_level)
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(f"camelot_api.{name}")


class _JsonFormatter(logging.Formatter):
    """JSON 行格式，方便 Rust 侧直接解析。"""

    def format(self, record: logging.LogRecord) -> str:
        import json

        return json.dumps(
            {
                "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            },
            ensure_ascii=False,
        )
