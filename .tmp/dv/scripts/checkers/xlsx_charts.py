#!/usr/bin/env python3
"""xlsx 图表数据标注审计：标注成分是否重复图例/类目轴、标注是否互相压盖。

为什么必须有这一项：脚本生成的 xlsx 图表普遍只显式打开 `showVal`，剩下的
`showSerName` / `showCatName` / `showLegendKey` 既不开也不关（openpyxl 不写元素 → XML 里缺省），
而渲染器对缺省成分的默认行为是**一并显示**。于是每个柱/线节点的标注都变成
"色块 + 公司全称(股票代码) + 年份 + 数值"四段——色块与系列名是右侧图例已经表达的内容、
年份是类目轴已经表达的内容，属于逐点重复；标注还因此宽到一百多 pt，在相邻标注只有一二十 pt
间距的图里互相压盖，数值本身反而读不出来。打得开、数据绑定也对，纯结构层能给出结论的
排版缺陷，这是一类。

本模块只做**分析**，档位与输出交给 `defect_check.py`，全技能只有一套 `checks[].status` 标准：
- 冗余成分 + 压盖同时命中 → fail（重复且压盖，图表不可读，证据充分）
- 只命中其一 → warn（可能是刻意标注；宽度是不建模自动换行的**上界**，单独不足以判 must 不满足）

零第三方依赖（openpyxl 由调用方保证已可用）。永不抛栈：单张图表出错只跳过该图。
"""
import re

EMU_PER_PT = 12700
EMU_PER_CM = 360000

# 绘图区占图框的比例：右侧图例吃掉约 3 成宽度，无图例时只扣值轴刻度
PLOT_W_RATIO = 0.70
PLOT_W_RATIO_NOLEGEND = 0.85

LABEL_FONT_PT = 10.0            # Excel 数据标注默认字号
ASCII_W_PT = LABEL_FONT_PT * 0.55
CJK_W_PT = LABEL_FONT_PT * 1.0

DEFAULT_GAP_WIDTH = 150.0       # 柱图 gapWidth 缺省值（%），决定同类目内相邻柱心距
DEFAULT_FRAME_CM = (15.0, 7.5)  # openpyxl 图表默认尺寸，anchor 无 ext 时的回退

MAX_CHARTS = 20                 # 最多审计几张图，防超大工作簿拖死
MAX_HITS = 8                    # 单张图 detail 里最多列几条命中

_REF_RE = re.compile(
    r"^(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$"
)


