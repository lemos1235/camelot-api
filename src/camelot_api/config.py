"""服务配置，全部通过环境变量驱动。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """服务配置。所有字段均从环境变量读取，提供合理默认值。"""

    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))  # noqa: S104
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    workers: int = field(default_factory=lambda: int(os.getenv("WORKERS", "1")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    log_format: str = field(default_factory=lambda: os.getenv("LOG_FORMAT", "text"))
    default_flavor: str = field(default_factory=lambda: os.getenv("CAMELOT_DEFAULT_FLAVOR", "lattice"))
    fallback_to_stream: bool = field(
        default_factory=lambda: os.getenv("CAMELOT_FALLBACK_STREAM", "true").lower() == "true"
    )
    default_line_scale: int = field(default_factory=lambda: int(os.getenv("CAMELOT_LINE_SCALE", "15")))
    max_pdf_size_mb: int = field(default_factory=lambda: int(os.getenv("MAX_PDF_SIZE_MB", "200")))

    # 文件上传
    upload_dir: str = field(
        default_factory=lambda: os.getenv("UPLOAD_DIR", "/var/lib/camelot-api/uploads")
    )
    upload_max_size_mb: int = field(
        default_factory=lambda: int(os.getenv("UPLOAD_MAX_SIZE_MB", os.getenv("MAX_PDF_SIZE_MB", "200")))
    )
    upload_ttl_hours: int = field(
        default_factory=lambda: int(os.getenv("UPLOAD_TTL_HOURS", "24"))
    )
    upload_cleanup_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("UPLOAD_CLEANUP_INTERVAL_MINUTES", "30"))
    )

    # 结果缓存
    cache_max_entries: int = field(
        default_factory=lambda: int(os.getenv("CACHE_MAX_ENTRIES", "1000"))
    )


_config: Config | None = None


def get_config() -> Config:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
