"""Markdown 渲染管线：扩展、代码高亮、图片懒加载、短代码。"""
from __future__ import annotations

import re

import markdown as md

_IMG_RE = re.compile(r"<img\s([^>]*?)>", re.I)
_SRC_RE = re.compile(r'src="([^"]+)"', re.I)
_LAZY_ATTRS = 'loading="lazy" decoding="async"'

_PRE_RE = re.compile(r"(<pre[\s\S]*?</pre>)", re.I)
_SC_RE = re.compile(r"\{\{<\s*(\w+)([\s\S]*?)\s*>\}\}")


def build_markdown(toc_depth: str = "2-3") -> "md.Markdown":
    md_ = md.Markdown(
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "footnotes",
            "attr_list",
            "def_list",
            "sane_lists",
            "toc",
        ],
        extension_configs={
            "toc": {"toc_depth": toc_depth, "permalink": False},
            "codehilite": {"guess_lang": False, "css_class": "highlight"},
        },
    )
    setattr(md_, "toc_tokens", [])  # toc 扩展会写入该动态属性
    return md_


def render(md_: "md.Markdown", text: str, shortcodes: dict | None = None, lazy_images: bool = True) -> str:
    """渲染 Markdown 文本为 HTML，并做图片懒加载、短代码展开。"""
    html = md_.reset().convert(text)
    if shortcodes:
        html = process_shortcodes(html, shortcodes)
    if lazy_images:
        html = _lazy_images(html)
    return html


def toc_from(md_: "md.Markdown") -> list[dict]:
    """从 toc 扩展取目录树。"""
    return list(getattr(md_, "toc_tokens", []) or [])


def toc_html(tokens: list[dict]) -> str:
    """把 toc_tokens 渲染为 <ul> 目录树。"""
    if not tokens:
        return ""
    parts = ["<ul>"]
    prev = 1
    for t in tokens:
        lvl = int(t["level"])
        if lvl > prev:
            parts.append("<ul>" * (lvl - prev))
        elif lvl < prev:
            parts.append("</ul>" * (prev - lvl))
        parts.append(f'<li><a href="#{t["id"]}">{t["name"]}</a></li>')
        prev = lvl
    parts.append("</ul>" * prev)
    return "".join(parts)


def _lazy_images(html: str) -> str:
    def repl(m):
        tag = m.group(1)
        m_src = _SRC_RE.search(tag)
        if not m_src:
            return m.group(0)
        add = _LAZY_ATTRS
        if "loading=" in tag:
            add = 'decoding="async"'
        if tag.rstrip().endswith("/"):
            tag = tag.rstrip()[:-1]  # 处理自闭合
        return f"<img {tag} {add}>"

    return _IMG_RE.sub(repl, html)


def process_shortcodes(html: str, shortcodes: dict) -> str:
    """展开 {{< name arg1 arg2 ... >}} 短代码；<pre> 代码块内不处理。
    Python-Markdown 会把段落里的 {{< 转义成 {{&lt;，这里两种形态都支持。"""
    parts = _PRE_RE.split(html)
    # 先归一化转义形态，避免 Markdown 转义干扰匹配
    norm = html
    if "{{&lt;" in norm:
        norm = norm.replace("{{&lt;", "{{<").replace("&gt;}}", ">}}")
    parts = _PRE_RE.split(norm)

    def repl(m):
        name, raw = m.group(1), m.group(2).strip()
        handler = shortcodes.get(name)
        if not handler:
            return m.group(0)
        try:
            out_html = handler([a for a in raw.split()] if raw else [])
            return out_html if out_html is not None else m.group(0)
        except Exception:  # 短代码出错不阻断整站
            return m.group(0)

    out: list[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:  # <pre> 块原样保留
            out.append(part)
            continue
        out.append(_SC_RE.sub(repl, part))
    return "".join(out)