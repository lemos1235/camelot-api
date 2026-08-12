"""Pydantic 数据模型：请求/响应/健康检查/错误。

所有坐标值以 PDF 点为单位的绝对值，坐标原点在页面左下角。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

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
    flavor: str = Field(description="实际使用的解析模式，如 lattice / stream / network / hybrid / ml")
    order: int = Field(description="在当前页的检测顺序（从 0 开始）")
    bbox: BBox = Field(description="整个表格区域的边界框")
    cells: list[CellInfo] = Field(default_factory=list, description="所有单元格")


class ExtractRequest(BaseModel):
    """表格提取请求 — 暴露 camelot.read_pdf 的全部参数。"""

    file_id: str | None = Field(default=None, description="通过 /api/v1/files/upload 获取的文件 ID（与 file_url 二选一）")
    file_url: str | None = Field(default=None, description="可公开访问的 PDF 下载 URL（与 file_id 二选一），自动下载后提取")
    pages: str = Field(default="all", description="页码范围：'all' / '1' / '1-3' / '1,3,5'")
    flavor: str = Field(
        default="lattice",
        description=(
            "解析模式，直接透传给 camelot.read_pdf，不做枚举限制。"
            "camelot 内置支持 lattice(有边框) / stream(无边框) / network / hybrid / ml / auto，"
            "具体以所安装的 camelot 版本为准，非法值由 camelot 自身报错。"
        ),
    )

    # 通用参数
    line_scale: int = Field(default=15, ge=1, description="线条缩放参数")
    copy_text: list[str] | None = Field(default=None, description="文本替换规则 ['旧','新']（lattice / hybrid / ml）")
    shift_text: list[str] | None = Field(default=None, description="文本位置偏移 ['l','r','t','b']（lattice / hybrid / ml）")

    # lattice / hybrid 专用
    line_tol: int | None = Field(default=None, ge=1, description="lattice/hybrid: 线条容差")
    joint_tol: int | None = Field(default=None, ge=1, description="lattice/hybrid: 连接点容差")
    threshold_blocksize: int | None = Field(default=None, ge=1, description="lattice/hybrid: 阈值块大小")
    threshold_constant: int | None = Field(default=None, ge=1, description="lattice/hybrid: 阈值常量")
    iterations: int | None = Field(default=None, ge=0, description="lattice/hybrid: 形态学迭代次数")
    resolution: int | None = Field(default=None, ge=1, description="lattice/hybrid/ml: 分辨率")

    # stream / network / hybrid 专用
    edge_tol: int | None = Field(default=None, ge=1, description="stream/network/hybrid: 边缘容差")
    row_tol: int | None = Field(default=None, ge=1, description="stream/network/hybrid: 行容差")
    column_tol: int | None = Field(default=None, ge=1, description="stream/network/hybrid: 列容差")

    # ml 专用
    device: str | None = Field(default=None, description="ml: 推理设备，如 'cpu' / 'cuda'")
    structure_model: str | None = Field(default=None, description="ml: 表格结构识别模型名称/路径")
    detection_model: str | None = Field(default=None, description="ml: 表格检测模型名称/路径")
    detection_threshold: float | None = Field(default=None, ge=0, le=1, description="ml: 表格检测置信度阈值")
    structure_threshold: float | None = Field(default=None, ge=0, le=1, description="ml: 结构识别置信度阈值")
    crop_padding: int | None = Field(default=None, ge=0, description="ml: 裁剪表格区域时的留白像素")
    ocr: bool | None = Field(default=None, description="ml: 是否对图像型 PDF 启用 OCR")
    use_fallback: bool | None = Field(default=None, description="lattice/ml: 是否在解析失败时使用回退引擎")

    # 后处理
    strip_text: str | None = Field(default=None, description="要去除的文本字符")
    split_text: bool = Field(default=False, description="是否拆分跨行文本")
    flag_size: bool = Field(default=False, description="是否检测字体大小（较慢）")
    process_background: bool = Field(default=False, description="是否处理背景")

    @model_validator(mode="after")
    def validate_file_source(self) -> ExtractRequest:
        """确保 file_id / file_url 二选一。"""
        provided = sum(1 for v in (self.file_id, self.file_url) if v)
        if provided == 0:
            raise ValueError("必须提供 file_id / file_url 之一")
        if provided > 1:
            raise ValueError("file_id / file_url 只能提供其中一个")
        return self


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


class UploadResponse(BaseModel):
    """文件上传响应。"""
    file_id: str = Field(description="文件唯一标识")
    filename: str = Field(description="原始文件名")
    size: int = Field(description="文件大小（字节）")
    md5: str = Field(description="文件 MD5 哈希")
    cached: bool = Field(description="是否已存在（MD5 去重命中）")
    created_at: datetime = Field(description="创建时间")


class FileDeleteResponse(BaseModel):
    """文件删除响应。"""
    file_id: str = Field(description="文件 ID")
    deleted: bool = Field(description="是否成功删除")
