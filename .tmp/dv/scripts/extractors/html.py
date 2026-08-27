"""html 抽取：**自己驱动无头浏览器加载页面**，取渲染后的 innerText 与运行时探针；
浏览器不可用时退化为源码去标签。

为什么放在抽取里：html 的正文与缺陷证据都只有渲染后才成立（JS 生成的内容、白屏、
占位符残留、资源裂图）。渲染管线复用同目录 `browser.py` 的 `--no-shots` 路径——只做
导航 + 探针 + innerText 导出，不截图（本流程不做多模态视觉审核，不需要图片）。
落点仍是 `browser.outdir_for(path)`，与渲染阶段一致。

`import html` 命中标准库（py3 绝对导入），与本文件同名无冲突。
"""
import html as html_std
import json
import os
import re
from pathlib import Path

from .common import merge_links, text_urls

_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S)
_REF_RE = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', re.I)
RENDER_DPI = 120


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _fresh(artifact, produced):
    """已有渲染产物是否比产物本身新（产物改过就必须重渲染）。"""
    try:
        return os.path.getmtime(produced) >= os.path.getmtime(artifact)
    except Exception:
        return False


def _render_paths(path):
    """该产物的渲染落点与三个关键文件。render 不可用时返回 None。"""
    try:
        import browser
    except Exception:
        return None
    outdir = browser.outdir_for(path)
    return (
        outdir,
        os.path.join(outdir, "rendered_text.txt"),
        os.path.join(outdir, "probe.json"),
        os.path.join(outdir, "render_error.txt"),
    )


def _note_failure(path, why):
    """把渲染失败记在产物的渲染目录里：本轮内其他调用不再重复尝试。
    浏览器建连失败可能各耗 90s，批量预渲染 + 逐个 extract 会把同一个失败付 N+1 遍。"""
    p = _render_paths(path)
    if not p:
        return
    try:
        Path(p[0]).mkdir(parents=True, exist_ok=True)
        Path(p[3]).write_text(str(why), encoding="utf-8")
    except Exception:
        pass


def _clear_failure(path):
    p = _render_paths(path)
    if not p:
        return
    try:
        os.remove(p[3])
    except Exception:
        pass


def render_page(path):
    """驱动无头浏览器加载页面，返回 (渲染后文本|None, probe|None, 说明|None)。

    已有且未过期的渲染产物直接复用，避免同一产物重复付浏览器启动开销；
    已记录且未过期的失败标记同样直接复用，避免重复付失败耗时。
    """
    p = _render_paths(path)
    if not p:
        return None, None, "render 模块不可用"
    outdir, text_p, probe_p, err_p = p
    if os.path.exists(text_p) and _fresh(path, text_p):
        return _read(text_p), _load_probe(probe_p), None
    if os.path.exists(err_p) and _fresh(path, err_p):
        return None, None, f"{_read(err_p)}（本轮已尝试过，未重复渲染）"
    import browser

    try:
        res = browser.run(path, outdir, RENDER_DPI, shots=False)
    except Exception as e:
        why = f"浏览器渲染失败: {str(e)[:200]}"
        _note_failure(path, why)
        return None, None, why
    if res.get("error"):
        why = f"浏览器渲染失败: {str(res['error'])[:200]}"
        _note_failure(path, why)
        return None, None, why
    text = _read(text_p)
    if text is None:
        why = "渲染完成但未产出 rendered_text.txt"
        _note_failure(path, why)
        return None, _load_probe(probe_p), why
    _clear_failure(path)
    return text, _load_probe(probe_p), None


def _load_probe(p):
    raw = _read(p)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {"error": "probe.json unreadable"}


def needs_render(path):
    """是否需要（重新）渲染：没有渲染文本 / 渲染文本比产物旧 / 也没有新鲜的失败标记。"""
    p = _render_paths(path)
    if not p:
        return False
    _, text_p, _, err_p = p
    if os.path.exists(text_p) and _fresh(path, text_p):
        return False
    if os.path.exists(err_p) and _fresh(path, err_p):
        return False  # 本轮已失败过，别再试
    return True


def render_batch(paths):
    """多个 html 合并进**同一个浏览器会话**预渲染（供 content_extract.py 批量入口调用）。

    浏览器建连约 3s 且会话独占，逐个渲染 = N 次建连 + 排队等锁；合并后只建连一次。
    渲染结果落在各产物自己的 outdir，后续 `extract()` 会命中"已有且新鲜"分支直接复用；
    失败的产物会写下失败标记，`extract()` 也不会再重复尝试。
    返回 {path: None | 错误说明}。
    """
    try:
        import browser
    except Exception as e:
        why = f"render 模块不可用: {str(e)[:160]}"
        for p in paths:
            _note_failure(p, why)
        return {p: why for p in paths}
    items = [(p, browser.outdir_for(p)) for p in paths if needs_render(p)]
    if not items:
        return {}
    result = browser.render_html_batch(items)
    for path, err in result.items():
        if err:
            _note_failure(path, f"浏览器渲染失败: {str(err)[:200]}")
        else:
            _clear_failure(path)
    return result


