#!/usr/bin/env python3
"""html 渲染取证 + （可选，默认关闭）多模态视觉排版审核。

用法:
    python3 visual_check.py <file> [--dpi 120] [--max-pages 10] [--budget-s 240] [--batch 3]

**默认行为（视觉审核关闭）**：本技能对外不承诺视觉排版审核。
    - office/pdf：直接返回 {"disabled": ...}，不渲染、不截图、不送审。
    - html：走无头浏览器渲染，只产出运行时探针 probe 与渲染后文本 rendered_text，
      不截图、不送审；这两项是 html 内容核对与确定性缺陷判定的证据来源。
    置 DUMATE_DELIVERABLE_VISUAL_CHECK=1 才开启多模态排版审核（逐页送审）。

向 stdout 输出 JSON：
    {
      "pages": [ {"page": 3, "image": "<图片路径>",
                  "issues": [{"severity": "blocker|warning", "problem": "..."}]}
                 | {"page": 5, "image": "...", "error": "..."} ],
      "page_count": N,          # 渲染出的总页数（关闭态为 0，未渲染或未截图）
      "checked_pages": M,       # 实际完成审核的页数（关闭态为 0）
      "sampled": true|false,    # 页数超过 max-pages 时做了均匀抽样（含首末页）
      "skipped_pages": [..],    # 因预算耗尽未送审的页码（原始页码）
      "probe": {...} | null,    # html 专有：运行时探针结果（render 阶段产出，见 SKILL.md）
      "rendered_text": "<文件路径>" | null,  # html 专有：**渲染后 innerText 的落盘文件路径**
                                             # （不是文本本身；内容上限 200k 字符，超出截断）
      "error": null | str,      # 整体失败（如渲染失败）时非空
      "disabled": str           # 存在该字段 = 视觉审核被开关关闭（主动跳过，非环境失败）
    }

审核结论使用规则（供校验子代理解析）：
    - 某页 issues 里存在 severity=blocker → 该产物存在排版级缺陷
    - 仅 warning → 不阻断交付的排版瑕疵
    - 某页带 error / skipped_pages 非空 / sampled=true 未覆盖的页 / 有 disabled 字段
      → 视为"视觉排版未覆盖"，不作为 fail 依据也不作为通过依据

时间预算与断点续跑（核心设计，防 bash 超时把已完成的工作全部丢弃）：
    - 预算 --budget-s **覆盖渲染与送审两个阶段**：html deck 逐页截图是串行的，光渲染就能
      把调用方 timeout 耗光；到点即停止截图/停止派发新批，收尾在飞请求后输出部分结果。
    - 多模态单页延迟实测 12~67s 且随网关排队增长。
    - 每页成功即写入 <outdir>/visual_results.json（write-through）；**重跑同一命令自动
      续跑**：产物未变时跳过已成功页、只补失败/未审页，且图片齐全时跳过重新渲染。
      产物被修复（size/mtime 变化）后缓存自动作废、全量重审。
    - 调用方（bash）的 timeout 必须大于 budget-s（建议 budget 240s / bash timeout 300000ms），
      保证退出权在脚本手里而不是被 bash SIGKILL（即使被杀，已成功页也在缓存里，重跑不丢）。

请求走千帆网关 chat/completions 多模态接口：沙箱内经调度器代理
（$DUMATE_SCHEDULER_URL/api/qianfanproxy）转发、鉴权由代理注入，无需本地密钥；
非沙箱环境直连原始 URL（无本地鉴权注入，通常会失败并按"未覆盖"处理）。渲染复用同目录
browser.py（office/pdf 走 soffice+pdftoppm，html 走 dumate-browser-cli 无头浏览器截图，
产物落工作目录 .tmp/）。本脚本永不抛栈，一切失败收敛进 JSON。
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from urllib.parse import urlparse

from browser import outdir_for, run as render_file  # 复用渲染管线（.tmp 落点、清残留、类型路由）

CHAT_URL = "https://qianfan.baidubce.com/v1/chat/completions"
# 多模态模型 ID，可用环境变量覆盖
MODEL = os.environ.get("ROUTING_MULTIMODAL_MODEL_ID", "qwen3.5-397b-a17b")
RETRIES = 2
TIMEOUT_S = 120          # 单请求超时基线（批量时按页数加成，见 _request_timeout；实际取 min(超时, 剩余预算)）
TIMEOUT_EXTRA_PER_PAGE_S = 30  # 批内每多一页，请求超时加成
CONCURRENCY = 3
DEFAULT_MAX_PAGES = 10
DEFAULT_BUDGET_S = 240
DEFAULT_BATCH = 3        # 每次请求送审的页数（批内页码连续，天然自带跨页上下文）
MIN_DISPATCH_S = 15      # 剩余预算低于此值不再派发新批
MAX_IMAGE_EDGE = 1280    # 送审前长边压缩上限（降低上传与推理耗时）
JPEG_QUALITY = 80

# 多模态视觉排版审核开关：**默认关闭**，本技能对外不承诺视觉排版审核能力。
# 置 DUMATE_DELIVERABLE_VISUAL_CHECK=1（或 true/on/yes）才开启送审；关闭时：
#   - office/pdf 直接返回 disabled，不渲染、不截图；
#   - html 仍走浏览器渲染，但只取运行时探针 probe 与渲染后文本 rendered_text（不截图），
#     供调用方做内容核对与确定性缺陷判定。
DEFAULT_VISUAL_AUDIT = False


def _visual_audit_enabled():
    v = os.environ.get("DUMATE_DELIVERABLE_VISUAL_CHECK")
    if v is None:
        return DEFAULT_VISUAL_AUDIT
    return v.strip().lower() not in ("0", "false", "off", "no", "")


# 批量审核 prompt 模板。{k}=本批张数，{page_list}=各图对应的原始页码列表，
# {total}=文档总页数，{doc_kind}/{pagination_note}=按产物类型注入的分页语义。
# JSON 花括号在模板中原样出现，用 %s 风格拼接避免 format 转义问题。
VISUAL_PROMPT_HEADER = (
    "你是文档排版审核专家。以下 {k} 张图片来自同一份交付{doc_kind}，"
    "按顺序分别是{page_list}（文档共 {total} 页）。请逐张检查每一页的排版问题：\n"
)

VISUAL_PROMPT_BODY = """
- 元素重叠（文字穿过形状/图片、元素堆叠遮挡）
- 文字在页面中部被截断、或明显的内容丢失（如句子/段落在页面中间戛然而止）
- 内容超出画布或页面范围
- 对齐不一致、间距失衡（某处大片空白而另一处过度拥挤）、边距不足
- 低对比度文字（如浅色文字在浅色背景上，难以辨认）
- 残留占位符（xxx、lorem/ipsum、TODO、[insert...]、明显的模板默认文字）
- 表格问题：列宽不足导致内容截断（显示为###）、单元格内容溢出；表格跨页续排本身是正常排版，仅当表头缺失或行内容明显不完整时才报告
- 图片或资源加载失败造成的空白/裂图
- 插入图片尺寸不当、形状不合适、拉伸变形、文本与图片间距不当

