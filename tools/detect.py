#!/usr/bin/env python3
"""PDF 表格检测 CLI —— 只依赖 camelot-py，与 camelot-api 服务完全解耦。

用法:
    uv run python tools/detect.py demo6.pdf
    uv run python tools/detect.py demo6.pdf -f stream
    uv run python tools/detect.py demo6.pdf -s                   # split-text
    uv run python tools/detect.py demo6.pdf -f lattice -S 40     # line_scale=40
    uv run python tools/detect.py demo6.pdf -p 1                 # 只测第 1 页
    uv run python tools/detect.py demo6.pdf --json               # JSON 输出
    uv run python tools/detect.py demo6.pdf --json | jq          # 管道下游工具

宽表格（超终端宽度）自动导出 HTML:
    uv run python tools/detect.py demo6.pdf                      # 生成 report.html
    uv run python tools/detect.py demo6.pdf --out result         # 生成 result.html
    uv run python tools/detect.py demo6.pdf --open               # 导出后自动用浏览器打开
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import webbrowser
from pathlib import Path

import camelot
from tabulate import tabulate


def build_kwargs(args: argparse.Namespace) -> dict:
    kwargs: dict = {
        "flavor": args.flavor,
        "pages": args.pages,
        "split_text": args.split_text,
        "flag_size": args.flag_size,
        "strip_text": args.strip_text,
        "process_background": args.process_background,
    }
    # 过滤掉 None
    kwargs = {k: v for k, v in kwargs.items() if v is not None and v is not False}

    if args.flavor == "lattice":
        kwargs["line_scale"] = args.line_scale
        for key in ("line_tol", "joint_tol", "threshold_blocksize",
                     "threshold_constant", "iterations", "resolution"):
            val = getattr(args, key)
            if val is not None:
                kwargs[key] = val
    else:
        # stream 不支持 line_scale / process_background
        kwargs.pop("process_background", None)
        for key in ("edge_tol", "row_tol", "column_tol"):
            val = getattr(args, key)
            if val is not None:
                kwargs[key] = val

    if args.copy_text:
        kwargs["copy_text"] = args.copy_text
    if args.shift_text:
        kwargs["shift_text"] = args.shift_text

    return kwargs


def _display_width(s: str) -> int:
    """字符串在终端中的显示宽度（CJK 全角占 2，其余占 1）。"""
    return sum(
        2 if 0x2E80 < ord(ch) < 0x10000 else 1
        for ch in s
    )


def _grid_text(t) -> str:
    """渲染单个表格为 tabulate grid 文本（换行转空格）。"""
    data = []
    for r in range(t.shape[0]):
        row = []
        for c in range(t.shape[1]):
            row.append(str(t.df.iloc[r, c]).replace("\n", " ").strip())
        data.append(row)
    return tabulate(data, tablefmt="grid")


def _table_display_width(t) -> int:
    """计算表格渲染后的显示宽度（CJK 感知）。"""
    return max(_display_width(line) for line in _grid_text(t).splitlines())


def _html_for_tables(tables) -> str:
    """把宽表格列表渲染成自包含 HTML（用 camelot 自带的 df.to_html）。"""
    parts: list[str] = []
    for i, t in enumerate(tables):
        parts.append(
            f'<h3>表格 {i+1}/{len(tables)}　page={t.page}　'
            f'{t.shape[0]}×{t.shape[1]}　精度 {t.accuracy:.0f}%</h3>'
        )
        html = t.df.to_html(index=False, header=False, border=1, escape=True,
                             justify="left", classes="dataframe")
        html = html.replace("\\n", "<br>")
        parts.append(f'<div class="table-scroll">{html}</div>')
    body = "".join(parts)
    return (
        '<!DOCTYPE html>\n<meta charset="utf-8">\n<title>camelot 表格导出</title>\n<style>'
        'body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;'
        'margin:24px;color:#222}'
        'table{border-collapse:collapse}'
        'td{border:1px solid #bbb;padding:4px 8px;vertical-align:top;'
        'white-space:pre;word-break:keep-all}'
        '.table-scroll{overflow-x:auto;margin-bottom:32px}'
        '</style>\n\n' + body + "\n"
    )


def print_human(tables, elapsed: float, flavor: str, out_prefix: str, auto_open: bool) -> None:
    print(f"检测结果: {tables.n} 个表格  |  耗时 {elapsed:.2f}s")

    if tables.n == 0:
        print("未检测到表格。")
        return

    tw = shutil.get_terminal_size().columns
    wide_tables: list = []  # 超宽、需导出 HTML 的表

    for i, t in enumerate(tables):
        header = (f"── 表格 {i+1}/{tables.n} ──  page={t.page}  "
                  f"{t.shape[0]}×{t.shape[1]}  精度 {t.accuracy:.0f}%  "
                  f"bbox=({t._bbox[0]:.0f},{t._bbox[1]:.0f})-"
                  f"({t._bbox[2]:.0f},{t._bbox[3]:.0f})")

        if _table_display_width(t) <= tw:
            # 窄表：终端内联渲染
            print()
            print(header)
            print()
            print(_grid_text(t))
            print()
        else:
            # 宽表：终端只打摘要行，稍后导出 HTML
            wide_tables.append(t)
            print()
            print(f"{header}  → 导出 {out_prefix}.html ({t.shape[1]} 列超宽，终端无法完整展示)")

    if wide_tables:
        html_path = Path(f"{out_prefix}.html").resolve()
        html_path.write_text(_html_for_tables(wide_tables), encoding="utf-8")
        print()
        print(f"→ 已导出 {html_path}（{len(wide_tables)} 个宽表），请用浏览器打开查看完整表格")
        if auto_open:
            url = html_path.as_uri()
            print(f"→ 正在打开浏览器: {url}")
            opened = webbrowser.open(url)
            if not opened:
                print(f"  webbrowser.open 返回 False，请手动打开 {html_path}", file=sys.stderr)


def print_json(tables, elapsed: float, kwargs: dict) -> None:
    table_list: list[dict] = []
    for i, t in enumerate(tables):
        cells: list[dict] = []
        for r in range(t.shape[0]):
            for c in range(t.shape[1]):
                cell = t.cells[r][c]
                cells.append({
                    "row": r, "col": c,
                    "text": cell.text.strip() if cell.text else "",
                    "bbox": {"x1": cell.x1, "y1": cell.y1, "x2": cell.x2, "y2": cell.y2},
                })
        table_list.append({
            "table_index": i,
            "page": t.page,
            "rows": t.shape[0],
            "cols": t.shape[1],
            "accuracy": t.accuracy,
            "whitespace": t.whitespace,
            "flavor": t.flavor,
            "order": t.order,
            "bbox": {"x1": t._bbox[0], "y1": t._bbox[1], "x2": t._bbox[2], "y2": t._bbox[3]},
            "cells": cells,
        })

    print(json.dumps({
        "success": True,
        "total_tables": tables.n,
        "tables": table_list,
        "elapsed_seconds": round(elapsed, 3),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF 表格检测（独立脚本，仅依赖 camelot）")
    parser.add_argument("pdf", type=str, help="PDF 文件路径")
    parser.add_argument("-f", "--flavor", choices=["lattice", "stream"], default="lattice",
                        help="解析模式 (default: lattice)")
    parser.add_argument("-S", "--line-scale", type=int, default=15,
                        help="线条缩放 (default: 15, lattice only)")
    parser.add_argument("-p", "--pages", default="all",
                        help="页码范围: all / 1 / 1-3 / 1,3,5 (default: all)")
    parser.add_argument("-s", "--split-text", action="store_true",
                        help="拆分跨行文本")
    parser.add_argument("--flag-size", action="store_true",
                        help="检测字体大小（较慢）")
    parser.add_argument("--strip-text", default=None, help="要去除的字符")
    parser.add_argument("--copy-text", nargs=2, metavar=("OLD", "NEW"), default=None,
                        help="文本替换，如 --copy-text '旧' '新'")
    parser.add_argument("--shift-text", nargs=2, metavar=("DIR", "LEN"), default=None,
                        help="文本偏移，如 --shift-text l 5")
    parser.add_argument("--process-background", action="store_true",
                        help="处理背景 (lattice only)")
    parser.add_argument("--fallback", action="store_true",
                        help="lattice 无结果时自动回退 stream")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--out", default="report", metavar="PREFIX",
                        help="宽表格导出 HTML 的文件名前缀 (default: report → report.html)")
    parser.add_argument("--open", action="store_true",
                        help="导出 HTML 后自动用浏览器打开")

    # lattice 参数
    lg = parser.add_argument_group("lattice 参数")
    lg.add_argument("--line-tol", type=int)
    lg.add_argument("--joint-tol", type=int)
    lg.add_argument("--threshold-blocksize", type=int)
    lg.add_argument("--threshold-constant", type=int)
    lg.add_argument("--iterations", type=int)
    lg.add_argument("--resolution", type=int)

    # stream 参数
    sg = parser.add_argument_group("stream 参数")
    sg.add_argument("--edge-tol", type=int)
    sg.add_argument("--row-tol", type=int)
    sg.add_argument("--column-tol", type=int)

    args = parser.parse_args()

    pdf_path = str(Path(args.pdf).resolve())
    if not Path(pdf_path).exists():
        print(f"错误：文件不存在 — {pdf_path}", file=sys.stderr)
        sys.exit(1)

    kwargs = build_kwargs(args)

    start = time.perf_counter()
    tables = camelot.read_pdf(pdf_path, **kwargs)
    elapsed = time.perf_counter() - start

    actual_flavor = args.flavor
    if tables.n == 0 and args.flavor == "lattice" and args.fallback:
        kwargs["flavor"] = "stream"
        kwargs.pop("line_scale", None)
        kwargs.pop("process_background", None)
        kwargs.pop("line_tol", None)
        kwargs.pop("joint_tol", None)
        kwargs.pop("threshold_blocksize", None)
        kwargs.pop("threshold_constant", None)
        kwargs.pop("iterations", None)
        kwargs.pop("resolution", None)
        start = time.perf_counter()
        tables = camelot.read_pdf(pdf_path, **kwargs)
        elapsed = time.perf_counter() - start
        actual_flavor = "stream"

    if args.json:
        print_json(tables, elapsed, kwargs)
    else:
        print_human(tables, elapsed, actual_flavor, args.out, args.open)


if __name__ == "__main__":
    main()
