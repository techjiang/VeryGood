#!/usr/bin/env python3
"""docx 静态页模型：把 body 推演成「页」，给空白页与页溢出提供确定性判据。

为什么必须有这一层：docx 本身**不存页**——页是渲染器按几何流式排出来的。于是
"每张图一页、不能有空页"这类需求，在没有页模型时技能一条证据都给不出，调用方只能靠
数 `w:br` 猜（实测已经猜错过：5 图 + 4 分页符被数成"5 页无空页"，真实渲染有空白页）。

本模块只做**分析**，判定结果按 `deliverable-verify` 的 `checks[].status` 四档
（fail / warn / skip / pass）回给 `defect_check.py`，全技能只有一套判定标准。

单位约定（全程 twips，1 inch = 1440 twips = 914400 EMU）:
    1 twip = 635 EMU；w:spacing/@w:line 的基准是 240（240 = 单倍行距）。

零第三方依赖（python-docx 由调用方传入已打开的 Document）。本模块永不抛栈：
任何内部异常都由 `checks_for` 收敛成该项 `skip` + 原因。
"""

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
V = "{urn:schemas-microsoft-com:vml}"

EMU_PER_TWIP = 635
PT_PER_TWIP = 20  # 1 pt = 20 twips
EMU_PER_PT = 12700
DEFAULT_LINE = 240  # w:line 的单倍行距基准
FALLBACK_SZ_HALFPT = 22  # docDefaults 缺 w:sz 时按 11pt
FALLBACK_PG = (11906, 16838)  # A4 纵向
FALLBACK_MARGIN = 1440  # 1 inch
MAX_PAGES = 2000
MAX_HITS = 12  # 单个 check 的 detail 最多列几条
# 单行自然高度 ≈ 1.2em（ascent + descent + 行间距）。只用于 realistic 口径；
# raw 口径不乘它——raw 是"任何渲染器至少要占"的下界，宁可小算也不能虚报 fail。
FONT_LINE_FACTOR = 1.2

# 分节符里会另起一页的类型（continuous 不换页；nextColumn 只换栏，按不换页处理）
SECT_NEW_PAGE = {"nextPage", "oddPage", "evenPage"}


def _i(v, default=0):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _attr(el, name, default=0):
    return _i(el.get(W + name), default) if el is not None else default


# ── 页几何 ───────────────────────────────────────────────────────────────────
def page_geometry(sect_pr):
    """正文区宽高（twips）。缺字段回落 A4 纵向 + 1 inch 边距，并标记用了默认值。

    正文区高按 Word 口径：上下页边距为准，页眉/页脚偏移大于页边距时以偏移为准
    （页眉压到正文区里的情况下，正文可用高度是更小的那个）。
    """
    fallback = sect_pr is None
    pg = sect_pr.find(W + "pgSz") if sect_pr is not None else None
    mar = sect_pr.find(W + "pgMar") if sect_pr is not None else None
    if pg is None or mar is None:
        fallback = True
    w = _attr(pg, "w", FALLBACK_PG[0]) or FALLBACK_PG[0]
    h = _attr(pg, "h", FALLBACK_PG[1]) or FALLBACK_PG[1]
    top = _attr(mar, "top", FALLBACK_MARGIN)
    bottom = _attr(mar, "bottom", FALLBACK_MARGIN)
    left = _attr(mar, "left", FALLBACK_MARGIN)
    right = _attr(mar, "right", FALLBACK_MARGIN)
    header = _attr(mar, "header", 0)
    footer = _attr(mar, "footer", 0)
    # 负边距（w:top 可为负，表示页眉浮在正文上）按 0 处理，否则正文区会被算大
    return {
        "w": max(0, w - max(0, left) - max(0, right)),
        "h": max(0, h - max(0, top, header) - max(0, bottom, footer)),
        "fallback": fallback,
    }


def _sect_type(sect_pr):
    t = sect_pr.find(W + "type") if sect_pr is not None else None
    return (t.get(W + "val") if t is not None else None) or "nextPage"


