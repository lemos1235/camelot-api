"""FastAPI HTTP 服务。

启动方式:
    uv run camelot-api --port 8000
    uv run python -m camelot_api --port 8000
    uv run uvicorn camelot_api.server:app --host 0.0.0.0 --port 8000

API:
    GET  /health                 结构化健康检查
    POST /api/v1/extract         提取 PDF 表格
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .errors import ErrorCode
from .logger import get_logger, setup_logging
from .models import ErrorDetail, ExtractRequest, ExtractResponse, HealthResponse
from .service import extract_tables

setup_logging()
logger = get_logger("server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期。"""
    logger.info("camelot-api v%s starting...", __version__)
    yield
    logger.info("camelot-api shutting down")


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
    allow_methods=["GET", "POST"],
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


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """结构化健康检查。"""
    try:
        import camelot  # noqa: F401
        camelot_ok = True
    except Exception:
        camelot_ok = False
    return HealthResponse(status="ok", version=__version__, camelot_available=camelot_ok)


@app.post("/api/v1/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest) -> ExtractResponse:
    """提取 PDF 中的表格，返回表格及单元格的布局信息（含 bbox）。

    Rust 侧用 reqwest 等 HTTP 客户端 POST JSON 即可调用。
    """
    return extract_tables(request)
