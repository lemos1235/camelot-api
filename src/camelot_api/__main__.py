"""python -m camelot_api entry point — starts the HTTP server."""

from __future__ import annotations

import argparse

import uvicorn

from .config import get_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="camelot PDF table extraction RPC service",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="监听地址 (默认: $HOST 或 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口 (默认: $PORT 或 8000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="worker 数量 (默认: $WORKERS 或 1)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="日志级别 (默认: $LOG_LEVEL 或 INFO)",
    )
    args = parser.parse_args()

    config = get_config()
    host = args.host or config.host
    port = args.port or config.port
    workers = args.workers or config.workers
    log_level = (args.log_level or config.log_level).lower()

    print(f"camelot-api v{__import__('camelot_api').__version__}")
    print(f"Listening on http://{host}:{port}")
    print(f"Workers: {workers}, Log level: {log_level}")

    uvicorn.run(
        "camelot_api.server:app",
        host=host,
        port=port,
        workers=workers,
        log_level=log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