# ── body 遍历 ────────────────────────────────────────────────────────────────
def _iter_blocks(parent):
    """按文档顺序产出 ("p"|"tbl", element)；穿透 sdt（内容控件）容器。"""
    for ch in parent:
        tag = ch.tag
        if tag == W + "p":
            yield "p", ch
        elif tag == W + "tbl":
            yield "tbl", ch
        elif tag in (W + "sdt", W + "sdtContent"):
            for item in _iter_blocks(ch):
                yield item


# ── 段落原子（按文档顺序）────────────────────────────────────────────────────
def _drawing_info(el):
    """DrawingML 图片：取 wp:extent 的 cx/cy（EMU）与是否浮动（anchor）。"""
    holder = el.find(WP + "inline")
    floating = False
    if holder is None:
        holder = el.find(WP + "anchor")
        floating = holder is not None
    if holder is None:
        return {"name": "图片", "cx": 0, "cy": 0, "floating": False, "known": False}
    ext = holder.find(WP + "extent")
    name = ""
    for probe in (PIC + "cNvPr", WP + "docPr"):
        node = next((n for n in holder.iter(probe)), None)
        if node is not None:
            name = node.get("name") or name
            if name:
                break
    return {
        "name": name or "图片",
        "cx": _i(ext.get("cx")) if ext is not None else 0,
        "cy": _i(ext.get("cy")) if ext is not None else 0,
        "floating": floating,
        "known": ext is not None,
    }


def _vml_size(style):
    """VML style="width:123pt;height:45.6pt" → (cx, cy) EMU；只认 pt/in/cm。"""
    out = {}
    for item in (style or "").split(";"):
        if ":" not in item:
            continue
        k, v = item.split(":", 1)
        k, v = k.strip().lower(), v.strip().lower()
        if k not in ("width", "height"):
            continue
        for unit, factor in (("pt", EMU_PER_PT), ("in", 914400), ("cm", 360000), ("mm", 36000)):
            if v.endswith(unit):
                out[k] = _i(float(v[: -len(unit)]) * factor) if _isnum(v[: -len(unit)]) else 0
                break
    return out.get("width", 0), out.get("height", 0)


