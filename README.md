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
User=nobody
WorkingDirectory=/opt/camelot-api
ExecStart=/root/.local/bin/uv run uvicorn camelot_api.server:app --host 127.0.0.1 --port 8000
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

### 方式二：Docker

```dockerfile
# Dockerfile
FROM ghcr.io/astral-sh/uv:python3.11-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ src/
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "camelot_api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

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

### 方式三：反向代理（nginx）

如果需要在生产环境暴露，建议前面放 nginx：

```nginx
server {
    listen 80;
    server_name camelot-api.example.com;

    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

## 项目结构

```
camelot-api/
├── pyproject.toml
├── .python-version
├── .gitignore
├── Dockerfile
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
