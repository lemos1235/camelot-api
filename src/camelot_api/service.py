"""核心服务：文件管理、MD5 去重、结果缓存、camelot 表格提取。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import camelot
from fastapi import UploadFile

from .config import get_config
from .errors import AppError, ErrorCode
from .logger import get_logger
from .models import (
    BBox,
    CellInfo,
    ErrorDetail,
    ExtractRequest,
    ExtractResponse,
    FileDeleteResponse,
    TableInfo,
    UploadResponse,
)

logger = get_logger("service")

# ---------------------------------------------------------------------------
# 文件注册表（持久化到 JSON，内存加速查询）
# ---------------------------------------------------------------------------

_registry: dict[str, dict] = {}        # file_id → {filename, path, size, md5, created_at}
_md5_index: dict[str, str] = {}        # md5 → file_id
_registry_lock = threading.Lock()
_registry_loaded = False

# ---------------------------------------------------------------------------
# 结果缓存（内存 LRU）
# ---------------------------------------------------------------------------

_cache: dict[str, ExtractResponse] = {}     # cache_key → response
_cache_order: list[str] = []                # 近似 LRU 顺序
_cache_lock = threading.Lock()


def _ensure_upload_dir() -> Path:
    """确保上传目录存在，返回 Path。"""
    cfg = get_config()
    d = Path(cfg.upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registry_path() -> Path:
    return _ensure_upload_dir() / "registry.json"


def _load_registry() -> None:
    """从磁盘加载注册表，构建 md5_index。"""
    global _registry, _md5_index, _registry_loaded  # noqa: PLW0603
    path = _registry_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                _registry = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("failed to load registry, starting fresh: %s", e)
            _registry = {}
    else:
        _registry = {}
    # 构建 md5_index
    _md5_index = {}
    for fid, info in _registry.items():
        if "md5" in info:
            _md5_index[info["md5"]] = fid
    _registry_loaded = True
    logger.info("registry loaded: %d files, %d md5 entries", len(_registry), len(_md5_index))


def _save_registry() -> None:
    """将注册表写回磁盘。"""
    path = _registry_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_registry, f, ensure_ascii=False, indent=2)


def init_service() -> None:
    """初始化服务：创建目录、加载注册表。"""
    _ensure_upload_dir()
    _load_registry()


# ---------------------------------------------------------------------------
# 文件管理 API
# ---------------------------------------------------------------------------


def save_upload(file: UploadFile) -> UploadResponse:
    """保存上传文件，MD5 去重。

    流程：
    1. 校验 PDF 魔数
    2. 流式写入磁盘 + 计算 MD5
    3. 查 md5_index，命中则删除新文件、返回已有 file_id
    4. 未命中则写入注册表
    """
    cfg = get_config()

    # 读取文件内容（前 4 字节校验魔数 + 全量计算 MD5 + 写入磁盘）
    content = file.file.read()
    file_size = len(content)

    # 大小检查
    max_bytes = cfg.upload_max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            f"文件大小 {file_size} 字节超过上限 {cfg.upload_max_size_mb}MB",
        )

    # PDF 魔数校验
    if len(content) < 4 or content[:4] != b"%PDF":
        raise AppError(ErrorCode.NOT_A_PDF, "文件不是有效的 PDF（魔数校验失败）")

    # 计算 MD5
    file_md5 = hashlib.md5(content).hexdigest()  # noqa: S324

    # MD5 去重
    with _registry_lock:
        if file_md5 in _md5_index:
            existing_id = _md5_index[file_md5]
            info = _registry[existing_id]
            logger.info("md5 dedup hit: %s → existing file_id=%s", file_md5, existing_id)
            return UploadResponse(
                file_id=existing_id,
                filename=info["filename"],
                size=info["size"],
                md5=file_md5,
                cached=True,
                created_at=datetime.fromisoformat(info["created_at"]),
            )

        # 新文件：写入磁盘
        file_id = uuid.uuid4().hex
        upload_dir = _ensure_upload_dir()
        dest = upload_dir / f"{file_id}.pdf"
        dest.write_bytes(content)

        now = datetime.now(tz=timezone.utc)
        filename = file.filename or "unknown.pdf"

        _registry[file_id] = {
            "filename": filename,
            "path": str(dest),
            "size": file_size,
            "md5": file_md5,
            "created_at": now.isoformat(),
        }
        _md5_index[file_md5] = file_id
        _save_registry()

    logger.info("file saved: id=%s name=%s size=%d md5=%s", file_id, filename, file_size, file_md5)
    return UploadResponse(
        file_id=file_id,
        filename=filename,
        size=file_size,
        md5=file_md5,
        cached=False,
        created_at=now,
    )


def resolve_file(file_id: str) -> Path:
    """根据 file_id 解析文件路径，校验存在且未过期。"""
    cfg = get_config()
    with _registry_lock:
        info = _registry.get(file_id)
    if info is None:
        raise AppError(ErrorCode.FILE_ID_NOT_FOUND, f"file_id 不存在: {file_id}")

    # 检查 TTL
    created_at = datetime.fromisoformat(info["created_at"])
    if cfg.upload_ttl_hours > 0:
        expires_at = created_at + timedelta(hours=cfg.upload_ttl_hours)
        if datetime.now(tz=timezone.utc) > expires_at:
            raise AppError(ErrorCode.FILE_ID_NOT_FOUND, f"文件已过期: {file_id}")

    path = Path(info["path"])
    if not path.exists():
        raise AppError(ErrorCode.FILE_ID_NOT_FOUND, f"文件已从磁盘删除: {file_id}")

    return path


def delete_file(file_id: str) -> FileDeleteResponse:
    """手动删除文件、注册表条目、缓存、md5_index。"""
    with _registry_lock:
        info = _registry.pop(file_id, None)
        if info is None:
            return FileDeleteResponse(file_id=file_id, deleted=False)
        md5 = info.get("md5", "")
        _md5_index.pop(md5, None)
        _save_registry()

    # 删除磁盘文件
    path = Path(info["path"])
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning("failed to delete file on disk: %s", e)

    # 清除关联缓存
    _cache_invalidate(file_id)

    logger.info("file deleted: id=%s", file_id)
    return FileDeleteResponse(file_id=file_id, deleted=True)


def cleanup_expired_files() -> int:
    """扫描注册表，删除所有过期文件。返回清理数量。"""
    cfg = get_config()
    if cfg.upload_ttl_hours <= 0:
        return 0

    now = datetime.now(tz=timezone.utc)
    expired_ids: list[str] = []

    with _registry_lock:
        for fid, info in list(_registry.items()):
            created_at = datetime.fromisoformat(info["created_at"])
            if now > created_at + timedelta(hours=cfg.upload_ttl_hours):
                expired_ids.append(fid)

        for fid in expired_ids:
            info = _registry.pop(fid)
            md5 = info.get("md5", "")
            _md5_index.pop(md5, None)
            # 删除磁盘文件
            path = Path(info["path"])
            try:
                if path.exists():
                    path.unlink()
            except OSError as e:
                logger.warning("cleanup: failed to delete %s: %s", path, e)
            # 清除缓存
            _cache_invalidate(fid)

        if expired_ids:
            _save_registry()

    if expired_ids:
        logger.info("cleanup: removed %d expired files", len(expired_ids))
    return len(expired_ids)


# ---------------------------------------------------------------------------
# URL 下载
# ---------------------------------------------------------------------------


def _download_from_url(file_url: str) -> tuple[str, Path]:
    """从 URL 下载 PDF 文件，进行 MD5 去重并注册到文件注册表。

    流程：
    1. 校验 URL scheme（仅支持 http / https）
    2. 流式下载，边读边计算 MD5，同时检查大小上限
    3. 校验 PDF 魔数
    4. MD5 去重（命中则直接返回已有 file_id）
    5. 未命中则写入磁盘并注册

    返回 (file_id, Path)
    """
    cfg = get_config()

    # 1. 校验 URL scheme
    parsed = urllib.parse.urlparse(file_url)
    if parsed.scheme not in ("http", "https"):
        raise AppError(
            ErrorCode.FILE_URL_INVALID,
            f"不支持的 URL 协议: {parsed.scheme}，仅支持 http / https",
        )

    max_bytes = cfg.download_max_size_mb * 1024 * 1024
    timeout = cfg.download_timeout_seconds

    # 2. 发起 GET 请求
    req = urllib.request.Request(file_url, method="GET")
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AppError(
            ErrorCode.FILE_URL_DOWNLOAD_FAILED,
            f"下载失败: {e}",
        ) from e

    # 检查 HTTP 状态码
    status_code = response.getcode()
    if status_code != 200:
        response.close()
        raise AppError(
            ErrorCode.FILE_URL_DOWNLOAD_FAILED,
            f"服务器返回非 200 状态码: {status_code}",
        )

    # 检查 Content-Length（如有）
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        length = int(content_length)
        if length > max_bytes:
            response.close()
            raise AppError(
                ErrorCode.FILE_URL_TOO_LARGE,
                f"文件大小 {length} 字节超过上限 {cfg.download_max_size_mb}MB",
            )

    # 3. 流式读取响应体，积累内存 + 计算 MD5
    chunk_size = 64 * 1024  # 64KB
    content_parts: list[bytes] = []
    total = 0
    md5_hash = hashlib.md5()  # noqa: S324
    try:
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            content_parts.append(chunk)
            md5_hash.update(chunk)
            total += len(chunk)
            if total > max_bytes:
                response.close()
                raise AppError(
                    ErrorCode.FILE_URL_TOO_LARGE,
                    f"下载内容超过上限 {cfg.download_max_size_mb}MB",
                )
    except (urllib.error.URLError, OSError) as e:
        raise AppError(
            ErrorCode.FILE_URL_DOWNLOAD_FAILED,
            f"下载中断: {e}",
        ) from e
    finally:
        response.close()

    content = b"".join(content_parts)
    file_md5 = md5_hash.hexdigest()

    # 4. 校验 PDF 魔数
    if len(content) < 4 or content[:4] != b"%PDF":
        raise AppError(ErrorCode.NOT_A_PDF, "下载的文件不是有效的 PDF（魔数校验失败）")

    # 5. MD5 去重
    filename = Path(urllib.parse.unquote(parsed.path)).name or "downloaded.pdf"

    with _registry_lock:
        if file_md5 in _md5_index:
            existing_id = _md5_index[file_md5]
            info = _registry[existing_id]
            logger.info("md5 dedup hit: file_url → existing file_id=%s", existing_id)
            return (existing_id, Path(info["path"]))

        # 6. 写入磁盘并注册
        file_id = uuid.uuid4().hex
        upload_dir = _ensure_upload_dir()
        dest = upload_dir / f"{file_id}.pdf"
        dest.write_bytes(content)

        now = datetime.now(tz=timezone.utc)
        _registry[file_id] = {
            "filename": filename,
            "path": str(dest),
            "size": total,
            "md5": file_md5,
            "created_at": now.isoformat(),
        }
        _md5_index[file_md5] = file_id
        _save_registry()

    logger.info("file downloaded: id=%s name=%s size=%d url=%s", file_id, filename, total, file_url)
    return (file_id, dest)


# ---------------------------------------------------------------------------
# 结果缓存
# ---------------------------------------------------------------------------


def _make_cache_key(file_id: str, request: ExtractRequest) -> str:
    """基于 file_id + 所有提取参数生成缓存键。"""
    # 将所有影响结果的参数序列化后做 hash
    parts = [
        file_id,
        request.pages,
        request.flavor,
        str(request.line_scale),
        str(request.split_text),
        str(request.flag_size),
        request.strip_text or "",
        str(request.process_background),
    ]
    # lattice 参数
    if request.flavor == "lattice":
        parts += [
            str(request.line_tol),
            str(request.joint_tol),
            str(request.threshold_blocksize),
            str(request.threshold_constant),
            str(request.iterations),
            str(request.resolution),
        ]
    else:
        parts += [
            str(request.edge_tol),
            str(request.row_tol),
            str(request.column_tol),
        ]
    raw = ":".join(parts)
    param_hash = hashlib.md5(raw.encode()).hexdigest()  # noqa: S324
    return f"{file_id}:{param_hash}"


def _cache_get(key: str) -> ExtractResponse | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_set(key: str, response: ExtractResponse) -> None:
    cfg = get_config()
    with _cache_lock:
        # 淘汰最旧条目
        while len(_cache) >= cfg.cache_max_entries and _cache_order:
            oldest = _cache_order.pop(0)
            _cache.pop(oldest, None)
        _cache[key] = response
        _cache_order.append(key)


def _cache_invalidate(file_id: str) -> None:
    """删除某 file_id 的所有缓存条目。"""
    with _cache_lock:
        keys_to_remove = [k for k in _cache if k.startswith(f"{file_id}:")]
        for k in keys_to_remove:
            _cache.pop(k, None)
            try:
                _cache_order.remove(k)
            except ValueError:
                pass
    if keys_to_remove:
        logger.info("cache invalidated: %d entries for file_id=%s", len(keys_to_remove), file_id)


# ---------------------------------------------------------------------------
# camelot 提取
# ---------------------------------------------------------------------------


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
        "split_text": request.split_text,
        "flag_size": request.flag_size,
        "strip_text": request.strip_text,
    }
    if request.copy_text is not None:
        kwargs["copy_text"] = request.copy_text
    if request.shift_text is not None:
        kwargs["shift_text"] = request.shift_text
    if request.flavor == "lattice":
        kwargs["line_scale"] = request.line_scale
        kwargs["process_background"] = request.process_background
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


def _do_extract(file_path: str, request: ExtractRequest) -> ExtractResponse:
    """实际执行 camelot 提取（不含缓存逻辑）。"""
    config = get_config()
    start = time.perf_counter()

    logger.info("start extract: %s pages=%s flavor=%s", file_path, request.pages, request.flavor)

    kwargs = _build_camelot_kwargs(request)
    tables = camelot.read_pdf(file_path, pages=request.pages, **kwargs)

    actual_flavor = request.flavor
    if tables.n == 0 and request.flavor == "lattice" and config.fallback_to_stream:
        logger.info("lattice returned 0 tables, falling back to stream")
        # 重建 kwargs，使用 stream flavor（避免 lattice 专属参数污染）
        stream_request = request.model_copy(update={"flavor": "stream"})
        kwargs = _build_camelot_kwargs(stream_request)
        tables = camelot.read_pdf(file_path, pages=request.pages, **kwargs)
        actual_flavor = "stream"

    elapsed = time.perf_counter() - start
    logger.info("extract done: %d tables in %.2fs (flavor=%s)", tables.n, elapsed, actual_flavor)
    return _build_response(request, tables)


def extract_tables(request: ExtractRequest) -> ExtractResponse:
    """执行 PDF 表格提取，支持 file_path / file_id / file_url，带结果缓存。

    - file_path 模式：直接使用本地路径，不走缓存（向后兼容）
    - file_id 模式：resolve 路径后，先查缓存再执行提取
    - file_url 模式：自动下载文件并注册，然后走 file_id 的缓存+提取流程
    """
    try:
        if request.file_url:
            # file_url 模式：下载 + MD5 去重 + 注册，然后走缓存
            file_id, _ = _download_from_url(request.file_url)

            # 复用 file_id 的缓存和提取逻辑
            cache_key = _make_cache_key(file_id, request)
            cached = _cache_get(cache_key)
            if cached is not None:
                logger.info("cache hit: file_url → file_id=%s key=%s", file_id, cache_key[:12])
                return cached

            file_path = str(resolve_file(file_id))
            result = _do_extract(file_path, request)

            if result.success:
                _cache_set(cache_key, result)
            return result

        if request.file_id:
            # file_id 模式：支持缓存
            cache_key = _make_cache_key(request.file_id, request)
            cached = _cache_get(cache_key)
            if cached is not None:
                logger.info("cache hit: file_id=%s key=%s", request.file_id, cache_key[:12])
                return cached

            file_path = str(resolve_file(request.file_id))
            result = _do_extract(file_path, request)

            if result.success:
                _cache_set(cache_key, result)
            return result
        else:
            # file_path 模式：传统方式
            _check_file(request.file_path)
            file_path = str(Path(request.file_path).resolve())
            return _do_extract(file_path, request)

    except AppError as e:
        logger.warning("app error: [%s] %s", e.code.value, e.message)
        return ExtractResponse(success=False, error=ErrorDetail(code=e.code, message=e.message))
    except Exception as e:
        logger.error("parse failed: %s", e, exc_info=True)
        return ExtractResponse(success=False, error=ErrorDetail(code=ErrorCode.PARSE_FAILED, message=str(e)))


warnings.filterwarnings("ignore", module="camelot")