字体与字号：
- 字号过小以致难以阅读（正文相对页面明显偏小、注释/页脚小到几乎看不清）
- 字号与排版不匹配：标题不够突出（与正文字号拉不开层次）、或标题过大挤占内容、文字撑满容器无留白
- 字号层级混乱：同级内容字号不一致（多个并列标题大小不一、表格同列字号跳变）
- 字体不统一：同一文档混用多种不协调字体、中英文字体搭配突兀
- 行距/字间距过密导致拥挤或过疏导致松散、文字与容器边界几乎贴合无内边距

美观度（仅在确有可见问题时报，且多为 warning）：
- 配色不协调：颜色过多过杂、饱和度过高刺眼、色彩搭配冲突、缺乏统一主色调
- 视觉层次弱：重点内容不突出、主次不分、整页平铺缺乏节奏
- 整体不精致：元素风格不统一（圆角/直角混用、阴影浓淡不一）、留白不均、观感廉价粗糙

分页语义（重要，避免误报）：
- {pagination_note}
- 页面顶部/底部边缘的文字或元素被裁切属于分页/分片的正常现象，不要报告；只报告页面中部的截断与内容丢失。同批相邻页可互为参照：底部疑似截断时，先看下一页开头是否延续。

严重度定义：
- blocker：导致内容不可读或明显错误——内容丢失、元素重叠到无法辨认、占位符残留、资源加载失败留白、插入图片缩放变形、字号过小到无法阅读
- warning：不影响可读性的不美观——间距略挤、轻微不齐、对比度偏低但仍可读、字号层级/字体不统一、配色不协调、视觉层次弱、观感不够精致

