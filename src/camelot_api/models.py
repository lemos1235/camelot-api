"""Pydantic 数据模型：请求/响应/健康检查/错误。

所有坐标值以 PDF 点为单位的绝对值，坐标原点在页面左下角。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel, Field

from .errors import ErrorCode


class BBox(BaseModel):
    """边界框。"""
    x1: float = Field(description="左上角 x")
    y1: float = Field(description="左上角 y")
    x2: float = Field(description="右下角 x")
    y2: float = Field(description="右下角 y")


class CellInfo(BaseModel):
    """单个单元格信息：文本 + 边界框。"""
    row: int = Field(description="行索引（从 0 开始）")
    col: int = Field(description="列索引（从 0 开始）")
    text: str = Field(description="单元格文本，去除多余空白")
    bbox: BBox = Field(description="单元格边界框")


class TableInfo(BaseModel):
    """单张表格的完整布局信息。"""
    table_index: int = Field(description="表格序号（从 0 开始）")
    page: int = Field(description="所在页码（从 1 开始）")
    rows: int = Field(description="行数")
    cols: int = Field(description="列数")
    accuracy: float = Field(description="解析精度 0-100")
    whitespace: float = Field(description="空白占比 0-100")
    flavor: str = Field(description="实际使用的解析模式：lattice / stream")
    order: int = Field(description="在当前页的检测顺序（从 0 开始）")
    bbox: BBox = Field(description="整个表格区域的边界框")
    cells: list[CellInfo] = Field(default_factory=list, description="所有单元格")


class ExtractRequest(BaseModel):
    """表格提取请求 — 暴露 camelot.read_pdf 的全部参数。"""

    file_path: str = Field(description="PDF 文件的本地绝对路径")
    pages: str = Field(default="all", description="页码范围：'all' / '1' / '1-3' / '1,3,5'")
    flavor: Literal["lattice", "stream"] = Field(default="lattice", description="lattice=有边框表格，stream=无边框表格")

    # 通用参数
    line_scale: int = Field(default=15, ge=1, description="线条缩放参数")
    copy_text: list[str] | None = Field(default=None, description="文本替换规则 ['旧','新']")
    shift_text: list[str] | None = Field(default=None, description="文本位置偏移 ['l','r','t','b']")

    # lattice 专用
    line_tol: int | None = Field(default=None, ge=1, description="lattice: 线条容差")
    joint_tol: int | None = Field(default=None, ge=1, description="lattice: 连接点容差")
    threshold_blocksize: int | None = Field(default=None, ge=1, description="lattice: 阈值块大小")
    threshold_constant: int | None = Field(default=None, ge=1, description="lattice: 阈值常量")
    iterations: int | None = Field(default=None, ge=0, description="lattice: 形态学迭代次数")
    resolution: int | None = Field(default=None, ge=1, description="lattice: 分辨率")

    # stream 专用
    edge_tol: int | None = Field(default=None, ge=1, description="stream: 边缘容差")
    row_tol: int | None = Field(default=None, ge=1, description="stream: 行容差")
    column_tol: int | None = Field(default=None, ge=1, description="stream: 列容差")

    # 后处理
    strip_text: str | None = Field(default=None, description="要去除的文本字符")
    split_text: bool = Field(default=False, description="是否拆分跨行文本")
    flag_size: bool = Field(default=False, description="是否检测字体大小（较慢）")
    process_background: bool = Field(default=False, description="是否处理背景")

    @pydantic.field_validator("file_path")
    @classmethod
    def file_must_exist(cls, v: str) -> str:
        path = Path(v)
        if not path.exists():
            raise ValueError(f"文件不存在: {v}")
        if not path.is_file():
            raise ValueError(f"不是文件: {v}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"不是 PDF 文件: {v}")
        return str(path.resolve())


class ErrorDetail(BaseModel):
    """结构化错误信息，方便 Rust 侧 match。"""
    code: ErrorCode = Field(description="machine-readable 错误码")
    message: str = Field(description="human-readable 错误描述")


class ExtractResponse(BaseModel):
    """表格提取响应。"""
    success: bool = Field(description="是否成功")
    total_tables: int = Field(default=0, description="检测到的表格总数（成功时）")
    tables: list[TableInfo] = Field(default_factory=list)
    error: ErrorDetail | None = Field(default=None, description="错误详情（仅在 success=False 时）")


class HealthResponse(BaseModel):
    """结构化健康检查响应。"""
    status: str = "ok"
    version: str = Field(description="服务版本")
    camelot_available: bool = Field(description="camelot 库是否可用")
