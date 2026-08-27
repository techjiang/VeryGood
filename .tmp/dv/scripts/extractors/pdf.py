"""pdf 抽取：逐页文本、书签大纲、注解链接（/Annots → /A /URI）。不做 OCR。"""
from .common import merge_links, text_urls


def _reader(path):
    try:
        from pypdf import PdfReader

        return PdfReader(path), None
    except Exception:
        pass
    try:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader(path), None
    except Exception as e:
        return None, f"pypdf/PyPDF2 不可用，pdf 正文与链接未抽取（pip install pypdf）: {e}"


def _annot_links(page, pno):
    out = []
    try:
        annots = page.get("/Annots")
        annots = annots.get_object() if hasattr(annots, "get_object") else annots
        for a in annots or []:
            a = a.get_object() if hasattr(a, "get_object") else a
            act = a.get("/A")
            act = act.get_object() if hasattr(act, "get_object") else act
            uri = (act or {}).get("/URI")
            uri = str(uri) if uri is not None else ""
            if uri.lower().startswith(("http://", "https://")):
                out.append({"url": uri, "where": f"第{pno}页", "source": "annot"})
    except Exception:
        pass
    return out


def extract(path):
    reader, err = _reader(path)
    if reader is None:
        return {"units": [], "links": [], "outline": [], "meta": {}, "notes": [err]}
    try:
        pages = list(reader.pages)
    except Exception as e:
        return {"units": [], "links": [], "outline": [], "meta": {}, "notes": [f"pdf 解析失败: {e}"]}

    units, links, notes, no_text = [], [], [], []
    for i, pg in enumerate(pages, 1):
        try:
            t = (pg.extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            units.append({"anchor": f"pdf:p{i}", "text": t})
            links += text_urls(t, f"第{i}页")
        else:
            no_text.append(i)
        links += _annot_links(pg, i)
    if no_text:
        notes.append("无可提取文本的页（整页图片/矢量输出）: " + ", ".join(map(str, no_text[:20])))

    outline = []
    try:
        for item in reader.outline or []:
            if isinstance(item, list):
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if title:
                outline.append({"anchor": "pdf:outline", "label": title[:80], "level": 1})
    except Exception:
        pass

    return {
        "units": units,
        "links": merge_links(links),
        "outline": outline,
        "meta": {"page_count": len(pages), "pages_without_text": no_text},
        "notes": notes,
    }