要求：
1. 只报告确实可见的问题，不要臆测；对轻微、观众不会注意的瑕疵不要报 blocker。美观度问题若只是风格偏好、不构成明显缺陷，不要硬报。
2. problem 描述里带上问题在页面中的大致位置（如"右下角"、"标题区"、"表格第 3 列"）。
3. 只输出一个 JSON 对象，不要任何其他文字、不要 markdown 代码围栏，按页给出结果（页码用上面给出的原始页码；没有问题的页 issues 为空数组，不要遗漏任何页）：
{"pages": [{"page": 3, "issues": [{"severity": "blocker", "problem": "..."}]}]}"""

PAGINATION_NOTE_HTML = (
    "这些图片是同一个连续网页按 1280×900 视口自上而下切出的分片，"
    "相邻分片在切缝处内容连续——切缝两侧各自看到内容的一半是分片伪影，不是产物缺陷"
)
PAGINATION_NOTE_PAGED = "这些图片是分页文档的各页，段落/表格延续到下一页（跨页续排）是正常排版"


def build_prompt(pnos, total, is_html):
    page_list = "、".join(f"第 {p} 页" for p in pnos)
    header = VISUAL_PROMPT_HEADER.format(
        k=len(pnos),
        page_list=page_list,
        total=total,
        doc_kind="网页（视口分片）" if is_html else "分页文档",
    )
    body = VISUAL_PROMPT_BODY.replace(
        "{pagination_note}", PAGINATION_NOTE_HTML if is_html else PAGINATION_NOTE_PAGED
    )
    return header + body


def resolve_outbound(original_url):
    """沙箱内改走调度器代理（鉴权由代理注入），并附透传 headers；非沙箱环境返回原始 URL。"""
    passthrough = {}
    for name in ("X-Dumate-Device-Id", "X-Dumate-Account-Id", "User-Agent"):
        v = os.environ.get(name)
        if v:
            passthrough[name] = v
    session_id = os.environ.get("DUMATE_SESSION_ID")
    scheduler = os.environ.get("DUMATE_SCHEDULER_URL")
    if not session_id or not scheduler:
        return original_url, passthrough
    p = urlparse(original_url)
    proxy_url = f"{scheduler}/api/qianfanproxy{p.path}" + (f"?{p.query}" if p.query else "")
    headers = dict(passthrough)
    headers["Host"] = p.netloc
    headers["X-Dumate-Session-Id"] = session_id
    headers["X-Dumate-Request-Id"] = os.environ.get("DUMATE_REQUEST_ID", "")
    return proxy_url, headers


def _prepare_image(path):
    """读图并压缩（PIL 可用时长边压到 MAX_IMAGE_EDGE、重编码 JPEG），减小 payload。
    PIL 不可用或处理失败时回退原始字节。返回 (bytes, mime)。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = MAX_IMAGE_EDGE / max(w, h)
            if scale < 1:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=JPEG_QUALITY)
            return buf.getvalue(), "image/jpeg"
    except Exception:
        data = Path(path).read_bytes()
        mime = "image/png" if str(path).lower().endswith(".png") else "image/jpeg"
        return data, mime