def _isnum(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _pict_info(el):
    """旧式 VML 图（w:pict / w:object）。拿不到尺寸时 known=False，不参与高度累加。"""
    shape = next((n for n in el.iter() if str(n.tag).endswith("}shape") or str(n.tag).endswith("}rect")), None)
    cx, cy = _vml_size(shape.get("style") if shape is not None else "")
    has_img = any(str(n.tag) == V + "imagedata" or str(n.tag).endswith("}imagedata") for n in el.iter())
    return {
        "name": (shape.get("alt") if shape is not None else "") or "VML 图片",
        "cx": cx,
        "cy": cy,
        "floating": False,
        "known": bool(cx and cy) and has_img,
        "vml": True,
    }


def _atoms(p_el, out):
    """递归收集段落原子：("text", 字符数) / ("img", info) / ("break", None) / ("hint", None)。

    跳过 w:pPr / w:rPr（格式，非内容）与 w:instrText（域代码，不可见）。
    超链接、smartTag、w:ins 等容器靠递归穿透，顺序即文档顺序。
    """
    for ch in p_el:
        tag = ch.tag
        if tag in (W + "pPr", W + "rPr", W + "instrText", W + "delText", W + "fldChar"):
            continue
        if tag == W + "br":
            if (ch.get(W + "type") or "") == "page":
                out.append(("break", None))
            continue
        if tag == W + "lastRenderedPageBreak":
            out.append(("hint", None))
            continue
        if tag == W + "t":
            out.append(("text", len(ch.text or "")))
            continue
        if tag == W + "tab":
            out.append(("text", 1))
            continue
        if tag == W + "drawing":
            out.append(("img", _drawing_info(ch)))
            continue
        if tag in (W + "pict", W + "object"):
            out.append(("img", _pict_info(ch)))
            continue
        _atoms(ch, out)
    return out


def _segments(p_el):
    """把段落按内部分页符切成若干"段片"。

    OOXML 语义（本 case 空白页的直接成因）：`w:br w:type="page"` 在段落**内部**，
    段落标记留在断点之后 —— 也就是新页顶部会残留这个段落的剩余部分（哪怕是空的），
    它占一行高度，把后面装不下的内容顶到再下一页，当前页就成了空白页。

    返回 [{"text","imgs","first","last"}]，至少一个元素（空段落 = 一个空段片）。
    """
    atoms = _atoms(p_el, [])
    segs, cur, hints = [], {"text": 0, "imgs": []}, 0
    for kind, val in atoms:
        if kind == "break":
            segs.append(cur)
            cur = {"text": 0, "imgs": []}
        elif kind == "text":
            cur["text"] += val
        elif kind == "img":
            cur["imgs"].append(val)
        elif kind == "hint":
            hints += 1
    segs.append(cur)
    for i, seg in enumerate(segs):
        seg["first"] = i == 0
        seg["last"] = i == len(segs) - 1
    return segs, hints


# ── 间距 / 行距 / 字号的继承链 ───────────────────────────────────────────────
class _Fmt:
    """段落格式解析：docDefaults → 样式（basedOn 链）→ 段落直接格式。

    **按属性粒度合并**，不是拿到一个 `w:spacing` 就整体覆盖：段落只写了 `w:before` 时，
    `w:line` / `w:lineRule` 仍继承上层。整体覆盖会把 docDefaults 里的行距倍数丢掉，
    而行距倍数恰好是"图占满一页 → 被顶到下一页 → 留下空白页"的成因之一。
    """

    def __init__(self, document):
        self.styles = {}
        self.default = {
            "before": 0,
            "after": 0,
            "line": DEFAULT_LINE,
            "rule": "auto",
            "sz": FALLBACK_SZ_HALFPT,
        }
        try:
            root = document.styles.element
        except Exception:
            root = None
        if root is None:
            return
        dd = root.find(W + "docDefaults")
        if dd is not None:
            self.default.update(self._spacing(dd.find(f"{W}pPrDefault/{W}pPr/{W}spacing")))
            sz = dd.find(f"{W}rPrDefault/{W}rPr/{W}sz")
            if sz is not None:
                self.default["sz"] = _i(sz.get(W + "val"), FALLBACK_SZ_HALFPT)
        for st in root.findall(W + "style"):
            sid = st.get(W + "styleId")
            if sid:
                self.styles[sid] = st

    @staticmethod
    def _spacing(el):
        """只回传**显式写了**的属性，缺的交给上层继承。"""
        out = {}
        if el is None:
            return out
        if el.get(W + "before") is not None:
            out["before"] = max(0, _i(el.get(W + "before")))
        if el.get(W + "after") is not None:
            out["after"] = max(0, _i(el.get(W + "after")))
        if el.get(W + "line") is not None:
            out["line"] = _i(el.get(W + "line"), DEFAULT_LINE)
        if el.get(W + "lineRule") is not None:
            out["rule"] = (el.get(W + "lineRule") or "auto").lower()
        return out

    def _chain(self, sid):
        """样式链：自身 → 基样式 → …（防环，最多 12 层）。"""
        out, seen = [], set()
        while sid and sid not in seen and len(out) < 12:
            st = self.styles.get(sid)
            if st is None:
                break
            out.append(st)
            seen.add(sid)
            based = st.find(W + "basedOn")
            sid = based.get(W + "val") if based is not None else None
        return out

    def para(self, p_el):
        cur = dict(self.default)
        p_pr = p_el.find(W + "pPr")
        sid = None
        if p_pr is not None:
            ps = p_pr.find(W + "pStyle")
            sid = ps.get(W + "val") if ps is not None else None
        for st in reversed(self._chain(sid)):  # 最上层基样式先应用，逐层向下覆盖
            cur.update(self._spacing(st.find(f"{W}pPr/{W}spacing")))
            sz = st.find(f"{W}rPr/{W}sz")
            if sz is not None:
                cur["sz"] = _i(sz.get(W + "val"), cur["sz"])
        if p_pr is not None:
            cur.update(self._spacing(p_pr.find(W + "spacing")))
        szs = [_i(n.get(W + "val"), 0) for n in p_el.iter(W + "sz")]  # 段内实际字号（含段落标记）
        szs = [s for s in szs if s > 0]
        if szs:
            cur["sz"] = max(szs)
        return cur


def seg_height(fmt_p, seg):
    """段片所需高度，返回 (raw, realistic, known)，单位 twips。

    - `raw` = **下界**：任何渲染器都至少要占的高度（不乘行距倍数、不乘字体度量系数）。
      只有连 raw 都放不下，才敢判 fail。
    - `realistic` = 按 lineRule 与行距倍数推演的实际高度，用于流式换页与 warn 判定。
    - `known` = realistic 是否可信：段内有文字时行数取决于字体度量与换行，未知 → False。

    段后间距（`w:after`）计入 raw/realistic（它是段间的真实占位），但**单段是否超过
    整页**的判定另用 `seg_solo_raw`：Word 在页底会吞掉尾随段后间距，把它算进"超页"
    会虚报 fail。
    """
    before = fmt_p["before"] if seg["first"] else 0
    after = fmt_p["after"] if seg["last"] else 0
    natural, known = _seg_natural(fmt_p, seg)
    if natural is None:  # 分页符之前的空段片：断点立即终止该行，前一页不占高度
        return 0, 0, True
    raw, real = _apply_line_rule(fmt_p, seg, natural)
    return int(before + raw + after), int(before + real + after), known


def seg_solo_raw(fmt_p, seg):
    """该段片**独占一页**时至少要占的高度（不含尾随段后间距，页底会被吞掉）。"""
    natural, _known = _seg_natural(fmt_p, seg)
    if natural is None:
        return 0
    raw, _real = _apply_line_rule(fmt_p, seg, natural)
    return int((fmt_p["before"] if seg["first"] else 0) + raw)


def _seg_natural(fmt_p, seg):
    """段片的自然高度（未套行距规则）。返回 (natural, known)；natural=None 表示不占行。"""
    if not seg["text"] and not seg["imgs"] and not seg["last"]:
        return None, True
    inline = [i for i in seg["imgs"] if not i.get("floating") and i.get("known")]
    cy = max([i["cy"] for i in inline], default=0)
    if cy:
        return cy / float(EMU_PER_TWIP), not seg["text"]
    # 无图：按字号折一行。有文字时行数未知（取决于字体度量与换行）→ known=False
    return fmt_p["sz"] / 2.0 * PT_PER_TWIP, not seg["text"]


def _apply_line_rule(fmt_p, seg, natural):
    """套 lineRule，返回 (raw, realistic)。图片行盒高度就是图高，不乘字体度量系数。"""
    has_img = any(not i.get("floating") and i.get("known") and i.get("cy") for i in seg["imgs"])
    factor = 1.0 if has_img else FONT_LINE_FACTOR
    rule = fmt_p["rule"] or "auto"
    line = fmt_p["line"] or DEFAULT_LINE
    if rule == "exact":  # 固定行高：内容被裁到 line，不会把段落顶到下一页
        return float(line), float(line)
    if rule == "atleast":
        return natural, max(natural * factor, line)
    return natural, natural * factor * (line / float(DEFAULT_LINE))  # auto = 倍数行距


# ── 页桶 ─────────────────────────────────────────────────────────────────────
def _new_page(index, geom, certain=True, approx=False, opened_by=""):
    return {
        "index": index,
        "geom": geom,
        "text": 0,
        "images": 0,
        "tables": 0,
        "used": 0,          # 已占高度（twips，realistic 口径）
        "used_raw": 0,      # 已占高度（raw 下界口径，用于"确定装不下"的判定）
        "img_names": [],
        # certain：该页**是否为空白页**这件事是否确定（仅当空白源于"行距倍数"这类
        # 推断时才置 False）。approx：该页**页码**是否只是推演值（上游有文本/表格等
        # 高度未知的内容时置 True）。两者必须分开 —— 页码不准不等于空白页判错。
        "certain": certain,
        "approx": approx,
        "reason": "",       # 关页原因：break / sect / pageBreakBefore / overflow / end
        # opened_by：本页由**什么打开**（即上一页的关页动作）。空白页的成因取决于它，而不是本页
        # 的 reason —— 实测：末段带 w:br type=page 造出的空白页，自身 reason 是 end，看不出成因。
        "opened_by": opened_by,
        "cause": "",        # 若因装不下而关页，记下是什么装不下（空白页的直接成因）
    }


def split_pages(document, fmt=None):
    """把 body 推演成页序列：结构切页（显式分页符 / 分节符 / pageBreakBefore）+ 流式换页。

    流式换页是关键：装不下就顺到下一页，**当前页因此只剩一个空行 → 空白页**。
    这正是"每图一页"产物出空白页的真实成因，只数分页符是数不出来的。

    空页上放不下也照放（渲染器只会裁切，不会无限顺延），并单独记为 overflow。

    返回 (pages, info)。info.page_count_hint 为 `w:lastRenderedPageBreak` 计数 —— 那是
    Word 存盘时的旧布局快照，可能过期，**只作参考，不当切点**（当切点会造出幻影空页）。
    """
    fmt = fmt or _Fmt(document)
    body = document.element.body
    final_sect = body.find(W + "sectPr")
    geom = page_geometry(final_sect)
    # 首节几何：body 里第一个中途 sectPr（在段落 pPr 内）描述的是**它之前**那些段落所在的节
    first_mid = next((n for n in body.iter(W + "sectPr") if n is not final_sect), None)
    if first_mid is not None:
        geom = page_geometry(first_mid)

    pages = [_new_page(1, geom)]
    hints, truncated, reliable = 0, False, True
    overflow = []

    def close(reason, cause=""):
        """关掉当前页并开新页；返回 False 表示已到页数上限。"""
        nonlocal truncated
        pages[-1]["reason"] = reason
        if cause:
            pages[-1]["cause"] = cause
        if len(pages) >= MAX_PAGES:
            truncated = True
            return False
        pages.append(_new_page(len(pages) + 1, geom, approx=not reliable, opened_by=reason))
        return True

    for kind, el in _iter_blocks(body):
        if truncated:
            break
        if kind == "tbl":
            pages[-1]["tables"] += 1
            pages[-1]["used"] += 0  # 表高需要行高与跨页规则，未建模
            reliable = False        # 之后的页码不再可信（表格高度未知）
            continue

        p_pr = el.find(W + "pPr")
        if p_pr is not None and p_pr.find(W + "pageBreakBefore") is not None:
            cur = pages[-1]
            if cur["text"] or cur["images"] or cur["tables"]:  # 空页上的分页前不额外造页
                if not close("pageBreakBefore"):
                    break

        segs, seg_hints = _segments(el)
        hints += seg_hints
        fmt_p = fmt.para(el)
        for si, seg in enumerate(segs):
            if si > 0 and not close("break"):  # 段内分页符：此前的内容留在当前页
                break
            raw, real, known = seg_height(fmt_p, seg)
            solo = seg_solo_raw(fmt_p, seg)
            page = pages[-1]
            area_h = page["geom"]["h"]
            label = (
                f"图「{seg['imgs'][0].get('name')}」"
                if seg["imgs"]
                else ("文本段落" if seg["text"] else "空段落")
            )
            # 装不下就顺到下一页。两套口径：raw 都放不下 = 任何渲染器都会换页（确定），
            # 只有 realistic 放不下 = 取决于行距倍数的实现（存疑，降级为 warn）。
            # 零高度段片（分页符前的空段片）不参与：它不占行，永远不会把内容顶走。
            if page["used"] > 0 and area_h > 0 and known and (raw or real):
                over_raw = page["used_raw"] + solo > area_h
                over_real = page["used"] + real > area_h
                if over_raw or over_real:
                    if not over_raw:
                        page["certain"] = False
                    avail = area_h - (page["used_raw"] if over_raw else page["used"])
                    if not close(
                        "overflow",
                        f"{label}需 {solo if over_raw else real} twips，该页仅剩 {avail} twips",
                    ):
                        break
                    page = pages[-1]
                    area_h = page["geom"]["h"]
            page["text"] += seg["text"]
            for img in seg["imgs"]:
                page["images"] += 1
                if img.get("name"):
                    page["img_names"].append(img["name"])
            page["used"] += real
            page["used_raw"] += raw
            if not known:
                reliable = False  # 文本行数未知 → 之后的页码只是推演值
            # 单段独占一页仍放不下：任何渲染器都只能裁切（确定性缺陷）
            if area_h > 0 and seg["imgs"] and solo > area_h:
                overflow.append(
                    {"page": page["index"], "label": label, "kind": "height",
                     "need": solo, "area": area_h}
                )
            for img in seg["imgs"]:  # 图宽超出正文区：会压进页边距/被页边裁切
                if img.get("floating") or not img.get("known") or not img.get("cx"):
                    continue  # 浮动图允许出血，不参与判定
                w_need = int(img["cx"] / float(EMU_PER_TWIP))
                if page["geom"]["w"] > 0 and w_need > page["geom"]["w"]:
                    overflow.append(
                        {"page": page["index"], "label": f"图「{img.get('name')}」",
                         "kind": "width", "need": w_need, "area": page["geom"]["w"]}
                    )

        sect = p_pr.find(W + "sectPr") if p_pr is not None else None
        if sect is not None and _sect_type(sect) in SECT_NEW_PAGE:
            if not close("sect"):
                break
            geom = page_geometry(sect)
            pages[-1]["geom"] = geom

    pages[-1]["reason"] = pages[-1]["reason"] or "end"
    info = {
        "page_count_static": len(pages),
        "page_count_hint": hints + 1 if hints else None,
        "truncated": truncated,
        "geom": geom,
        "overflow": overflow,
        "reliable": reliable,
    }
    return pages, info


def count_images(document):
    """body 里的图片数（DrawingML + 旧式 VML）。

    `defect_check.py` 与 `extractors/docx.py` 都用这一个口径 —— "文档有没有图"这件事
    在三处各写一遍必然漂移，而它直接决定 `non_empty` 判 fail 还是 pass。
    页眉页脚里的图（多为 logo）不计入正文内容。
    """
    n = 0
    try:
        body = document.element.body
    except Exception:
        return 0
    for el in body.iter():
        tag = str(el.tag)
        if tag == W + "drawing":
            if any(str(c.tag) == A + "blip" for c in el.iter()):
                n += 1
        elif tag in (W + "pict", W + "object"):
            if any(str(c.tag).endswith("}imagedata") for c in el.iter()):
                n += 1
    return n


# ── 对外入口：按 deliverable-verify 的 checks 四档回报 ───────────────────────
def _c(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


def _is_blank(page):
    return not (page["text"] or page["images"] or page["tables"])


# 硬分页符：段内 `w:br w:type="page"` 与 `w:pageBreakBefore`。二者都是作者写死的强制中断，
# OOXML 语义上必然起新页（`close("pageBreakBefore")` 只在当前页已有内容时触发，见 split_pages），
# 所以"新页上没落下任何内容"就是确定性的空白页，不依赖任何渲染器实现。
HARD_ORIGIN = {"break", "pageBreakBefore"}


def _evidence(page):
    """空白页的证据档：measured（实测几何）/ hard_break（硬分页符）/ structural（无支撑）。

    只有前两档敢判 fail：
    - measured：`cause` 由 `pgSz-pgMar` 与 `wp:extent` 相减得出，误差单向（只漏报不虚报）。
    - hard_break：判据是 OOXML 语义本身，与几何推演无关。实测 `successful_script.docx`
      末段 `<w:br w:type="page"/>` 造出的尾页空白属此类，人工在 Word 里已确认为真缺陷。

    `sect`（`nextPage` 分节符）打开的页一律进 structural：实测 `元代土司制度研究40年回顾与
    前瞻.docx`（CNKI 导出 / WPS 存盘）在两个相邻分节符之间只夹空段时，静态模型会造出**幻影页**
    （模型推 7 页、文档自报 `<Pages>6</Pages>`），人工确认该页并不存在。
    首页（`opened_by` 为空）同样进 structural —— "整篇无内容"由 `non_empty` 负责。
    """
    if not page["certain"]:
        return "structural"  # 是否为空取决于渲染器行距实现
    if page["cause"]:
        return "measured"
    if page["opened_by"] in HARD_ORIGIN:
        return "hard_break"
    return "structural"


def _dedup(hits):
    out, seen = [], set()
    for h in hits:
        key = (h.get("page"), h.get("label"), h.get("kind"), int(h.get("need") or 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def checks_for(path, document):
    """docx 页级判定，返回 (checks, info)。异常一律收敛成 skip —— 本模块永不抛栈。"""
    try:
        fmt = _Fmt(document)
        pages, info = split_pages(document, fmt)
    except Exception as e:
        return [_c("blank_page", "skip", f"docx 静态页模型异常，空白页未校验: {str(e)[:160]}")], {}

    geom = info["geom"]
    if geom["h"] <= 0 or geom["w"] <= 0:
        return [_c("blank_page", "skip", f"正文区尺寸异常（{geom['w']}x{geom['h']} twips），空白页未校验")], info

    checks = []
    blanks = [p for p in pages if _is_blank(p)]
    # 证据分档见 _evidence()：实测几何与硬分页符两档判 fail，纯结构推断（分节符/首页/行距）降 warn。
    hard = [p for p in blanks if _evidence(p) != "structural"]
    maybe = [p for p in blanks if _evidence(p) == "structural"]
    approx = (
        "（页码为静态推演值，可能与实际渲染相差 ±1）"
        if any(p["approx"] for p in blanks)
        else ""
    )

    if hard:
        detail = "空白页（无文本/无图片/无表格）: " + ", ".join(
            f"第{p['index']}页（{p['cause'] or '由硬分页符切出，该页无任何内容'}）"
            for p in hard[:MAX_HITS]
        )
        checks.append(_c("blank_page", "fail", detail + approx))
    elif maybe:
        checks.append(_c(
            "blank_page",
            "warn",
            "疑似空白页（无硬证据：成因为分节符切页或渲染器行距实现）: "
            + ", ".join(f"第{p['index']}页" for p in maybe[:MAX_HITS]) + approx,
        ))
    else:
        checks.append(_c(
            "blank_page",
            "pass",
            f"静态推演 {info['page_count_static']} 页，无空白页"
            + (f"；正文区 {geom['w']}x{geom['h']} twips" if geom.get("fallback") is False else ""),
        ))
    if hard and maybe:  # 两档都有：把存疑的也交代清楚，别让调用方以为只有那几页
        checks.append(_c(
            "blank_page_suspect",
            "warn",
            "另有疑似空白页（无硬证据）: " + ", ".join(f"第{p['index']}页" for p in maybe[:MAX_HITS]),
        ))

    over = _dedup(info["overflow"])
    if over:
        checks.append(_c(
            "page_overflow",
            "fail",
            "; ".join(
                f"第{h['page']}页 {h['label']}"
                + (f"高需 {h['need']} > 正文区高 {h['area']} twips" if h["kind"] == "height"
                   else f"宽需 {h['need']} > 正文区宽 {h['area']} twips")
                for h in over[:MAX_HITS]
            )
            + "（独占一页仍放不下，任何渲染器都只能裁切）",
        ))
    else:
        checks.append(_c("page_overflow", "pass", "无单段超出正文区的内容"))

    if info["truncated"]:
        checks.append(_c("page_model", "warn", f"页数超过 {MAX_PAGES}，其余未推演"))
    if geom.get("fallback"):
        checks.append(_c("page_model", "warn", "缺 pgSz/pgMar，正文区按 A4 纵向 + 1 inch 边距推演"))

    info["blank_pages"] = [p["index"] for p in hard]
    info["blank_suspect"] = [p["index"] for p in maybe]
    info["images"] = sum(p["images"] for p in pages)
    return checks, info


# ── 自检入口（开发期用；技能流程不调用本文件）────────────────────────────────
if __name__ == "__main__":
    import json
    import os
    import sys

    # 直接执行时 sys.path[0] 是本包目录，deps.py 在上一层；import deps 即把技能缓存里的
    # python-docx 挂进 sys.path（--doctor --install 装到的就是那里）。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import deps  # noqa: F401
    except Exception:
        pass

    import docx  # noqa: E402

    d = docx.Document(sys.argv[1])
    ps, meta = split_pages(d)
    cks, _ = checks_for(sys.argv[1], d)
    print(json.dumps(
        {
            "checks": cks,
            "geom": meta["geom"],
            "info": {k: v for k, v in meta.items() if k not in ("geom",)},
            "pages": [{k: v for k, v in p.items() if k != "geom"} for p in ps],
        },
        ensure_ascii=False,
        indent=2,
    ))
