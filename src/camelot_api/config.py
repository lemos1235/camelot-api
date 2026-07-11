"""服务配置。

优先级：环境变量 > config.toml > 字段默认值。
配置文件路径由环境变量 ``CONFIG_FILE`` 指定（默认 ``config.toml``，相对于 CWD；
不存在则跳过，回退到默认值）。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass


def _config_file() -> str:
    """返回要加载的配置文件路径（默认 config.toml，可被 $CONFIG_FILE 覆盖）。"""
    return os.getenv("CONFIG_FILE", "config.toml")


def _load_toml() -> dict:
    """读取配置文件为 dict；文件不存在或不可读则返回空 dict（不报错）。"""
    path = _config_file()
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        # 解析失败时打 stderr 提示，但回退默认值不让服务起不来
        import sys

        print(f"[config] failed to load {path}: {e}", file=sys.stderr)
        return {}


@dataclass
class Config:
    """服务配置。字段名被 server.py / service.py / logger.py / __main__.py 直接读取，勿改。"""

    host: str
    port: int
    workers: int
    log_level: str
    log_format: str

    default_flavor: str
    fallback_to_stream: bool
    default_line_scale: int
    max_pdf_size_mb: int

    # 文件上传
    upload_dir: str
    upload_max_size_mb: int
    upload_ttl_hours: int
    upload_cleanup_interval_minutes: int

    # 结果缓存
    cache_max_entries: int

    # URL 下载
    download_timeout_seconds: int
    download_max_size_mb: int


def _str(env_key: str, toml_key: str, default: str, toml: dict) -> str:
    """字符串字段：env > toml > default。"""
    val = os.getenv(env_key)
    if val is not None:
        return val
    raw = toml.get(toml_key)
    if raw is not None:
        return str(raw)
    return default


def _int(env_key: str, toml_key: str, default: int, toml: dict) -> int:
    """整数字段：env > toml > default。"""
    val = os.getenv(env_key)
    if val is not None:
        return int(val)
    raw = toml.get(toml_key)
    if raw is not None:
        return int(raw)
    return default


def _bool(env_key: str, toml_key: str, default: bool, toml: dict) -> bool:
    """布尔字段：env > toml > default。接受大小写不敏感的 true/false/1/0。"""
    val = os.getenv(env_key)
    if val is not None:
        return val.strip().lower() in ("true", "1", "yes", "on")
    raw = toml.get(toml_key)
    if raw is not None:
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("true", "1", "yes", "on")
    return default


_config: Config | None = None


def get_config() -> Config:
    """获取全局配置单例（首次调用时按 env > config.toml > 默认值 构造）。"""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    toml = _load_toml()

    upload_dir = os.path.expanduser(
        _str("UPLOAD_DIR", "upload_dir", "~/.camelot-api/uploads", toml)
    )
    # upload_max_size_mb 默认复用 MAX_PDF_SIZE_MB
    upload_max_size_default = _int("MAX_PDF_SIZE_MB", "max_pdf_size_mb", 200, toml)
    upload_max_size_mb = _int(
        "UPLOAD_MAX_SIZE_MB", "upload_max_size_mb", upload_max_size_default, toml
    )
    # url_max_size_mb 默认复用 UPLOAD_MAX_SIZE_MB
    url_max_size_default = upload_max_size_mb

    _config = Config(
        host=_str("HOST", "host", "0.0.0.0", toml),  # noqa: S104
        port=_int("PORT", "port", 8000, toml),
        workers=_int("WORKERS", "workers", 1, toml),
        log_level=_str("LOG_LEVEL", "log_level", "INFO", toml).upper(),
        log_format=_str("LOG_FORMAT", "log_format", "text", toml),
        default_flavor=_str("CAMELOT_DEFAULT_FLAVOR", "default_flavor", "lattice", toml),
        fallback_to_stream=_bool("CAMELOT_FALLBACK_STREAM", "fallback_to_stream", True, toml),
        default_line_scale=_int("CAMELOT_LINE_SCALE", "line_scale", 15, toml),
        max_pdf_size_mb=_int("MAX_PDF_SIZE_MB", "max_pdf_size_mb", 200, toml),
        upload_dir=upload_dir,
        upload_max_size_mb=upload_max_size_mb,
        upload_ttl_hours=_int("UPLOAD_TTL_HOURS", "upload_ttl_hours", 24, toml),
        upload_cleanup_interval_minutes=_int(
            "UPLOAD_CLEANUP_INTERVAL_MINUTES", "upload_cleanup_interval_minutes", 30, toml
        ),
        cache_max_entries=_int("CACHE_MAX_ENTRIES", "cache_max_entries", 1000, toml),
        download_timeout_seconds=_int(
            "URL_DOWNLOAD_TIMEOUT_SECONDS", "url_download_timeout_seconds", 30, toml
        ),
        download_max_size_mb=_int(
            "URL_MAX_SIZE_MB", "url_max_size_mb", url_max_size_default, toml
        ),
    )
    return _config


def reset_config() -> None:
    """重置单例（供测试 / CLI --config 后重新加载使用）。"""
    global _config  # noqa: PLW0603
    _config = None