def _valid_issues(raw):
    """校验并规整单页 issues 列表；非法输入返回 None。"""
    if not isinstance(raw, list):
        return None
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        sev = it.get("severity")
        prob = it.get("problem")
        if sev in ("blocker", "warning") and isinstance(prob, str) and prob:
            out.append({"severity": sev, "problem": prob})
    return out


def _parse_batch_issues(content, expected_pnos):
    """从模型回复中提取按页 issues；返回 {pno: [issues]}（只含 expected 中出现的页），
    解析失败返回 None（调用方记 error）。"""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except Exception:
        return None
    pages = obj.get("pages")
    # 容错：模型偶发退化成单页格式 {"issues": [...]}，且本批恰好只有一页 → 按该页收下
    if pages is None and len(expected_pnos) == 1:
        issues = _valid_issues(obj.get("issues"))
        return None if issues is None else {expected_pnos[0]: issues}
    if not isinstance(pages, list):
        return None
    expected = set(expected_pnos)
    out = {}
    for entry in pages:
        if not isinstance(entry, dict):
            continue
        pno = entry.get("page")
        issues = _valid_issues(entry.get("issues"))
        if isinstance(pno, int) and pno in expected and issues is not None:
            out[pno] = issues
    return out or None


def _request_timeout(batch_size):
    return TIMEOUT_S + TIMEOUT_EXTRA_PER_PAGE_S * max(0, batch_size - 1)


def check_batch(batch, total_pages, is_html, deadline):
    """一批页送审：压缩 → base64 → 单次 chat/completions（多图）→ 按页解析 issues。
    batch 为 [(原始页码, 图片路径), ...]，批内页码连续。受 deadline 约束。
    返回 {pno: {"issues":[...]} | {"error": "..."}}——模型漏答的页记 error，可续跑补审。"""
    pnos = [pno for pno, _ in batch]
    remaining = deadline - time.monotonic()
    if remaining < 5:
        return {pno: {"error": "budget exhausted before dispatch"} for pno in pnos}

    content_parts = []
    for pno, img in batch:
        try:
            data, mime = _prepare_image(img)
        except Exception as e:
            return {p: {"error": f"read image failed: {e}"} for p in pnos}
        content_parts.append({"type": "text", "text": f"第 {pno} 页："})
        content_parts.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}
        )
    content_parts.append({"type": "text", "text": build_prompt(pnos, total_pages, is_html)})
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": content_parts}]}).encode()

    url, extra = resolve_outbound(CHAT_URL)
    headers = {"Content-Type": "application/json", **extra}
    last_err = None
    for attempt in range(RETRIES):
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            started = time.monotonic()
            with urllib.request.urlopen(req, timeout=min(_request_timeout(len(batch)), remaining)) as resp:
                payload = json.loads(resp.read().decode())
            elapsed = time.monotonic() - started
            content = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if content:
                per_page = _parse_batch_issues(content, pnos)
                if per_page is not None:
                    n_issues = sum(len(v) for v in per_page.values())
                    print(
                        f"[visual_check] pages {pnos} done in {elapsed:.1f}s ({n_issues} issues, {len(per_page)}/{len(pnos)} pages answered)",
                        file=sys.stderr,
                    )
                    # 模型漏答的页记 error（不进缓存），续跑时重新送审
                    return {
                        pno: ({"issues": per_page[pno]} if pno in per_page else {"error": "missing in model reply"})
                        for pno in pnos
                    }
                last_err = "unparseable model reply"
            else:
                last_err = "empty model reply"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if 400 <= e.code < 500:  # 4xx 逻辑错误不重试
                break
        except Exception as e:
            last_err = str(e)
        # 重试前短退避（预算余量充足时才等，避免烧预算）
        if attempt < RETRIES - 1 and deadline - time.monotonic() > 10:
            time.sleep(2)
    return {pno: {"error": last_err or "unknown error"} for pno in pnos}


