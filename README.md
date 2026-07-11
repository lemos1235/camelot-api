# camelot-api

camelot PDF table extraction RPC service — 供 Rust 侧通过 HTTP 调用，返回表格及单元格的布局信息（含 bbox）。

## 快速开始

```bash
uv sync
uv run camelot-api
```

默认监听 `0.0.0.0:8000`（值来自 `config.toml`，可被环境变量/CLI 覆盖，详见[配置](#配置)）。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/files/upload` | 上传 PDF 文件（返回 file_id，自动 MD5 去重） |
| `DELETE` | `/api/v1/files/{file_id}` | 删除已上传的文件及缓存 |
| `POST` | `/api/v1/extract` | 提取 PDF 表格（支持 file_id / file_url） |

### 上传文件

```bash
curl -X POST http://localhost:8000/api/v1/files/upload \
  -F "file=@/path/to/input.pdf"
```

响应：
```json
{
  "file_id": "a1b2c3d4...",
  "filename": "input.pdf",
  "size": 123456,
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "cached": false,
  "created_at": "2026-07-10T10:00:00Z"
}
```

- 同一文件（MD5 相同）重复上传会直接返回已有 `file_id`（`cached: true`），不重复存储

### 提取表格（使用 file_id，推荐）

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"file_id":"a1b2c3d4...","pages":"all","flavor":"lattice"}'
```

- 相同 `file_id` + 相同参数会自动命中结果缓存，秒级返回

### 提取表格（使用 file_url，支持远程 PDF）

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"file_url":"https://example.com/sample.pdf","pages":"all","flavor":"lattice"}'
```

- 自动下载远程 PDF 到本地，MD5 去重，支持结果缓存

### 响应结构

```json
{
  "success": true,
  "total_tables": 1,
  "tables": [
    {
      "table_index": 0,
      "page": 1,
      "rows": 4,
      "cols": 3,
      "accuracy": 90.6,
      "whitespace": 16.7,
      "flavor": "lattice",
      "order": 1,
      "bbox": {"x1": 72.0, "y1": 563.0, "x2": 523.0, "y2": 706.0},
      "cells": [
        {
          "row": 0,
          "col": 0,
          "text": "Header",
          "bbox": {"x1": 72.0, "y1": 690.0, "x2": 171.0, "y2": 706.0}
        }
      ]
    }
  ]
}
```

## 配置

配置优先级（从高到低）：CLI 参数 > 环境变量 > `config.toml` > 内置默认值。

应用配置默认值记录在项目根的 `config.toml`（复制自 `config.toml.example`）。裸机 / systemd 部署改这个文件即可；Docker Compose 默认使用内置默认值，并可通过 `.env` 的应用参数覆盖同名项。

```bash
cp config.toml.example config.toml   # 可选，不改则用内置默认值
```

### 应用配置（`config.toml` / 环境变量）

| 字段(toml) / 环境变量 | 默认值 | 说明 |
|------|--------|------|
| `host` / `HOST` | `0.0.0.0` | 监听地址 |
| `port` / `PORT` | `8000` | 监听端口 |
| `workers` / `WORKERS` | `1` | worker 数量 |
| `log_level` / `LOG_LEVEL` | `INFO` | 日志级别 |
| `log_format` / `LOG_FORMAT` | `text` | 日志格式 (`text` / `json`) |
| `default_flavor` / `CAMELOT_DEFAULT_FLAVOR` | `lattice` | 默认解析模式 |
| `fallback_to_stream` / `CAMELOT_FALLBACK_STREAM` | `true` | lattice 无结果时回退 stream |
| `line_scale` / `CAMELOT_LINE_SCALE` | `15` | 线条缩放参数 |
| `max_pdf_size_mb` / `MAX_PDF_SIZE_MB` | `200` | PDF 大小基线 (MB)，作为上传 / 下载大小上限的默认值 |
| `upload_dir` / `UPLOAD_DIR` | `~/.camelot-api/uploads` | 上传文件存储目录（`~` 自动展开） |
| `upload_max_size_mb` / `UPLOAD_MAX_SIZE_MB` | `200` | 上传文件大小上限 (MB)，未设则复用 `max_pdf_size_mb` |
| `upload_ttl_hours` / `UPLOAD_TTL_HOURS` | `24` | 上传文件保留时长（小时），过期后定时清理 |
| `upload_cleanup_interval_minutes` / `UPLOAD_CLEANUP_INTERVAL_MINUTES` | `30` | 定时清理间隔（分钟） |
| `cache_max_entries` / `CACHE_MAX_ENTRIES` | `1000` | 结果缓存最大条目数 |
| `url_download_timeout_seconds` / `URL_DOWNLOAD_TIMEOUT_SECONDS` | `30` | 远程 PDF 下载超时（秒） |
| `url_max_size_mb` / `URL_MAX_SIZE_MB` | `200` | 远程 PDF 大小上限 (MB)，未设则复用 `upload_max_size_mb` |

