"""FastAPI HTTP 服务。

启动方式:
    uv run camelot-api
    uv run python -m camelot_api
    uv run uvicorn camelot_api.server:app

API:
    GET  /health                      结构化健康检查
    POST /api/v1/files/upload         上传 PDF 文件（返回 file_id）
    DELETE /api/v1/files/{file_id}    手动删除文件及缓存
    POST /api/v1/extract              提取 PDF 表格（支持 file_id / file_url）
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_config
from .errors import AppError, ErrorCode
from .logger import get_logger, setup_logging
from .models import ErrorDetail, ExtractRequest, ExtractResponse, FileDeleteResponse, HealthResponse, UploadResponse
from .service import cleanup_expired_files, delete_file, extract_tables, init_service, save_upload

setup_logging()
logger = get_logger("server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期：初始化服务 + 启动后台清理任务。"""
    logger.info("camelot-api v%s starting...", __version__)
    init_service()

    # 启动定时清理任务
    config = get_config()
    interval = config.upload_cleanup_interval_minutes * 60
    cleanup_task = asyncio.create_task(_cleanup_loop(interval))
    logger.info("cleanup task started (interval=%dmin)", config.upload_cleanup_interval_minutes)

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("camelot-api shutting down")


async def _cleanup_loop(interval_seconds: int) -> None:
    """后台定时清理过期文件。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            count = await asyncio.to_thread(cleanup_expired_files)
            if count > 0:
                logger.info("cleanup task: removed %d expired files", count)
        except Exception as e:
            logger.error("cleanup task error: %s", e)


app = FastAPI(
    title="camelot-api",
    description="camelot PDF table extraction service — 供 Rust 侧通过 HTTP RPC 调用",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个请求的方法、路径、状态码和耗时。"""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s → %d (%.1fms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常统一返回结构化错误。"""
    logger.error("unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ExtractResponse(
            success=False,
            error=ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message=str(exc)),
        ).model_dump(),
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """AppError 统一返回结构化错误。"""
    status_map = {
        ErrorCode.FILE_ID_NOT_FOUND: 404,
        ErrorCode.FILE_TOO_LARGE: 413,
        ErrorCode.NOT_A_PDF: 400,
        ErrorCode.UPLOAD_FAILED: 500,
        ErrorCode.FILE_URL_INVALID: 400,
        ErrorCode.FILE_URL_DOWNLOAD_FAILED: 502,
        ErrorCode.FILE_URL_TOO_LARGE: 413,
    }
    status_code = status_map.get(exc.code, 400)
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": {"code": exc.code, "message": exc.message}},
    )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """结构化健康检查。"""
    try:
        import camelot  # noqa: F401
        camelot_ok = True
    except Exception:
        camelot_ok = False
    return HealthResponse(status="ok", version=__version__, camelot_available=camelot_ok)


# ---------------------------------------------------------------------------
# 文件上传 / 删除
# ---------------------------------------------------------------------------


@app.post("/api/v1/files/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile) -> UploadResponse:
    """上传 PDF 文件，返回 file_id。

    同一文件（MD5 相同）重复上传会直接返回已有的 file_id（cached=true）。
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise AppError(ErrorCode.NOT_A_PDF, "只接受 .pdf 文件")
    return await asyncio.to_thread(save_upload, file)


@app.delete("/api/v1/files/{file_id}", response_model=FileDeleteResponse)
async def remove_file(file_id: str) -> FileDeleteResponse:
    """手动删除已上传的文件及关联缓存。"""
    return await asyncio.to_thread(delete_file, file_id)


# ---------------------------------------------------------------------------
# 表格提取
# ---------------------------------------------------------------------------


@app.post("/api/v1/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest) -> ExtractResponse:
    """提取 PDF 中的表格，返回表格及单元格的布局信息（含 bbox）。

    支持两种方式：
    - file_id:   通过 /api/v1/files/upload 获取的文件 ID（支持结果缓存）
    - file_url:  可公开访问的 PDF URL（自动下载、去重，支持结果缓存）

    Rust 侧用 reqwest 等 HTTP 客户端 POST JSON 即可调用。
    """
    return await asyncio.to_thread(extract_tables, request)
