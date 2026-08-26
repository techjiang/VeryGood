"""Markdown 渲染管线：扩展、代码高亮、语言标签、图片懒加载、短代码。"""
from __future__ import annotations

import html as _html
import re

import markdown as md

_IMG_RE = re.compile(r"<img\s([^>]*?)>", re.I)
_SRC_RE = re.compile(r'src="([^"]+)"', re.I)
_LAZY_ATTRS = 'loading="lazy" decoding="async"'

_PRE_RE = re.compile(r"(<pre[\s\S]*?</pre>)", re.I)
_SC_RE = re.compile(r"\{\{<\s*(\w+)([\s\S]*?)\s*>\}\}")

# ---- 代码块语言标签（v1.4.0）----
# fence 信息行（```python / ```py title=xxx）取首词作为语言标识；
# 兼容 blockquote 内 fence（行首可带 > 前缀）。
_FENCE_RE = re.compile(r"^(?:\s*>\s*)?```([^\n`]*)", re.M)
_HILITE_RE = re.compile(r'<div class="highlight">')

# 常见别名归一 + 显示名美化（fence 原文小写后查表，查不到则原样展示）
_LANG_ALIAS = {
    "js": "javascript", "ts": "typescript", "py": "python",
    "sh": "bash", "shell": "bash", "zsh": "bash", "yml": "yaml",
    "c++": "cpp", "md": "markdown", "mjs": "javascript",
    "cjs": "javascript", "jsx": "jsx", "tsx": "tsx",
}
_LANG_DISPLAY = {
    "javascript": "JavaScript", "typescript": "TypeScript", "python": "Python",
    "bash": "Bash", "yaml": "YAML", "json": "JSON", "html": "HTML",
    "css": "CSS", "cpp": "C++", "c": "C", "go": "Go", "rust": "Rust",
    "sql": "SQL", "xml": "XML", "markdown": "Markdown", "text": "Text",
    "java": "Java", "kotlin": "Kotlin", "swift": "Swift", "dart": "Dart",
    "php": "PHP", "ruby": "Ruby", "lua": "Lua", "perl": "Perl",
    "dockerfile": "Dockerfile", "makefile": "Makefile", "diff": "Diff",
    "ini": "INI", "toml": "TOML", "nginx": "Nginx", "graphql": "GraphQL",
    "vue": "Vue", "svelte": "Svelte", "scss": "SCSS", "less": "Less",
    "jsx": "JSX", "tsx": "TSX", "haskell": "Haskell", "elixir": "Elixir",
    "erlang": "Erlang", "clojure": "Clojure", "powershell": "PowerShell",
    "objective-c": "Objective-C", "r": "R", "matlab": "MATLAB",
    "scala": "Scala", "groovy": "Groovy", "vb": "VB", "csharp": "C#",
    "fsharp": "F#", "asm": "Assembly", "protobuf": "Protobuf",
    "plaintext": "Text", "txt": "Text", "log": "Log", "nginx-conf": "Nginx",
}


def _fence_langs(text: str) -> list[str]:
    """按源码顺序提取所有 fenced code 的语言标识（空串 = 无语言标注）。"""
    langs: list[str] = []
    for m in _FENCE_RE.finditer(text):
        info = m.group(1).strip().split()
        langs.append(info[0].lower() if info else "")
    return langs


def _display_lang(lang: str) -> str:
    lang = _LANG_ALIAS.get(lang, lang)
    return _LANG_DISPLAY.get(lang, lang)


def _decorate_code_langs(html: str, langs: list[str]) -> str:
    """给每个 <div class="highlight"> 依序补上 data-lang 属性（无语言标注的块跳过）。"""
    if not langs:
        return html
    it = iter(langs)

    def repl(m):
        try:
            lang = next(it)
        except StopIteration:
            return m.group(0)
        if not lang:
            return m.group(0)
        return f'<div class="highlight" data-lang="{_html.escape(_display_lang(lang))}">'

    return _HILITE_RE.sub(repl, html)


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
    """渲染 Markdown 文本为 HTML，并做代码语言标签、图片懒加载、短代码展开。"""
    html = md_.reset().convert(text)
    html = _decorate_code_langs(html, _fence_langs(text))
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