def _col_idx(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _ref_values(wb, f):
    """把 `'sheet'!$B$7:$F$7` 这类引用读成值列表；解析不了就返回 []。"""
    m = _REF_RE.match((f or "").strip())
    if not m:
        return []
    title = (m.group(1) or m.group(2) or "").replace("''", "'")
    if title not in wb.sheetnames:
        return []
    ws = wb[title]
    c1, r1 = _col_idx(m.group(3)), int(m.group(4))
    c2 = _col_idx(m.group(5)) if m.group(5) else c1
    r2 = int(m.group(6)) if m.group(6) else r1
    out = []
    for r in range(r1, min(r2, r1 + 4096) + 1):
        for c in range(c1, min(c2, c1 + 256) + 1):
            out.append(ws.cell(r, c).value)
    return out


def _cache_values(src):
    """优先用图表里缓存的点值（numCache / strCache），省一次单元格读取。"""
    for attr in ("numCache", "strCache"):
        cache = getattr(src, attr, None)
        if cache is not None and getattr(cache, "pt", None):
            return [p.v for p in cache.pt]
    return []


def _chart_title(chart):
    try:
        runs = chart.title.tx.rich.p[0].r
        return "".join(r.t or "" for r in runs).strip()
    except Exception:
        return ""


def _where(ws, idx, chart):
    title = _chart_title(chart)
    tail = f"（{title}）" if title else ""
    return f"{ws.title}!图表{idx}{tail}"


def audit(wb):
    """返回 (findings, charts_total)。

    findings 每项：{where, kind, labels, redundant[], overlaps, hits[]}；
    没开数据标注的图表只计数，不产出 finding。
    """
    findings, total = [], 0
    for ws in wb.worksheets:
        for idx, chart in enumerate(getattr(ws, "_charts", []) or [], 1):
            total += 1
            if total > MAX_CHARTS:
                return findings, total
            try:
                f = _audit_chart(wb, ws, idx, chart)
            except Exception:
                continue  # 单图异常不影响其余图表，也不影响主流程
            if f is not None:
                findings.append(f)
    return findings, total


def _label_flags(chart):
    """合并图表组级 dLbls 与各系列 dLbls，回报每个成分是否会被渲染。

    只有显式 False 才算关闭；缺省（None，即 XML 里没写这个元素）按"会显示"处理——
    本 case 的截图实测就是缺省时色块/系列名/类目名被一并画出来。宁可按渲染器的实际行为判，
    不按"没写就是不显示"想当然。
    """
    holders = [chart.dLbls] + [s.dLbls for s in chart.series]
    holders = [h for h in holders if h is not None]
    if not holders:
        return None
    flags = {}
    for key in ("showVal", "showSerName", "showCatName", "showLegendKey", "showPercent"):
        vals = [getattr(h, key, None) for h in holders]
        flags[key] = any(v is not False for v in vals)
    return flags


def _has_legend(chart):
    legend = getattr(chart, "legend", None)
    return bool(legend is not None and getattr(legend, "position", None))


def _has_cat_axis(chart):
    ax = getattr(chart, "x_axis", None)
    return bool(ax is not None and getattr(ax, "delete", None) is not True)


def _redundant_parts(chart, flags):
    """标注里与图例 / 类目轴重复的成分。showVal / showPercent 是唯一增量信息，不计。"""
    parts = []
    if _has_legend(chart):
        if flags["showLegendKey"]:
            parts.append("图例色块(showLegendKey 未显式关闭)")
        if flags["showSerName"]:
            parts.append("系列名(showSerName 未显式关闭)")
    if _has_cat_axis(chart) and flags["showCatName"]:
        parts.append("类目名(showCatName 未显式关闭)")
    return parts


def _frame_pt(chart):
    """图框尺寸（pt）：优先用 anchor 的 ext，缺失时回退 chart.width/height（cm）。"""
    ext = getattr(getattr(chart, "anchor", None), "ext", None)
    cx = getattr(ext, "cx", None) or (chart.width or DEFAULT_FRAME_CM[0]) * EMU_PER_CM
    cy = getattr(ext, "cy", None) or (chart.height or DEFAULT_FRAME_CM[1]) * EMU_PER_CM
    return cx / EMU_PER_PT, cy / EMU_PER_PT


def _text_width(s):
    """单行文本宽度（pt）：CJK 按 1.0em，其余按 0.55em。"""
    return sum(CJK_W_PT if ord(c) > 0x2E80 else ASCII_W_PT for c in str(s))


def _fmt_num(v, numfmt):
    if v is None:
        return ""
    if not isinstance(v, (int, float)):
        return str(v)
    if numfmt and "." in str(numfmt):
        try:
            return f"{v:,.{len(str(numfmt).split('.')[-1])}f}"
        except Exception:
            pass
    return f"{v:,.2f}"


def _series_meta(wb, chart):
    """每个系列取 (系列名, 点数, 最宽值文本)，另外取全图最宽类目名。"""
    numfmt = getattr(chart.dLbls, "numFmt", None) if chart.dLbls is not None else None
    metas, cats = [], []
    for s in chart.series:
        name = ""
        if s.tx is not None:
            ref = getattr(s.tx, "strRef", None)
            if getattr(s.tx, "v", None):
                name = str(s.tx.v)
            elif ref is not None:
                cached = _cache_values(ref)
                vals = cached or _ref_values(wb, ref.f)
                name = str(vals[0]) if vals and vals[0] is not None else ""
        vals = []
        if s.val is not None and s.val.numRef is not None:
            vals = _cache_values(s.val.numRef) or _ref_values(wb, s.val.numRef.f)
        widest = max((_fmt_num(v, numfmt) for v in vals), key=_text_width, default="")
        metas.append({"name": name, "points": len(vals), "value_text": widest})
        if not cats and s.cat is not None:
            src = getattr(s.cat, "numRef", None) or getattr(s.cat, "strRef", None)
            if src is not None:
                cats = [c for c in (_cache_values(src) or _ref_values(wb, src.f)) if c is not None]
    cat_text = max((str(c) for c in cats), key=_text_width, default="")
    return metas, cat_text


def _label_width(meta, cat_text, flags):
    """最坏情况单行宽度：系列名按内嵌换行切段，末段拼上 ", 类目名, 值"。

    不建模渲染器的自动换行，所以这是宽度**上界**；因此几何项单独只记 warn。
    """
    segs = str(meta["name"]).split("\n") if flags["showSerName"] and meta["name"] else [""]
    tail_parts = [segs[-1]]
    if flags["showCatName"] and cat_text:
        tail_parts.append(cat_text)
    if (flags["showVal"] or flags["showPercent"]) and meta["value_text"]:
        tail_parts.append(meta["value_text"])
    tail = ", ".join(p for p in tail_parts if p)
    return max([_text_width(s) for s in segs[:-1]] + [_text_width(tail)])


def _overlaps(chart, flags, metas, cat_text):
    """相邻标注的横向压盖：柱图比同类目内相邻柱心距，其余比相邻类目间距。"""
    npts = max((m["points"] for m in metas), default=0)
    if npts < 1 or not metas:
        return 0, []
    frame_w, _ = _frame_pt(chart)
    plot_w = frame_w * (PLOT_W_RATIO if _has_legend(chart) else PLOT_W_RATIO_NOLEGEND)
    cat_pitch = plot_w / npts
    widths = [_label_width(m, cat_text, flags) for m in metas]
    hits, count = [], 0
    if type(chart).__name__ == "BarChart" and len(metas) > 1:
        gap = chart.gapWidth if chart.gapWidth is not None else DEFAULT_GAP_WIDTH
        pitch = cat_pitch / (len(metas) + gap / 100.0)
        for k in range(npts):
            for a in range(len(widths) - 1):
                need = (widths[a] + widths[a + 1]) / 2
                if need > pitch:
                    count += 1
                    if len(hits) < MAX_HITS:
                        hits.append(
                            f"类目{k + 1} 系列{a + 1}/{a + 2} 标注半宽和{need:.0f}pt>柱心距{pitch:.0f}pt"
                        )
    else:
        for j, w in enumerate(widths):
            if npts > 1 and w > cat_pitch:
                count += npts - 1
                if len(hits) < MAX_HITS:
                    hits.append(
                        f"系列{j + 1} 相邻类目标注宽{w:.0f}pt>类目间距{cat_pitch:.0f}pt"
                    )
    return count, hits


def _audit_chart(wb, ws, idx, chart):
    flags = _label_flags(chart)
    if not flags or not any(flags.values()):
        return None  # 没开数据标注：只计数，不产出 finding
    metas, cat_text = _series_meta(wb, chart)
    overlaps, hits = _overlaps(chart, flags, metas, cat_text)
    npts = max((m["points"] for m in metas), default=0)
    return {
        "where": _where(ws, idx, chart),
        "kind": type(chart).__name__,
        "labels": sum(m["points"] for m in metas),
        "series": len(metas),
        "points": npts,
        "redundant": _redundant_parts(chart, flags),
        "overlaps": overlaps,
        "hits": hits,
    }