def links_of_source(path):
    """只从源码抽链接，**不渲染**。

    链接（`href`/`src` 与正文裸链）在源码里就是完整的，渲染拿不到更多；而渲染要独占浏览器
    会话。link_probe 走这条路径，避免它为了取链接去抢浏览器——曾因此与 extract 并发撞车，
    导致 extract 的 run-code 被挤掉、html 退化成源码去标签。
    """
    source = _read(path) or ""
    links = text_urls(source, "源码")
    for m in _REF_RE.finditer(source):
        ref = m.group(1)
        if ref.lower().startswith(("http://", "https://")):
            links.append({"url": ref, "where": "源码引用", "source": "rel"})
    return merge_links(links)


_HTML_CHECK_ORDER = ("fail", "warn", "skip")
_HTML_CHECK_LIMIT = 80
_RENDER_ALL_SKIP = "未渲染成功，渲染层九项均未覆盖"


def _trim(text, limit=_HTML_CHECK_LIMIT):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _c(name, status, detail=""):
    return {"name": name, "status": status, "detail": _trim(detail)}


def _sample(items, width=28):
    """取第一条命中做定位提示——只回答"哪里"，不回举证数据。"""
    for item in items or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("url") or item.get("msg") or item.get("detail") or ""
        else:
            text = str(item)
        text = (text or "").strip().replace("\n", " ")
        if text:
            return _trim(text, width)
    return ""


def _pair(group, sep="→"):
    if not isinstance(group, dict):
        return "位置未记录"
    a = group.get("line") or group.get("panel") or group.get("a") or "元素"
    b = group.get("box") or group.get("over") or group.get("b") or "目标"
    return f"{a} {sep} {b}"


def _real_failed_requests(probe):
    proto = (probe or {}).get("protocol")
    items = probe.get("failed_requests") or []
    if proto == "setContent":
        return [x for x in items if not (isinstance(x, dict) and x.get("relative"))]
    return items


def _layout_skip_reason(layout):
    """几何整体不可信/没量成的原因；None 表示这次几何结论成立。"""
    if not isinstance(layout, dict):
        return "未产出排版几何"
    if not layout.get("available"):
        return _trim(layout.get("unavailable_reason") or "几何未产出", 48)
    if layout.get("trust") != "ok":
        return f"几何可信度 {layout.get('trust')}，结论不成立"
    if layout.get("settle_warning"):
        return "布局未落定就量了"
    if layout.get("truncated"):
        return "页面元素超上限被截断"
    return None


def _geometry_checks(layout):
    """线-框 / 浮框-正文 / 重复绘制三项；pass 不输出，未覆盖合并成一条。

    几何整体不可信时（无外部样式、布局未落定、元素截断）一律不出结论：此时量到的坐标
    是"没加载样式的页面"的坐标，报 fail 会造成假缺陷，比漏报更坏。
    """
    reason = _layout_skip_reason(layout)
    if reason:
        return [_c("layout", "skip", f"排版几何三项未覆盖：{reason}")]

    layout = layout if isinstance(layout, dict) else {}
    counts = layout.get("counts") if isinstance(layout.get("counts"), dict) else {}
    lines = counts.get("lines") or 0
    panels = counts.get("panels") or 0
    runs = counts.get("text_runs") or 0
    crosses = layout.get("line_crosses_box") or []
    flush = layout.get("line_flush_box_edge") or []
    over = layout.get("box_over_text") or []
    coincident = layout.get("coincident_lines") or []

    out, uncovered = [], []

    if crosses or flush:
        parts = []
        if crosses:
            parts.append(f"压穿内容框 {len(crosses)} 处（{_pair(crosses[0])} 等）")
        if flush:
            parts.append(f"贴框边并越出 {len(flush)} 处（{_pair(flush[0], '贴')} 等）")
        out.append(_c("layout_line_box", "fail", "装饰线" + "；".join(parts)))
    elif not lines:
        uncovered.append(("装饰线-内容框", "页面无装饰线，无输入"))

    if over:
        out.append(_c("layout_box_over_text", "fail",
                      f"浮框压住正文 {len(over)} 处（{_pair(over[0], '压')} 等）"))
    elif not panels or not runs:
        uncovered.append(("浮框-正文", "页面无浮框，无输入"))

    if coincident:
        out.append(_c("layout_coincident_lines", "warn", f"同段线重复绘制 {len(coincident)} 处"))
    elif not lines:
        uncovered.append(("重复绘制", "页面无装饰线，无输入"))

    # 装饰线被主动放弃（旋转/缩放）不是"没有缺陷"，必须留痕
    skipped_lines = counts.get("skipped_lines") or 0
    if skipped_lines:
        uncovered.append(("旋转/缩放装饰线", f"{skipped_lines} 条几何不可信被放弃"))

    if uncovered:
        why = uncovered[0][1]
        names = "、".join(n for n, _ in uncovered)
        if len(uncovered) >= 3 and len({r for _, r in uncovered}) == 1:
            out.append(_c("layout", "skip", f"排版几何三项未覆盖：{why}"))
        else:
            out.append(_c("layout", "skip", f"排版几何 {names} 未覆盖：{why}"))
    return out


