"""核心服务：封装 camelot 调用，返回包含布局信息的结构化数据。"""

from __future__ import annotations

import time
import warnings
from pathlib import Path

import camelot

from .config import get_config
from .errors import AppError, ErrorCode
from .logger import get_logger
from .models import BBox, CellInfo, ErrorDetail, ExtractRequest, ExtractResponse, TableInfo

logger = get_logger("service")


def _check_file(path: str) -> None:
    """前置校验：文件存在且为 PDF。"""
    p = Path(path)
    if not p.exists():
        raise AppError(ErrorCode.FILE_NOT_FOUND, f"文件不存在: {path}")
    if not p.is_file():
        raise AppError(ErrorCode.FILE_NOT_FOUND, f"路径不是文件: {path}")
    if p.suffix.lower() != ".pdf":
        raise AppError(ErrorCode.FILE_NOT_PDF, f"不是 PDF 文件: {path}")


def _build_camelot_kwargs(request: ExtractRequest) -> dict:
    """从请求中提取 camelot.read_pdf 的有效关键字参数。"""
    kwargs: dict = {
        "flavor": request.flavor,
        "line_scale": request.line_scale,
        "split_text": request.split_text,
        "flag_size": request.flag_size,
        "strip_text": request.strip_text,
        "process_background": request.process_background,
    }
    if request.copy_text is not None:
        kwargs["copy_text"] = request.copy_text
    if request.shift_text is not None:
        kwargs["shift_text"] = request.shift_text
    if request.flavor == "lattice":
        for key in ("line_tol", "joint_tol", "threshold_blocksize", "threshold_constant", "iterations", "resolution"):
            val = getattr(request, key)
            if val is not None:
                kwargs[key] = val
    if request.flavor == "stream":
        for key in ("edge_tol", "row_tol", "column_tol"):
            val = getattr(request, key)
            if val is not None:
                kwargs[key] = val
    return kwargs


def _build_response(request: ExtractRequest, tables: list) -> ExtractResponse:
    """将 camelot Table 列表转换为 ExtractResponse。"""
    table_infos: list[TableInfo] = []
    for idx, table in enumerate(tables):
        raw_bbox = table._bbox  # noqa: SLF001
        table_bbox = BBox(x1=raw_bbox[0], y1=raw_bbox[1], x2=raw_bbox[2], y2=raw_bbox[3])

        cells: list[CellInfo] = []
        for i, row_cells in enumerate(table.cells):
            for j, cell in enumerate(row_cells):
                cells.append(CellInfo(
                    row=i, col=j,
                    text=cell.text.strip() if cell.text else "",
                    bbox=BBox(x1=cell.x1, y1=cell.y1, x2=cell.x2, y2=cell.y2),
                ))

        table_infos.append(TableInfo(
            table_index=idx, page=table.page,
            rows=table.shape[0], cols=table.shape[1],
            accuracy=table.parsing_report["accuracy"],
            whitespace=table.parsing_report["whitespace"],
            flavor=table.flavor, order=table.order,
            bbox=table_bbox, cells=cells,
        ))

    return ExtractResponse(success=True, total_tables=len(table_infos), tables=table_infos)


def extract_tables(request: ExtractRequest) -> ExtractResponse:
    """执行 PDF 表格提取，返回含 bbox 的完整布局信息。"""
    config = get_config()
    start = time.perf_counter()

    try:
        _check_file(request.file_path)
        file_path = str(Path(request.file_path).resolve())
        logger.info("start extract: %s pages=%s flavor=%s", file_path, request.pages, request.flavor)

        kwargs = _build_camelot_kwargs(request)
        tables = camelot.read_pdf(file_path, pages=request.pages, **kwargs)

        actual_flavor = request.flavor
        if tables.n == 0 and request.flavor == "lattice" and config.fallback_to_stream:
            logger.info("lattice returned 0 tables, falling back to stream")
            kwargs["flavor"] = "stream"
            tables = camelot.read_pdf(file_path, pages=request.pages, **kwargs)
            actual_flavor = "stream"

        elapsed = time.perf_counter() - start
        logger.info("extract done: %d tables in %.2fs (flavor=%s)", tables.n, elapsed, actual_flavor)
        return _build_response(request, tables)

    except AppError as e:
        logger.warning("app error: [%s] %s", e.code.value, e.message)
        return ExtractResponse(success=False, error=ErrorDetail(code=e.code, message=e.message))
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error("parse failed after %.2fs: %s", elapsed, e, exc_info=True)
        return ExtractResponse(success=False, error=ErrorDetail(code=ErrorCode.PARSE_FAILED, message=str(e)))


warnings.filterwarnings("ignore", module="camelot")
