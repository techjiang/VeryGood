"""抽取器共用工具：URL 抽取与 OOXML 超链接关系解析。

设计约定（所有 extractors/<type>.py 都遵守）：
    extract(path) -> {
      "units":   [ {"anchor": "docx:p12", "text": "..."} ],   # 有序，正文载体
      "links":   [ {"url": ..., "where": ..., "source": "text|rel|annot"} ],
      "outline": [ {"anchor": ..., "label": ..., "level": 1} ],
      "meta":    {...},        # 类型专有量化基线（段数/页数/sheet 等）
      "notes":   [ "..." ],    # 降级与未覆盖说明，必须如实回传
    }
模块名与三方库/标准库同名（docx/html/pdf）无碍：py3 只有绝对导入，
`extractors/docx.py` 里 `import docx` 命中 site-packages，不会自指。
"""
import re
import zipfile

# 正文里的裸链接。右侧排除中英标点与括号，避免把句末标点吃进 URL。
URL_RE = re.compile(r'https?://[^\s<>"\'\)\]}，。；、！？】）]+')

_REL_RE = re.compile(r"<Relationship\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def text_urls(text, where):
    """从一段文本里抽裸链接。"""
    out = []
    for m in URL_RE.finditer(text or ""):
        out.append({"url": m.group(0).rstrip(".,;:"), "where": where, "source": "text"})
    return out


def _rels_label(name):
    """把 rels 文件路径翻成人能看懂的位置标签。"""
    if "slide" in name:
        m = re.search(r"slide(\d+)\.xml\.rels$", name)
        return f"第{m.group(1)}页" if m else "slide"
    if "sheet" in name:
        m = re.search(r"sheet(\d+)\.xml\.rels$", name)
        return f"sheet{m.group(1)}" if m else "sheet"
    if "document.xml.rels" in name:
        return "正文"
    if "footnotes" in name:
        return "脚注"
    if "header" in name or "footer" in name:
        return "页眉页脚"
    return name.rsplit("/", 1)[-1].replace(".xml.rels", "")


def ooxml_external_links(path):
    """扫 OOXML 包内所有 _rels，取 TargetMode="External" 的 hyperlink 目标。

    这是「链接文字是中文、URL 只存在于关系表」这类超链接的唯一来源——纯文本
    正则抽不到，是漏检最多的一类。解析失败不抛栈，返回已拿到的部分。
    """
    out = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.endswith(".rels"):
                    continue
                try:
                    xml = zf.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
                for tag in _REL_RE.findall(xml):
                    attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
                    if "hyperlink" not in (attrs.get("type") or "").lower():
                        continue
                    if (attrs.get("targetmode") or "").lower() != "external":
                        continue
                    target = attrs.get("target") or ""
                    if target.lower().startswith(("http://", "https://")):
                        out.append({"url": target, "where": _rels_label(name), "source": "rel"})
    except Exception:
        pass
    return out


def merge_links(*groups):
    """按 URL 合并：出现位置累加，source 取并集（rel 优先展示）。

    `where` 既接受字符串（抽取器原始输出）也接受字符串列表（本函数自身的输出），
    因此可对已合并的结果再次合并——link_probe 跨多个产物做全局去重时依赖这一点。
    """
    merged = {}
    for g in groups:
        for it in g or []:
            url = it.get("url")
            if not url:
                continue
            cur = merged.setdefault(url, {"url": url, "where": [], "source": set()})
            w = it.get("where")
            for one in (w if isinstance(w, (list, tuple)) else [w]):
                if one and one not in cur["where"]:
                    cur["where"].append(one)
            cur["source"].add(it.get("source") or "text")
    out = []
    for url, v in merged.items():
        src = "rel" if "rel" in v["source"] else ("annot" if "annot" in v["source"] else "text")
        out.append({"url": url, "where": v["where"][:10], "source": src})
    return out
