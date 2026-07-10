# camelot-api

camelot PDF table extraction RPC service — 供 Rust 侧通过 HTTP 调用，返回表格及单元格的布局信息（含 bbox）。

## 快速开始

```bash
uv sync
uv run camelot-api --port 8000
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/extract` | 提取 PDF 表格 |

### 请求示例

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -H "Content-Type: application/json" \
  -d '{"file_path":"/path/to/input.pdf","pages":"all","flavor":"lattice"}'
```

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

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `WORKERS` | `1` | worker 数量 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FORMAT` | `text` | 日志格式 (`text` / `json`) |
| `CAMELOT_DEFAULT_FLAVOR` | `lattice` | 默认解析模式 |
| `CAMELOT_FALLBACK_STREAM` | `true` | lattice 无结果时回退 stream |
| `MAX_PDF_SIZE_MB` | `200` | PDF 文件大小上限 |

## 服务器部署

### 前提条件

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装系统依赖（camelot 需要 Ghostscript 做 PDF 渲染）
sudo apt install -y ghostscript
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
ExecStart=/opt/camelot-api/.venv/bin/uvicorn camelot_api.server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=LOG_LEVEL=INFO
Environment=LOG_FORMAT=json

[Install]
WantedBy=multi-user.target
EOF

# 3. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now camelot-api
sudo systemctl status camelot-api

# 4. 查看日志
journalctl -u camelot-api -f
```

### 方式二：Docker Compose（推荐）

```bash
# 1. 准备环境变量（可选）
cp .env.example .env
# 按需编辑 .env

# 2. 创建 PDF 数据目录
mkdir -p data/pdf

# 3. 构建并启动
docker compose up -d

# 4. 查看日志
docker compose logs -f

# 5. 停止
docker compose down
```

### 方式三：Docker（手动构建）

```bash
# 构建
docker build -t camelot-api .

# 运行
docker run -d \
  --restart=always \
  -p 127.0.0.1:8000:8000 \
  -v /data/pdf:/data/pdf:ro \
  --name camelot-api \
  camelot-api
```

## 项目结构

```
camelot-api/
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example             # Docker Compose 环境变量示例
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
