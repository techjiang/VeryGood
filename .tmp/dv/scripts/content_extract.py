#!/usr/bin/env python3
"""交付产物内容抽取（只读）：把 docx/pptx/xlsx/pdf/html 的正文与链接落到磁盘，
stdout 只回摘要与文件路径——**正文绝不进 stdout**，避免一次把上下文打满。

用法:
    python3 content_extract.py <file> [<file> ...] [--max-chars 200000]

**每个产物输出一行 JSON**（单个产物时就是一行，与旧行为一致）。多个 html 一次传入时，
它们会合并进**同一个浏览器会话**渲染，只付一次浏览器建连开销（约 3s），比逐条调用快得多。

落盘（工作目录下 .tmp/dv-extract-<名>-<路径hash>/）:
    content.txt  每行前缀定位锚，形如 `[docx:p12|H1] 第一章 概述`；grep 命中即自带位置
    links.json   去重后的链接清单 [{url, where[], source}]

stdout JSON:
    {
      "file", "ext", "content_file", "links_file",
      "text_chars", "lines", "truncated",
      "outline": [{anchor,label,level}],   # 上限 80 条
      "links_count", "meta": {...}, "notes": [...], "checks": [...], "error": null|str
    }
    `checks` 只在脚本量出确定问题时才有内容（fail / warn / 未覆盖声明），pass 一律不输出；
    html 的 `meta` 另含 `text_origin`（rendered_text / source_stripped）。

抽取实现按类型分模块（extractors/docx.py 等），本文件只做路由与落盘：
defect_check.py 走同一套 extractors，保证「一套解析、多处复用」。
html 的抽取会**自己驱动无头浏览器**加载页面（只导航取文本与探针、不截图），
故 html 产物的 bash timeout 需放宽（建议 180000）。永不抛栈。
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:  # 依赖自举：把技能缓存里的三方库挂进 sys.path（--doctor --install 装的就在那）
    import deps  # noqa: E402,F401
except Exception:
    deps = None
import extractors  # noqa: E402

MAX_CHARS = 200000
MAX_OUTLINE = 80
_TMP_ROOT = Path.cwd() / ".tmp"


def outdir_for(path):
    p = os.path.abspath(path)
    stem = re.sub(r"[^\w.-]+", "_", Path(p).stem) or "artifact"
    h = hashlib.sha1(p.encode()).hexdigest()[:8]
    d = _TMP_ROOT / f"dv-extract-{stem}-{h}"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def extract_all(path):
    """供 defect_check.py 复用：返回抽取结果 dict（含 units/links/outline/meta/notes）。"""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mod = extractors.load(ext)
    if mod is None:
        return {"units": [], "links": [], "outline": [], "meta": {}, "notes": [f".{ext} 不支持抽取"]}
    try:
        return mod.extract(path)
    except Exception as e:  # 抽取器内部已尽量兜底，这里是最后一道
        return {"units": [], "links": [], "outline": [], "meta": {}, "notes": [f"抽取异常: {e}"]}


def links_only(path):
    """只取链接的轻量路径（供 link_probe 复用）。

    html 走 `links_of_source`：链接在源码里就是完整的，**不触发浏览器渲染**——渲染要独占
    浏览器会话，若 link_probe 也去渲染就会和 extract 抢会话（曾导致 extract 渲染失败）。
    其他类型没有独占资源，直接复用完整抽取。
    """
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mod = extractors.load(ext)
    if mod is None:
        return []
    try:
        if hasattr(mod, "links_of_source"):
            return mod.links_of_source(path)
        return mod.extract(path).get("links") or []
    except Exception:
        return []


def write_content(outdir, units, max_chars):
    """每行前缀锚点写入 content.txt；超预算截断并标注。

    返回的字符数只算正文，不含 `[html:l12] ` 这类定位锚——量化判据（字数、篇幅）
    必须按正文算，把锚点计进去会让一份 250 字的产物看起来有 900 字。
    """
    lines, body_chars, written_chars, truncated = [], 0, 0, False
    for u in units:
        anchor = u.get("anchor") or "?"
        for raw in (u.get("text") or "").splitlines() or [""]:
            t = raw.strip()
            if not t:
                continue
            line = f"[{anchor}] {t}"
            if written_chars + len(line) > max_chars:
                truncated = True
                break
            lines.append(line)
            body_chars += len(t)
            written_chars += len(line) + 1
        if truncated:
            break
    if truncated:
        lines.append(f"[TRUNCATED] 已达 {max_chars} 字符上限，其余内容未写入")
    p = Path(outdir) / "content.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p), body_chars, written_chars, len(lines), truncated


def process_one(path, max_chars):
    """抽取单个产物并落盘，返回该产物的摘要 dict。"""
    out = {"file": path, "ext": os.path.splitext(path)[1].lower().lstrip("."), "error": None}
    if not os.path.exists(path):
        out["error"] = "file not found"
        return out
    if not extractors.supported(out["ext"]):
        out["error"] = f".{out['ext']} 不在抽取范围（仅 docx/pptx/xlsx/pdf/html）"
        return out

    res = extract_all(path)
    outdir = outdir_for(path)
    content_file, chars, _, lines, truncated = write_content(outdir, res.get("units") or [], max_chars)
    links = res.get("links") or []
    links_file = str(Path(outdir) / "links.json")
    Path(links_file).write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")

    outline = (res.get("outline") or [])[:MAX_OUTLINE]
    notes = list(res.get("notes") or [])
    if len(res.get("outline") or []) > MAX_OUTLINE:
        notes.append(f"大纲共 {len(res['outline'])} 条，仅回传前 {MAX_OUTLINE} 条")
    out.update(
        {
            "content_file": content_file,
            "links_file": links_file,
            "text_chars": chars,
            "lines": lines,
            "truncated": truncated,
            "outline": outline,
            "links_count": len(links),
            "meta": res.get("meta") or {},
            "notes": notes,
            "checks": res.get("checks") or [],
        }
    )
    return out


def prerender_html(paths):
    """多个 html 合并进同一个浏览器会话预渲染，把 N 次建连压成 1 次。"""
    htmls = [p for p in paths if p.lower().endswith(".html") and os.path.exists(p)]
    if len(htmls) < 2:
        return  # 单个 html 由 extract() 内部自己渲染，无需批量
    mod = extractors.load("html")
    if mod is None or not hasattr(mod, "render_batch"):
        return
    try:
        mod.render_batch(htmls)
    except Exception:
        pass  # 预渲染失败不阻断：extract() 里各自还有渲染与降级路径


def main():
    ap = argparse.ArgumentParser(description="Extract deliverable text/links (read-only).")
    ap.add_argument("files", nargs="+", help="产物路径（可多个；每个产物输出一行 JSON）")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    args = ap.parse_args()

    prerender_html(args.files)
    for path in args.files:
        print(json.dumps(process_one(path, args.max_chars), ensure_ascii=False))


if __name__ == "__main__":
    main()
