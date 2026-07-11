# tools — PDF 表格检测工具

独立于 `camelot-api` HTTP 服务的命令行脚本，只依赖 `camelot-py`，无需启动服务即可对 PDF 文件执行表格检测。

## 用法

```bash
cd ..
uv run python tools/detect.py <pdf文件> [参数]
```

### 常用示例

```bash
# lattice 模式（默认，适合有边框表格）
uv run python tools/detect.py ./demo6.pdf

# stream 模式（适合无边框表格）
uv run python tools/detect.py ./demo6.pdf -f stream

# 调大 line_scale 增强线检测（对细线表格有效）
uv run python tools/detect.py ./demo6.pdf -S 40

# 拆分跨行文本
uv run python tools/detect.py ./demo6.pdf -s

# 指定页码范围
uv run python tools/detect.py ./demo6.pdf -p 1

# JSON 输出，配合 jq 使用
uv run python tools/detect.py ./demo6.pdf --json
uv run python tools/detect.py ./demo6.pdf --json | jq '.tables[].accuracy'
```

### 完整参数

| 参数 | 说明 |
|------|------|
| `-f` / `--flavor` | 解析模式：`lattice`（有边框）或 `stream`（无边框） |
| `-S` / `--line-scale` | 线条缩放参数，默认 15（仅 lattice） |
| `-p` / `--pages` | 页码范围：`all` / `1` / `1-3` / `1,3,5` |
| `-s` / `--split-text` | 拆分跨行文本 |
| `--flag-size` | 检测字体大小（较慢） |
| `--strip-text` | 要去除的字符 |
| `--copy-text` | 文本替换，如 `--copy-text '旧' '新'` |
| `--shift-text` | 文本偏移 |
| `--process-background` | 处理背景（仅 lattice） |
| `--fallback` | lattice 无结果时自动回退 stream |
| `--json` | JSON 格式输出 |
| `--line-tol` / `--joint-tol` | lattice 容差参数 |
| `--edge-tol` / `--row-tol` / `--column-tol` | stream 容差参数 |

## 快速参考

### 对不同风格 PDF 的建议

| PDF 类型 | 推荐参数 |
|----------|----------|
| 有明确边框线的表格 | `-f lattice`（默认） |
| 无线框、空格分隔的表格 | `-f stream` |
| 细线或低分辨率扫描件 | `-f lattice -S 40` 或 `-S 60` |
| 跨行合并的复杂表头 | `-s` 拆分跨行文本 |

### 结果解读

每个表格输出内容：

- **页面**：表格所在的 PDF 页码
- **形状**：`行数×列数`
- **精度**：0-100，越高说明解析结果越可信
- **空白**：单元格中空白的比例
- **左上 / 右下**：表格区域在 PDF 坐标系中的坐标（左下角为原点）
- **预览**：前 8 行列出的文本内容

---

*注意：脚本以 `tools/demo6.pdf` 形式引用项目根目录的文件，实际运行时需调整路径。*