def _probe_checks(probe):
    """html 渲染层判定：只回传 fail / warn / skip，pass 一律不输出。"""
    if not isinstance(probe, dict):
        return [_c("layout", "skip", _RENDER_ALL_SKIP)]

    checks = []
    audit = probe.get("audit") if isinstance(probe.get("audit"), dict) else {}
    # unavailable = 页面由 CLI 先打开、run-code 未再导航，监听器挂在加载之后：加载期三项
    # （failed_requests / console_errors / page_errors）为空只说明没查到，不等于没问题。
    lost = probe.get("load_events") == "unavailable"

    if probe.get("blank_page"):
        checks.append(_c("render_blank", "fail", "渲染后白屏，可见内容近乎为零"))

    placeholders = audit.get("placeholders") or []
    if placeholders:
        checks.append(_c("runtime_placeholder", "fail",
                         f"占位符残留 {len(placeholders)} 处（{_sample(placeholders)} 等）"))

    if probe.get("protocol") == "setContent":
        checks.append(_c("runtime_resource", "skip", "setContent 协议，资源与本地引用维度未覆盖"))
    else:
        failed = _real_failed_requests(probe)
        if failed:
            checks.append(_c("runtime_resource", "fail",
                             f"资源加载失败 {len(failed)} 处（{_sample(failed, 36)} 等）"))
        elif lost:
            checks.append(_c("runtime_resource", "skip", "加载期事件未捕获，资源加载维度未覆盖"))
    broken = audit.get("broken_images") or []
    if broken and probe.get("protocol") != "setContent":
        checks.append(_c("runtime_broken_image", "fail",
                         f"图片裂图 {len(broken)} 处（{_sample(broken, 36)} 等）"))

    errs = (probe.get("page_errors") or []) + (probe.get("console_errors") or [])
    if errs:
        checks.append(_c("runtime_error", "warn", f"运行时报错 {len(errs)} 处（{_sample(errs)} 等）"))
    elif lost:
        checks.append(_c("runtime_error", "skip", "加载期事件未捕获，运行时报错维度未覆盖"))

    over = [f"{k}={audit.get(k)}" for k in ("horizontal_overflow", "truncated_text", "empty_charts") if audit.get(k)]
    if over:
        checks.append(_c("runtime_overflow", "warn", "；".join(over)))

    if (probe.get("deck") or {}).get("suspect_hidden_pages"):
        checks.append(_c("deck_pagination", "skip", "疑似脚本翻页演示稿，除首屏外的页未覆盖"))

    checks.extend(_geometry_checks(probe.get("layout")))
    checks.sort(key=lambda c: (_HTML_CHECK_ORDER.index(c["status"]) if c["status"] in _HTML_CHECK_ORDER else 9, c["name"]))
    return checks


def extract(path):
    notes, units = [], []
    source = _read(path)
    if source is None:
        return {"units": [], "links": [], "outline": [], "meta": {}, "notes": ["html 读取失败"]}

    body, probe, why = render_page(path)
    origin = "rendered_text"
    if body is None:
        stripped = _TAG_RE.sub(" ", _DROP_RE.sub(" ", source))
        body = re.sub(r"[ \t]+", " ", html_std.unescape(stripped))
        origin = "source_stripped"
        notes.append(f"{why or '无渲染产物'}；正文退化为源码去标签，JS 动态生成的内容不在正文里")

    for i, line in enumerate(body.splitlines(), 1):
        t = line.strip()
        if t:
            units.append({"anchor": f"html:l{i}", "text": t})

    return {
        "units": units,
        "links": links_of_source(path),
        "outline": [],
        "meta": {"text_origin": origin},
        "notes": notes,
        "checks": _probe_checks(probe),
    }
