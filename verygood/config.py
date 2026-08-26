"""配置加载与规整：默认值 + 用户 config.yml 深合并。"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent  # 仓库根目录

DEFAULTS = {
    "site": {
        "title": "VeryGood",
        "subtitle": "",
        "description": "",
        "keywords": ["blog", "github pages"],
        "url": "",
        "basePath": "",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "nav": [],
        "footer_text": "",
        "sidebar_recent": 5,
        # 公告弹窗（v1.1.6 起为弹窗样式，此前为顶部横幅）
        "announcement": {
            "enabled": False,
            "text": "",
            "title": "",             # 弹窗标题（留空则不显示标题）
            "link": "",
            "btn_text": "",          # 链接按钮文案（留空默认「了解更多」）
            "type": "info",          # info / tip / warn
        },
        # 右侧栏（v1.1，≥1366px 宽屏显示，330px 宽）
        "rightbar": {
            "enabled": True,
            "show_toc": True,        # 文章页目录（宽屏放右栏）
            "show_recent": True,
            "recent_count": 5,
            "show_tags": True,
            "tags_max": 24,
            "show_categories": True,
            "show_links": True,
            "links_max": 8,
        },
        # 左侧栏自定义（v1.1）
        "sidebar": {
            "recent_count": 5,       # 覆盖顶层 sidebar_recent，留空则用顶层值
            "collapse": False,       # 模块默认折叠
            "custom": [],            # 追加自定义模块 [{title, icon, html}]
        },
    },
    "author": {
        "name": "",
        "email": "",
        "avatar": "",
        "bio": "",
        "social": {"github": "", "twitter": "", "weibo": "", "rss": ""},
    },
    # 分类 / 标签元数据（v1.1）：可在归档页展示描述、钉在列表前部
    "taxonomies": {
        "categories": {},            # {名称: {desc, pin}}
        "tags": {},                  # {名称: {desc, pin}}
    },
    "board": {                       # 朋友圈动态页 /board/（v1.1.2 起：站长 Issue→Actions 推送）
        "enabled": True,
        "title": "朋友圈动态",
        "desc": "站长的碎碎念与站点动态 —— 用 GitHub Issue（打上 Moment 标签）推送，关闭 Issue 即下线。",
        "per_page": 30,              # 时间线最多展示条数（其余由站长在 Issue 中管理）
        "repo": "",                  # 形如 "owner/repo"：动态卡片跳转 GitHub Issue 的来源仓库，留空则不显示
        "giscus": False,             # 同时挂 giscus 评论区（继承 comments.giscus 配置）
    },
    "seo": {
        "image": "/assets/og-default.png",
        "twitter_handle": "",
        "google_site_verification": "",
        "baidu_site_verification": "",
        "baidu_push": False,
        "sitemap": True,
        "rss": True,
        "robots": True,
        "noindex_page_2plus": True,
    },
    "theme": {"name": "verygood"},
    "issues": {"publish_label": "Article", "draft_label": "Draft", "page_label": "Page", "moment_label": "Moment", "slug_prefix": "issue"},
    "posts": {
        "per_page": 8,
        "excerpt_length": 150,
        "toc": True,
        "toc_depth": "2-3",
        "related": 3,
        "date_format": "%Y-%m-%d",
        "cover_default": "",
    },
    "comments": {"provider": "none"},
    "links": [],
    "plugins": [],
    "build": {
        "source_dir": "source",
        "output_dir": "dist",
        "minify": True,
        "include_drafts": False,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(cfg_path=None, root: Path | None = None) -> dict:
    """加载 config.yml 并与默认值合并，返回规整后的配置。"""
    root = root or BASE_DIR
    path = Path(cfg_path) if cfg_path else root / "config.yml"
    overrides = {}
    if path.exists():
        overrides = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = deep_merge(DEFAULTS, overrides)
    normalize(cfg, root)
    return cfg


def normalize(cfg: dict, root: Path) -> None:
    s = cfg["site"]
    s["url"] = (s.get("url") or "").rstrip("/")
    if not s["url"]:
        s["url"] = "http://localhost:8000"  # 本地预览兜底
    s["basePath"] = (s.get("basePath") or "").strip("/")
    s["subtitle"] = s.get("subtitle") or ""
    if not s.get("description"):
        s["description"] = s["subtitle"] or f"{s['title']} · 一个开源博客主题"
    if not s.get("keywords"):
        s["keywords"] = [s["title"]]
    if not cfg["author"].get("social", {}).get("rss"):
        cfg["author"]["social"]["rss"] = "/rss.xml"

    # v1.1：sidebar.recent_count 向后兼容顶层 site.sidebar_recent
    sb = s.setdefault("sidebar", {})
    if not sb.get("recent_count"):
        sb["recent_count"] = s.get("sidebar_recent", 5)
    sb.setdefault("collapse", False)
    sb.setdefault("custom", [])
    if not isinstance(sb["custom"], list):
        sb["custom"] = []

    # v1.1.6：公告弹窗规整
    ann = s.setdefault("announcement", {})
    ann.setdefault("enabled", False)
    ann.setdefault("text", "")
    ann.setdefault("title", "")
    ann.setdefault("link", "")
    ann.setdefault("btn_text", "")
    ann.setdefault("type", "info" if ann.get("type") not in ("info", "tip", "warn") else ann["type"])

    # v1.1.7：文章页底部信息（更新于 / 版权行 / 分享）规整
    pe = s.setdefault("post_extra", {})
    pe.setdefault("show_updated", True)
    pe.setdefault("show_copyright", True)
    pe.setdefault("show_share", True)
    pe.setdefault("license", "")

    # v1.1：右侧栏规整
    rb = s.setdefault("rightbar", {})
    rb.setdefault("enabled", True)
    rb.setdefault("show_toc", True)
    rb.setdefault("show_recent", True)
    rb.setdefault("recent_count", sb["recent_count"])
    rb.setdefault("show_tags", True)
    rb.setdefault("tags_max", 24)
    rb.setdefault("show_categories", True)
    rb.setdefault("show_links", True)
    rb.setdefault("links_max", 8)

    # v1.1：分类 / 标签元数据归一化为 {名称: {desc, pin}}
    tax = cfg.setdefault("taxonomies", {})
    for _kind in ("categories", "tags"):
        _src = tax.get(_kind) or {}
        tax[_kind] = {
            str(k): {
                "desc": str((v or {}).get("desc", "")) if isinstance(v, dict) else "",
                "pin": bool((v or {}).get("pin", False)) if isinstance(v, dict) else False,
            }
            for k, v in _src.items()
        }

    # v1.1.2：朋友圈动态页规整（站长 Issue 推送，无 localStorage）
    bd = cfg.setdefault("board", {})
    bd.setdefault("enabled", True)
    bd.setdefault("title", "朋友圈动态")
    bd.setdefault("desc", "站长的碎碎念与站点动态 —— 用 GitHub Issue（打上 Moment 标签）推送。")
    bd.setdefault("per_page", 30)
    bd.setdefault("repo", "")
    bd.setdefault("giscus", False)
    if "local" in bd:
        bd.pop("local")  # 移除废弃的本地留言配置

    b = cfg["build"]
    b["source_dir"] = root / b["source_dir"]
    b["output_dir"] = root / b["output_dir"]
    theme_root = root / "themes" / cfg["theme"]["name"]
    cfg["theme"]["root"] = theme_root if theme_root.is_dir() else root / "themes" / "verygood"


def base_path(cfg: dict) -> str:
    bp = cfg["site"]["basePath"]
    return "/" + bp if bp else ""


def _is_external(p: str) -> bool:
    """http(s):// 或 // 协议相对链接视为外部，不再拼接 basePath。"""
    return p.startswith(("http://", "https://", "//"))


def _has_base(cfg: dict, p: str) -> bool:
    """p 是否已含 basePath 前缀（防重复拼接）。"""
    bp = base_path(cfg)
    return bool(bp) and (p == bp or p.startswith(bp + "/"))


def url_for(cfg: dict, path: str) -> str:
    """站内相对 URL（含 basePath 前缀）。path 形如 /foo/ 或 foo/；外部链接原样返回；
    已含前缀时幂等返回。"""
    if _is_external(path):
        return path
    p = path if path.startswith("/") else "/" + path
    if _has_base(cfg, p):
        return p
    return (base_path(cfg) + p) or "/"


def abs_url(cfg: dict, path: str) -> str:
    """绝对 URL（用于 canonical / OG / sitemap / RSS / JSON-LD）；外部链接原样返回；
    已含前缀时幂等返回。"""
    if _is_external(path):
        return path
    p = path if path.startswith("/") else "/" + path
    if _has_base(cfg, p):
        return cfg["site"]["url"] + p
    return cfg["site"]["url"] + base_path(cfg) + p