> 配置文件路径可用 `--config <path>` 或环境变量 `CONFIG_FILE` 指定。

## 服务器部署

### 前提条件

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装系统依赖（camelot 需要 Ghostscript 做 PDF 渲染）
sudo apt install -y ghostscript
```

应用配置默认值在 `config.toml`（可选，不改则用内置默认值）：

```bash
cp config.toml.example config.toml
```

### 方式一：systemd（裸机）

```bash
# 1. 部署代码
sudo mkdir -p /opt/camelot-api
sudo chown $USER:$USER /opt/camelot-api
git clone <repo> /opt/camelot-api
cd /opt/camelot-api
uv sync

# 2. 创建 systemd 服务
sudo tee /etc/systemd/system/camelot-api.service <<EOF
[Unit]
Description=camelot PDF table extraction API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/camelot-api
ExecStart=/opt/camelot-api/.venv/bin/camelot-api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 3. 配置（生产建议绑定回环，仅由前置反代对外）
cp config.toml.example config.toml
sed -i 's/^host = .*/host = "127.0.0.1"/' config.toml
# 按需编辑 config.toml 调整 worker / 日志 / 上传目录等

# 4. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now camelot-api
sudo systemctl status camelot-api

# 5. 查看日志
journalctl -u camelot-api -f
```

### 方式二：Docker Compose（推荐）

容器内使用内置默认值（等同 `config.toml`），可调参数通过 `.env` 覆盖：

```bash
# 1. 创建环境变量（从模板复制，按需编辑；仅用默认值可跳过）
cp .env.example .env

# 2. 创建数据目录
mkdir -p data/uploads

# 3. 构建并启动
docker compose up -d

# 4. 查看日志
docker compose logs -f

# 5. 停止
docker compose down
```

> `.env` 里的应用参数会被注入容器并覆盖内置默认值（全部留空即用默认值，可不创建 `.env`）。容器内监听 `0.0.0.0:8000`（由内置默认值决定），对外端口、PDF / 上传目录挂载均在 `docker-compose.yml` 中以默认值配置，按需直接编辑该文件。

### 方式三：Docker（手动构建）

```bash
# 构建
docker build -t camelot-api .

# 创建数据目录
mkdir -p data/uploads

# 运行
docker run -d \
  --restart=always \
  -p 127.0.0.1:8000:8000 \
  -v "$(pwd)/data/uploads:/data/uploads" \
  --name camelot-api \
  camelot-api
```

## 项目结构

```
camelot-api/
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example             # Docker Compose 部署变量示例
├── config.toml.example      # 应用配置基线示例（复制为 config.toml 使用）
├── Dockerfile
├── docker-compose.yml       # Docker Compose 编排
└── src/
    └── camelot_api/
        ├── __init__.py      # main() → 控制台入口
        ├── __main__.py      # python -m 入口
        ├── config.py        # 环境变量配置
        ├── errors.py        # ErrorCode 枚举 + AppError
        ├── logger.py        # 结构化日志
        ├── models.py        # Pydantic 请求/响应模型
        ├── server.py        # FastAPI 应用
        └── service.py       # camelot 调用核心
```
