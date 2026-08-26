"""内容解析：Front Matter + Markdown 正文 → 文章/页面模型。"""
from __future__ import annotations

import datetime as _dt
import re
from html import unescape as _unescape
from pathlib import Path

import yaml

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)


def split_front_matter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return fm, text[m.end():]


def parse_datetime(value, fallback: _dt.datetime) -> _dt.datetime:
    if value is None:
        return fallback
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    if s.isdigit() and len(s) == 10:
        try:
            return _dt.datetime.fromtimestamp(int(s))
        except (OSError, ValueError, OverflowError):
            pass
    return fallback


def clean_text(html: str) -> str:
    text = TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = WS_RE.sub(" ", text)
    return _unescape(text).strip()


def make_excerpt(html: str, limit: int) -> str:
    text = clean_text(html)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _to_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def parse_post_file(
    file: Path,
    cfg: dict,
    md_,
    shortcodes: dict,
    log,
    kind: str = "posts",
) -> dict:
    """kind: posts / pages / drafts。返回文章 dict（含渲染后的 body_html）。"""
    stem = file.stem
    raw = file.read_text(encoding="utf-8")
    fm, body = split_front_matter(raw)

    now = _dt.datetime.now()
    date = parse_datetime(fm.get("date") or fm.get("created"), now)
    updated = parse_datetime(fm.get("updated"), date)

    slug = str(fm.get("slug") or stem).strip()

    title_raw = fm.get("title") or ""
    if not title_raw:
        title_raw = stem.replace("-", " ").title()
    title = str(title_raw)

    body_html = mdrender_render(md_, body, shortcodes)

    post = {
        "kind": kind,
        "slug": slug,
        "title": title,
        "date": date,
        "updated": updated,
        "date_str": date.strftime(cfg["posts"]["date_format"]),
        "tags": [t for t in _to_list(fm.get("tags"))],
        "category": (_to_list(fm.get("category")) or [""])[0],
        "summary": str(fm.get("summary") or fm.get("excerpt") or "").strip() or make_excerpt(body_html, cfg["posts"]["excerpt_length"]),
        "body_html": body_html,
        "rawbody": body,
        "cover": str(fm.get("cover") or "").strip() or cfg["posts"]["cover_default"] or "",
        "cover_alt": str(fm.get("cover_alt") or "").strip() or title,
        "draft": bool(fm.get("draft", False)) or kind == "drafts",
        "issue": fm.get("issue"),
        "seo": fm.get("seo") or {},
        "source_file": str(file),
    }

    if kind == "posts":
        post["url"] = f"/{slug}/"
        post["dir"] = "posts"
    elif kind == "pages":
        post["url"] = f"/{slug}/"
        post["dir"] = "pages"
    elif kind == "moments":
        post["url"] = f"/moments/{slug}/"  # 仅作为动态标识，不生成独立页
        post["dir"] = "moments"
    else:
        post["url"] = f"/drafts/{slug}/" if cfg["build"]["include_drafts"] else f"/{slug}/"
        post["dir"] = "drafts"

    # 正文图片列表（v1.1：用于 image sitemap / 灯箱预载）
    post["images"] = _IMG_SRC_RE.findall(body_html)

    # toc（动态/朋友圈时间线不生成目录）
    if cfg["posts"]["toc"] and kind != "moments":
        post["toc_html"] = toc_html(toc_from(md_))
    else:
        post["toc_html"] = ""

    return post


# 延迟导入避免循环依赖
def mdrender_render(md_, body, shortcodes):
    from . import mdrender as _m

    return _m.render(md_, body, shortcodes)


def toc_from(md_):
    from . import mdrender as _m

    return _m.toc_from(md_)


def toc_html(tokens):
    from . import mdrender as _m

    return _m.toc_html(tokens)


def load_posts(cfg: dict, md_, shortcodes: dict, log, include_drafts: bool = False) -> list[dict]:
    src = cfg["build"]["source_dir"]
    posts_dir = src / "posts"
    posts = []
    if posts_dir.is_dir():
        for f in sorted(posts_dir.glob("*.md")):
            try:
                p = parse_post_file(f, cfg, md_, shortcodes, log, "posts")
                if p["draft"] and not include_drafts:
                    continue
                posts.append(p)
            except Exception as e:  # noqa: BLE001
                log(f"  [warn] 文章解析失败 {f.name}: {e}")
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def load_pages(cfg: dict, md_, shortcodes: dict, log) -> list[dict]:
    src = cfg["build"]["source_dir"]
    pages_dir = src / "pages"
    pages = []
    if pages_dir.is_dir():
        for f in sorted(pages_dir.glob("*.md")):
            try:
                pages.append(parse_post_file(f, cfg, md_, shortcodes, log, "pages"))
            except Exception as e:  # noqa: BLE001
                log(f"  [warn] 页面解析失败 {f.name}: {e}")
    return pages


def load_moments(cfg: dict, md_, shortcodes: dict, log) -> list[dict]:
    """加载朋友圈动态（source/moments/*.md，由 sync_issues.py 经 Moment 标签同步生成，
    也可手写放置）。按时间倒序返回。"""
    src = cfg["build"]["source_dir"]
    moments_dir = src / "moments"
    moments = []
    if moments_dir.is_dir():
        for f in sorted(moments_dir.glob("*.md")):
            try:
                m = parse_post_file(f, cfg, md_, shortcodes, log, "moments")
                if m.get("draft"):
                    continue
                # 动态标题不展示 Issue 占位名，展示正文摘要
                m["kind"] = "moments"
                moments.append(m)
            except Exception as e:  # noqa: BLE001
                log(f"  [warn] 动态解析失败 {f.name}: {e}")
    moments.sort(key=lambda m: m["date"], reverse=True)
    return moments