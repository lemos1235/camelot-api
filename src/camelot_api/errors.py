"""结构化错误类型，方便 Rust 侧进行模式匹配。"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """错误码枚举，作为响应中的 machine-readable 标识。"""
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_NOT_PDF = "FILE_NOT_PDF"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_ID_NOT_FOUND = "FILE_ID_NOT_FOUND"
    NOT_A_PDF = "NOT_A_PDF"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    INVALID_PAGES = "INVALID_PAGES"
    INVALID_FLAVOR = "INVALID_FLAVOR"
    PARSE_FAILED = "PARSE_FAILED"
    NO_TABLES_FOUND = "NO_TABLES_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # URL 下载相关
    FILE_URL_INVALID = "FILE_URL_INVALID"
    FILE_URL_DOWNLOAD_FAILED = "FILE_URL_DOWNLOAD_FAILED"
    FILE_URL_TOO_LARGE = "FILE_URL_TOO_LARGE"


class AppError(Exception):
    """应用层异常，携带 machine-readable error_code。"""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