def _sample_pages(images, max_pages):
    """页数超上限时均匀抽样（必含首末页）。返回 ([(原始页码, 图片路径)...], 是否抽样)。"""
    n = len(images)
    if n <= max_pages:
        return [(i + 1, img) for i, img in enumerate(images)], False
    if max_pages <= 1:
        return [(1, images[0])], True
    idxs = sorted({round(i * (n - 1) / (max_pages - 1)) for i in range(max_pages)})
    return [(i + 1, images[i]) for i in idxs], True


def _artifact_key(path):
    """产物指纹（size + mtime_ns）：修复重写后指纹变化 → 缓存作废、全量重审。"""
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def _load_cache(cache_path, key):
    """读断点缓存；产物指纹不匹配或损坏时视为无缓存。"""
    try:
        obj = json.loads(Path(cache_path).read_text())
        if obj.get("artifact_key") == key and isinstance(obj.get("results"), dict):
            return obj
    except Exception:
        pass
    return None


def _save_cache(cache_path, key, images, results):
    """write-through：仅持久化成功页。写失败不影响本次输出。"""
    try:
        ok = {k: v for k, v in results.items() if isinstance(v, dict) and "issues" in v}
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(
            json.dumps({"artifact_key": key, "images": images, "results": ok}, ensure_ascii=False)
        )
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Visual layout check via multimodal model.")
    ap.add_argument("file")
    ap.add_argument("--dpi", type=int, default=120)
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--budget-s", type=int, default=DEFAULT_BUDGET_S)
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="每次请求送审的页数（批内页码连续）")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(json.dumps({"pages": [], "page_count": 0, "checked_pages": 0, "sampled": False, "skipped_pages": [], "error": "file not found"}))
        return

    # 预算从这里起算，**覆盖渲染与送审两个阶段**：渲染（尤其 html deck 逐页串行截图）
    # 本身就能把调用方的 bash timeout 耗光，若预算只管送审，超时会被 SIGKILL 且缓存未写、整轮白跑。
    deadline = time.monotonic() + max(args.budget_s, 30)

    # 视觉审核关闭（默认）：不做多模态排版审核。office/pdf 无需渲染 → 直接返回；
    # html 仍渲染以产出 rendered_text/probe 供内容核对，但不截图（--no-shots）。
    # disabled 与 error 严格区分：这是主动跳过，不是环境失败/渲染失败。
    audit_on = _visual_audit_enabled()
    is_html = Path(args.file).suffix.lower() == ".html"
    if not audit_on and not is_html:
        print(json.dumps({
            "pages": [], "page_count": 0, "checked_pages": 0,
            "sampled": False, "skipped_pages": [], "probe": None,
            "rendered_text": None, "error": None,
            "disabled": "visual audit disabled by gate",
        }, ensure_ascii=False))
        return

    outdir = outdir_for(args.file)
    key = _artifact_key(args.file)
    cache_path = str(Path(outdir) / "visual_results.json")
    cache = _load_cache(cache_path, key)

    # 视觉审核关闭（此时必为 html）：只跑探针 + 文本导出，不截图。
    if not audit_on:
        try:
            rendered = render_file(args.file, outdir, args.dpi, shots=False, deadline=deadline)
        except Exception as e:
            rendered = {"images": [], "error": str(e)}
        if rendered.get("error"):
            print(json.dumps({
                "pages": [], "page_count": 0, "checked_pages": 0, "sampled": False,
                "skipped_pages": [], "probe": None, "rendered_text": None,
                "error": f"render failed: {rendered['error']}",
                "disabled": "visual audit disabled by gate",
            }, ensure_ascii=False))
            return
        _probe = None
        _pp = Path(outdir) / "probe.json"
        if _pp.exists():
            try:
                _probe = json.loads(_pp.read_text(encoding="utf-8"))
            except Exception:
                _probe = {"error": "probe.json unreadable"}
        _tp = Path(outdir) / "rendered_text.txt"
        print(json.dumps({
            "pages": [], "page_count": 0, "checked_pages": 0,
            "sampled": False, "skipped_pages": [], "probe": _probe,
            "rendered_text": str(_tp) if _tp.exists() else None, "error": None,
            "disabled": "visual audit disabled by gate",
        }, ensure_ascii=False))
        return

    # 断点续跑：产物未变且图片齐全 → 跳过重新渲染
    images = None
    if cache:
        cached_images = cache.get("images") or []
        if cached_images and all(os.path.exists(p) for p in cached_images):
            images = cached_images
    if images is None:
        try:
            rendered = render_file(args.file, outdir, args.dpi, deadline=deadline)
        except Exception as e:
            rendered = {"images": [], "error": str(e)}
        if rendered.get("error"):
            print(json.dumps({"pages": [], "page_count": 0, "checked_pages": 0, "sampled": False, "skipped_pages": [], "error": f"render failed: {rendered['error']}"}, ensure_ascii=False))
            return
        images = rendered.get("images") or []

    # 仅复用成功页；error/未审页留待本轮补跑
    results = {}
    if cache:
        results = {k: v for k, v in cache["results"].items() if isinstance(v, dict) and "issues" in v}
        if results:
            print(f"[visual_check] resume: {len(results)} page(s) from cache", file=sys.stderr)

    targets, sampled = _sample_pages(images, max(args.max_pages, 0))
    todo = [(pno, img) for pno, img in targets if str(pno) not in results]

    # 按批分组：批内页码取自 todo 的自然顺序（升序），同批相邻页可互为跨页参照
    batch_size = max(args.batch, 1)
    batches = [todo[i : i + batch_size] for i in range(0, len(todo), batch_size)]
    total_pages = len(images)

    # 渲染已经花掉一部分预算；剩余预算用于送审，到点停止派发、收尾在飞请求后立即返回部分结果。
    queue = list(batches)
    skipped = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {}

        def dispatch():
            while queue and len(futures) < CONCURRENCY:
                if deadline - time.monotonic() < MIN_DISPATCH_S:
                    break
                batch = queue.pop(0)
                futures[pool.submit(check_batch, batch, total_pages, is_html, deadline)] = batch

        dispatch()
        while futures:
            done, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
            for fut in done:
                batch = futures.pop(fut)
                try:
                    per_page = fut.result()
                except Exception as e:  # check_batch 不应抛，最后一道兜底
                    per_page = {pno: {"error": str(e)} for pno, _ in batch}
                got_success = False
                for pno, _ in batch:
                    res = per_page.get(pno) or {"error": "missing result"}
                    results[str(pno)] = res
                    if "issues" in res:
                        got_success = True
                if got_success:
                    _save_cache(cache_path, key, images, results)
            dispatch()
        skipped = [pno for batch in queue for pno, _ in batch]

    pages = []
    img_of = dict(targets)
    for pno_str, res in results.items():
        pno = int(pno_str)
        entry = {"page": pno, "image": img_of.get(pno, "")}
        entry.update(res)
        pages.append(entry)
    pages.sort(key=lambda p: p["page"])
    checked = sum(1 for p in pages if "issues" in p)

    # html 专有：透传 render 阶段的运行时探针与渲染后文本（不存在即 null，如 office/pdf）
    probe = None
    probe_path = Path(outdir) / "probe.json"
    if probe_path.exists():
        try:
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
        except Exception:
            probe = {"error": "probe.json unreadable"}
    text_path = Path(outdir) / "rendered_text.txt"
    rendered_text = str(text_path) if text_path.exists() else None

    print(
        json.dumps(
            {
                "pages": pages,
                "page_count": len(images),
                "checked_pages": checked,
                "sampled": sampled,
                "skipped_pages": skipped,
                "probe": probe,
                "rendered_text": rendered_text,
                "error": None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
