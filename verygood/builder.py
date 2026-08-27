"""主构建器：组装站点模型 → 渲染模板 → 输出静态站 + SEO 文件。"""
from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import html as _html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit as _urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__, config as _cfg, content, mdrender, seo as _seo
from .plugins import load_plugins

# ---------- 品牌署名指纹（v1.3.0 构建层常量） ----------
# 与 verygood/plugins 无关；供构建层与运行时守卫两端重算比对。
_POWER_MARKER = "vg-power-51f3a8"
_POWER_EXPECTED = "Powered by TechSauce & VeryGood"   # 标准署名可见文本（唯一允许的形态）
# 指纹 1：绑定署名文本本身（防「改字」）；指纹 2：绑定指纹 1 + footer 容器（防「整段换页脚」）
_POWER_FP1 = _hashlib.sha256(f"{_POWER_MARKER}|{_POWER_EXPECTED}".encode()).hexdigest()[:12]
_POWER_FP2 = _hashlib.sha256(f"site-footer|{_POWER_FP1}".encode()).hexdigest()[:12]

_CSS_MIN_RE = re.compile(r"/\*[\s\S]*?\*/")
_WS_RE = re.compile(r"\s+")
_PUNC_RE = re.compile(r"\s*([{}:;,])\s*")


def minify_css(text: str) -> str:
    """保守 CSS 压缩：去注释、压缩空白。不会改动字符串内容。"""
    text = _CSS_MIN_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    text = _PUNC_RE.sub(r"\1", text)
    text = text.replace(";}", "}").replace(",}", "}")
    return text.strip()


def paginate(items: list, per_page: int) -> list[list]:
    pages = [items[i:i + per_page] for i in range(0, len(items), per_page)]
    return pages or [[]]


def _tax_slug(name: str) -> str:
    """标签 / 分类名的目录安全形式：空白折叠为 '-'（与 scripts/sync_issues.py 的
    sanitize_tag 保持一致），中文等非 ASCII 保留原样。"""
    return re.sub(r"\s+", "-", (name or "").strip()) or "x"


def tax_path(kind: str, name: str) -> str:
    """标签 / 分类的站内路径（URL 与目录统一用 slug）。

    避免 URL / canonical / sitemap 中出现未编码空格（RFC 3986 不允许，属 SEO 缺陷）。
    """
    return f"/{kind}/{_tax_slug(name)}/"


def reading_time_of(post: dict) -> tuple[str, int]:
    words = len(content.clean_text(post["body_html"]))
    minutes = max(1, round(words / 350))
    return f"{minutes} 分钟", words


def related_posts(post: dict, posts: list, limit: int) -> list:
    def score(other):
        s = 0
        s += len(set(post["tags"]) & set(other["tags"])) * 3
        if post["category"] and post["category"] == other["category"]:
            s += 2
        return s

    cands = [p for p in posts if p["url"] != post["url"]]
    cands.sort(key=lambda p: (score(p), p["date"]), reverse=True)
    picked = [p for p in cands if score(p) > 0][:limit]
    return picked if picked else cands[:limit]


def build_site_model(cfg: dict, ctx, posts: list, pages: list, log) -> dict:
    now = _dt.datetime.now()
    tags: dict[str, list] = {}
    cats: dict[str, list] = {}
    for p in posts:
        for t in p["tags"]:
            tags.setdefault(t, []).append(p)
        if p["category"]:
            cats.setdefault(p["category"], []).append(p)

    def _sort_meta(items: dict[str, list], meta: dict) -> dict[str, list]:
        """置顶（taxonomies meta pin）优先，再按文章数与名称排序。"""
        ordered = sorted(items.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
        pinned = [kv for kv in ordered if meta.get(kv[0], {}).get("pin")]
        rest = [kv for kv in ordered if not meta.get(kv[0], {}).get("pin")]
        return dict(pinned + rest)

    tax_meta = cfg["taxonomies"]
    tags = _sort_meta(tags, tax_meta["tags"])
    cats = _sort_meta(cats, tax_meta["categories"])

    archive: dict[str, list] = {}
    for p in posts:
        archive.setdefault(p["date"].strftime("%Y"), []).append(p)

    for i, p in enumerate(posts):
        p["reading_time"], p["word_count"] = reading_time_of(p)
        p["related"] = related_posts(p, posts, cfg["posts"]["related"])
        p["prev"] = posts[i + 1] if i + 1 < len(posts) else None
        p["next"] = posts[i - 1] if i > 0 else None
        p["cover_url"] = _cfg.url_for(cfg, p["cover"]) if p["cover"] else ""
        p["updated_str"] = p["updated"].strftime(cfg["posts"]["date_format"])
        p["is_updated"] = p["updated"] > p["date"]

    rb = cfg["site"]["rightbar"]
    # 右侧栏数据：近期文章 / 标签云 / 分类列表 / 友链缩略
    rightbar = {
        "recent": [p for p in posts[: rb.get("recent_count", 5)]],
        "top_tags": [{"name": n, "count": len(ps)} for n, ps in tags.items()][: rb.get("tags_max", 24)],
        "categories": [
            {"name": n, "count": len(ps), "desc": tax_meta["categories"].get(n, {}).get("desc", "")}
            for n, ps in cats.items()
        ],
        "links": cfg["links"][: rb.get("links_max", 8)],
    }
    # 公告（模板经 cfg 读取，这里并入 site 便于统一）
    announcement = dict(cfg["site"]["announcement"])

    return {
        "cfg": cfg,
        "posts": posts,
        "pages": pages,
        "tags": tags,
        "categories": cats,
        "archive": archive,
        "links": cfg["links"],
        "taxonomies": tax_meta,
        "rightbar": rightbar,
        "announcement": announcement,
        "board": cfg["board"],
        "now": now,
        "year": now.year,
        "version": __version__,
    }


def _env(cfg: dict, theme_root: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(theme_root / "templates", followlinks=True),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # v1.3.0：品牌署名双指纹（data-vg-fp / data-vg-sig），构建层与运行时守卫共同校验。
    # 指纹与署名文本、marker、站点信息绑定：整段署名被复制到别的站点也会被识别为篡改。
    env.globals["power_fp1"] = _POWER_FP1
    env.globals["power_fp2"] = _POWER_FP2

    def datefmt(dt, fmt=None):
        return dt.strftime(fmt or cfg["posts"]["date_format"])

    env.filters["datefmt"] = datefmt
    env.globals["cfg"] = cfg
    env.globals["url_for"] = lambda path, **kw: _cfg.url_for(cfg, path)
    env.globals["abs_url"] = lambda path, **kw: _cfg.abs_url(cfg, path)
    env.globals["base_path"] = lambda: _cfg.base_path(cfg)
    env.globals["tax_path"] = tax_path
    return env


class Output:
    """输出写入器：所有文件经此落盘，方便统计与校验。"""

    def __init__(self, root: Path):
        self.root = root
        self.files: list[str] = []

    def write(self, rel: str, text: str):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.files.append(rel)

    def touch(self, rel: str, data: bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.files.append(rel)


def _pager(cur: int, total: int, base_url: str) -> dict:
    """base_url 形如 /tags/verygood/ 或 / 。返回分页信息（url 均为站内相对，不含 basePath）。"""
    return {
        "current": cur,
        "total": total,
        "page_url": lambda n: base_url + ("" if n == 1 else f"page/{n}/"),
        "prev_url": None if cur == 1 else (base_url.rstrip("/") + ("/" if base_url == "/" else "/" if cur == 2 else f"/page/{cur-1}/")),
        "next_url": None if cur == total else base_url + f"page/{cur+1}/",
    }


def _rmtree_force(p: Path) -> None:
    """跨平台强制删除目录：Windows 下先解除只读再删，避免 WinError 5/145。"""
    import os as _os
    import stat as _stat

    def _onerror(func, path, exc_info):
        try:
            _os.chmod(path, _stat.S_IWRITE)
        except OSError:
            pass
        func(path)

    shutil.rmtree(p, onerror=_onerror)


def build(cfg: dict, log=print, include_drafts: bool | None = None) -> dict:
    """执行完整构建，返回统计信息。"""
    out = cfg["build"]["output_dir"]
    if out.exists():
        _rmtree_force(out)
    out.mkdir(parents=True, exist_ok=True)
    ow = Output(out)

    b = cfg["build"]
    if include_drafts is not None:
        b["include_drafts"] = include_drafts

    log(f"[VeryGood v{__version__}] 开始构建")
    ctx = load_plugins(cfg, log)
    ctx.emit("init", cfg)

    md_ = mdrender.build_markdown(cfg["posts"]["toc_depth"])
    posts = content.load_posts(cfg, md_, ctx.shortcodes, log, b["include_drafts"])
    pages = content.load_pages(cfg, md_, ctx.shortcodes, log)
    moments = content.load_moments(cfg, md_, ctx.shortcodes, log)
    for p in posts:
        ctx.emit("post_parsed", p)
    for p in pages:
        ctx.emit("page_parsed", p)
    for m in moments:
        ctx.emit("page_parsed", m)

    site = build_site_model(cfg, ctx, posts, pages, log)
    site["moments"] = moments
    ctx.emit("site_ready", site)
    log(f"  · 文章 {len(posts)} 篇，页面 {len(pages)} 个，动态 {len(moments)} 条，标签 {len(site['tags'])} 个")

    env = _env(cfg, cfg["theme"]["root"])
    # v1.2.0：插件注册的全局变量与 Jinja 过滤器注入模板环境（插件可接管同名内置能力）
    for gname, gval in ctx.globals.items():
        env.globals[gname] = gval
    for fname, fval in ctx.filters.items():
        env.filters[fname] = fval
    extra = {"injections": ctx.template_injections}
    # v1.3.0：注入片段中的 __BASE__ 占位符统一替换为站点 basePath（如 /VeryGood 或空串）
    _bp = _cfg.base_path(cfg)
    if _bp and ctx.template_injections:
        extra["injections"] = {
            pos: [s.replace("__BASE__", _bp) for s in frags]
            for pos, frags in ctx.template_injections.items()
        }
    # 百度收录自动推送（主动推送 JS 钩子，配置 seo.baidu_push: true 时注入每个页面）
    if cfg["seo"].get("baidu_push"):
        ctx.inject(
            "body_end",
            '<script>(function(){var b=document.createElement("script");var p=location.protocol.split(":")[0];b.async=true;b.src=(p==="https"?"https://zz.bdstatic.com/linksubmit/push.js":"http://push.zhanzhang.baidu.com/push.js");var s=document.getElementsByTagName("script")[0];s.parentNode.insertBefore(b,s)})();</script>',
        )
    per = cfg["posts"]["per_page"]
    seo_cfg = cfg["seo"]
    noindex_p2 = seo_cfg["noindex_page_2plus"]

    def render(tpl, **kw):
        # v1.3.0：模板渲染前触发 tpl_context 钩子，插件可向渲染上下文注入键（kw 同一引用）
        ctx.emit("tpl_context", {"template": tpl, "ctx": kw})
        return _render_page(env, site, tpl, **kw)

    def cur(path: str) -> str:
        """站内路径 → 含 basePath 的完整路径，用于导航高亮比对。"""
        return _cfg.url_for(cfg, path)

    # ---------- 首页 + 分页 ----------
    chunks = paginate(posts, per)
    total_p = len(chunks)
    for idx, items in enumerate(chunks, 1):
        base_url = "/"
        pg = _pager(idx, total_p, "/")
        html = render(
            "index.html",
            posts_page=items,
            pager=pg,
            page_title=None if idx == 1 else f"第 {idx} 页 - {cfg['site']['title']}",
            current_path=cur("/"),
            noindex=(noindex_p2 and idx > 1),
            **extra,
        )
        if idx == 1:
            ow.write("index.html", html)
        else:
            ow.write(f"page/{idx}/index.html", html)

    # ---------- 文章页 ----------
    for p in posts:
        html = render("post.html", post=p, current_path=cur(p["url"]), **extra)
        ow.write(p["url"].strip("/") + "/index.html", html)

    # ---------- 自定义页面 ----------
    for p in pages:
        tpl = "links.html" if (p.get("slug") == "links" or p.get("type") == "links") else "page.html"
        html = render(tpl, page=p, current_path=cur(p["url"]), **extra)
        ow.write(p["url"].strip("/") + "/index.html", html)

    # ---------- 标签 / 分类 列表页 ----------
    ow.write("tags/index.html", render("tags.html", current_path=cur("/tags/"), **extra))
    for name, items in site["tags"].items():
        base_url = tax_path("tag", name)
        slug = _tax_slug(name)
        chunks = paginate(items, per)
        for idx, chunk in enumerate(chunks, 1):
            pg = _pager(idx, len(chunks), base_url)
            html = render("tag.html", tag=name, posts_page=chunk, pager=pg,
                          current_path=cur(base_url), noindex=(noindex_p2 and idx > 1), **extra)
            ow.write(base_url.strip("/") + "/index.html", html) if idx == 1 else ow.write(
                f"tag/{slug}/page/{idx}/index.html", html)
    for name, items in site["categories"].items():
        base_url = tax_path("category", name)
        slug = _tax_slug(name)
        chunks = paginate(items, per)
        for idx, chunk in enumerate(chunks, 1):
            pg = _pager(idx, len(chunks), base_url)
            html = render("tag.html", tag=name, posts_page=chunk, pager=pg,
                          current_path=cur(base_url), noindex=(noindex_p2 and idx > 1), **extra)
            ow.write(f"category/{slug}/index.html", html) if idx == 1 else ow.write(
                f"category/{slug}/page/{idx}/index.html", html)

    # ---------- 归档 / 分类云 / 留言板 / 搜索 / 404 ----------
    ow.write("archive/index.html", render("archive.html", current_path=cur("/archive/"), **extra))
    ow.write("categories/index.html", render("categories.html", current_path=cur("/categories/"), **extra))
    if cfg["board"].get("enabled", True):
        ow.write("board/index.html", render("board.html", current_path=cur("/board/"), **extra))
    search_index = [
        {
            "title": p["title"], "url": _cfg.url_for(cfg, p["url"]), "date": p["date_str"],
            "summary": p["summary"], "tags": p["tags"], "category": p["category"],
        }
        for p in posts
    ]
    ow.write("search.json", json.dumps({"posts": search_index}, ensure_ascii=False, indent=1))
    ow.write("search/index.html", render(
        "search.html", current_path=cur("/search/"), noindex=True, **extra))
    ow.write("404.html", render("404.html", current_path=cur("/404.html"), noindex=True, **extra))

    # ---------- SEO 文件 ----------
    absf = lambda p: _cfg.abs_url(cfg, p)
    sitemap_urls = []
    if seo_cfg["sitemap"]:
        # 首页（1.0 最高优先级，v1.1 补齐；无文章时用构建时间兜底）
        lastmod_home = posts[0]["updated"] if posts else _dt.datetime.now()
        sitemap_urls.append({"loc_abs": absf("/"), "lastmod": lastmod_home,
                             "freq": "daily", "priority": "1.0"})
        # 文章页 + 文章封面图（image sitemap，v1.1 拉到顶）
        for p in posts:
            images = []
            if p.get("cover_url"):
                images.append(absf(p["cover_url"]))
            for img in (p.get("images") or []):
                images.append(absf(img) if not img.startswith(("http://", "https://")) else img)
            sitemap_urls.append({"loc_abs": absf(p["url"]), "lastmod": p["updated"],
                                 "freq": "monthly", "priority": "0.8", "images": images})
        for p in pages:
            sitemap_urls.append({"loc_abs": absf(p["url"]), "lastmod": p["updated"], "freq": "monthly", "priority": "0.6"})
        for name in site["tags"]:
            sitemap_urls.append({"loc_abs": absf(tax_path("tag", name)), "freq": "weekly", "priority": "0.5"})
        for name in site["categories"]:
            sitemap_urls.append({"loc_abs": absf(tax_path("category", name)), "freq": "weekly", "priority": "0.5"})
        sitemap_urls.append({"loc_abs": absf("/archive/"), "freq": "weekly", "priority": "0.4"})
        sitemap_urls.append({"loc_abs": absf("/categories/"), "freq": "weekly", "priority": "0.5"})
        if cfg["board"].get("enabled", True):
            sitemap_urls.append({"loc_abs": absf("/board/"), "freq": "weekly", "priority": "0.4"})
        # 标签云 / 友链 收录入口
        sitemap_urls.append({"loc_abs": absf("/tags/"), "freq": "weekly", "priority": "0.4"})
        if site["links"]:
            sitemap_urls.append({"loc_abs": absf("/links/"), "freq": "monthly", "priority": "0.4"})
        ow.write("sitemap.xml", _seo.sitemap_xml(absf, sitemap_urls))

    if seo_cfg["rss"]:
        ow.write("rss.xml", _seo.rss_xml(absf, cfg, posts, __version__))

    if seo_cfg["robots"]:
        ow.write("robots.txt", _seo.robots_txt(absf, cfg))
        ow.write("humans.txt", _seo.humans_txt(cfg))

    # ---------- 静态资源 ----------
    theme_static = cfg["theme"]["root"] / "static"
    if theme_static.is_dir():
        _copy_tree(theme_static, out)
    src_assets = cfg["build"]["source_dir"] / "assets"
    if src_assets.is_dir():
        _copy_tree(src_assets, out / "assets")

    # v1.3.0：插件静态资源 → dist/plugins/{插件名}/（插件 inject 时用 __BASE__/plugins/{名}/... 引用）
    for _pname, _psdir in ctx.static_dirs.items():
        _dst = out / "plugins" / _pname
        _copy_tree(_psdir, _dst)
        log(f"  · 插件静态资源 → plugins/{_pname}/")

    # CSS 压缩（仅压缩主题自带 styles.css/markdown.css）
    if b["minify"]:
        for f in list(out.rglob("*.css")):
            if f.name.endswith(".min.css"):
                continue
            raw = f.read_text(encoding="utf-8")
            mini = minify_css(raw)
            if len(mini) < len(raw):
                f.write_text(mini, encoding="utf-8")

# ---------- 品牌署名防护（v1.3.0：字符级 + 域名精确 + 双指纹 + 链接文本 + 控制字符剥离） ----------
    # 页脚署名行「Powered by TechSauce & VeryGood」是品牌护栏，分毫不能修改：
    #   · 模板 marker（vg-power-51f3a8）缺失 → 构建失败
    #   · 署名可见文本逐字符比对（对比前剥离零宽/双向控制字符，防「看不见的字」混入）
    #   · 两个链接必须精确指向 docs.asoe.cn 与 github.com/techjiang/VeryGood（netloc 精确匹配，
    #     防 docs.asoe.cn.evil.com 之类的子串绕过），且均须 target="_blank" + rel 含 noopener
    #   · 链接可见文本必须恰为 TechSauce / VeryGood（防<a>标签被塞入前缀/伪装文本）
    #   · 双指纹校验（v1.3.0）：<footer data-vg-sig> 与 <p data-vg-fp> 与署名文本/marker 绑定，
    #     任何位置互换、整段克隆到其他站点、改容器属性 → 立即识别
    #   · 一切改动/顺序调换/增删字符 → 构建失败
    # 与主题内置运行时防线（逐字符比对 + 指纹重算 + 可见性/遮挡探测 + 周期性再校验）构成双保险。
    _POWER_PAT = re.compile(r'<p\s+(class="site-footer__powered"[^>]*?)>(.*?)</p>', re.S)
    _POWER_A_PAT = re.compile(r'<a\s+([^>]*)>(.*?)</a>', re.S | re.I)
    _POWER_FOOTER_PAT = re.compile(r'<footer\s+class="site-footer"[^>]*>', re.S)
    _POWER_HOST_A = "docs.asoe.cn"
    _POWER_HOST_B = "github.com"
    _POWER_PATH_B = "/techjiang/VeryGood"
    _TAG_RE = re.compile(r"<[^>]+>")
    # 零宽 / 双向文本控制字符：肉眼不可见但能改页面字节，必须剥离后比对
    _ZERO_W = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")

    def _norm_power_text(s: str) -> str:
        """去标签 + HTML 实体反转义 + 剥离零宽/双向字符 + 折叠空白，得到页面署名的可见文本。"""
        text = _TAG_RE.sub("", s)
        text = _html.unescape(text)
        text = _ZERO_W.sub("", text)
        return re.sub(r"\s+", " ", text).strip()

    def _power_href_ok(href: str, host: str, path: str | None = None) -> bool:
        """精确校验署名链接：协议 http/https + netloc 恰好等于目标域名（防子串伪装），
        path 非空时路径也须以目标路径开头（防 github 路径被偷换）。"""
        try:
            p = _urlsplit(href)
        except Exception:  # noqa: BLE001
            return False
        if p.scheme not in ("http", "https"):
            return False
        if (p.netloc or "").lower() != host:
            return False
        if path is not None and not (p.path or "").lower().startswith(path.lower()):
            return False
        return True

    missing = []
    # 只校验「模板渲染生成」的页面（ow.files），不校验 source/assets 等静态拷贝的
    # 原生 HTML——用户可能在 assets 里放自定义页面（如 SPA、落地页），它们不属于
    # 主题页脚体系，强校验会误伤。
    rendered_html = sorted(
        rel for rel in ow.files if rel.endswith(".html")
    )
    _POWER_P_CNT = re.compile(r'<p\s+class="site-footer__powered"')
    for rel in rendered_html:
        f = out / rel
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            missing.append(f"{f} [读取失败]")
            continue
# v1.4.2：marker 必须存在于 <footer class="site-footer"> 块内部（防把
        # 注释搬到页脚外其他位置糊弄构建层），且 site-footer 全页有且仅有一个
        fm0 = _POWER_FOOTER_PAT.search(txt)
        if not fm0:
            missing.append(f"{f} [缺失 <footer class=\"site-footer\">]")
            continue
        fend = txt.find("</footer>", fm0.end())
        if fend == -1:
            missing.append(f"{f} [缺失 </footer> 闭合结构]")
            continue
        footer_block = txt[fm0.start():fend + len("</footer>")]
        if _POWER_MARKER not in footer_block:
            missing.append(f"{f} [marker vg-power-51f3a8 必须位于 footer 内部]")
            continue
        if len(_POWER_FOOTER_PAT.findall(txt)) != 1:
            missing.append(f"{f} [site-footer 必须恰好出现一次]")
            continue
        if len(_POWER_P_CNT.findall(txt)) != 1:
            missing.append(f"{f} [.site-footer__powered 署名行必须恰好出现一次]")
            continue
        fm = fm0
        if not (fm and f'data-vg-sig="{_POWER_FP2}"' in fm.group(0)):
            missing.append(
                f"{f} [缺失/篡改 footer 签名 data-vg-sig (期望 {_POWER_FP2})]"
            )
            continue
        m = _POWER_PAT.search(txt)
        if not m:
            missing.append(f"{f} [缺失 .site-footer__powered 署名行]")
            continue
        p_attrs, p_inner = m.group(1), m.group(2)
        if f'data-vg-fp="{_POWER_FP1}"' not in p_attrs:
            missing.append(
                f"{f} [缺失/篡改署名行指纹 data-vg-fp (期望 {_POWER_FP1})]"
            )
            continue
        if _norm_power_text(p_inner) != _POWER_EXPECTED:
            missing.append(
                f"{f} [署名文本被篡改: "
                f"期望 `{_POWER_EXPECTED}`，实际 `{_norm_power_text(p_inner)}`]"
            )
            continue
        # 链接校验：恰好两个 a，分别精确指向两大官方地址；且均 target="_blank" + rel 含 noopener，
        # 链接可见文本必须恰为 TechSauce / VeryGood（防止塞入前缀文本或伪装元素）。
        # v1.4.2：链接与文本必须一一配对——TechSauce → docs.asoe.cn 在前，
        #        VeryGood → github.com/techjiang/VeryGood 在后，禁止交错/调包。
        links = _POWER_A_PAT.findall(p_inner)
        hrefs, ok_attr, texts_ok = [], True, True
        for attrs, inner in links:
            hm = re.search(r'href\s*=\s*"([^"]*)"', attrs, re.I)
            if not hm:
                ok_attr = False
                break
            hrefs.append(hm.group(1))
            rel_ok = re.search(r'rel\s*=\s*"([^"]*)"', attrs, re.I)
            rel_txt = (rel_ok.group(1).lower() if rel_ok else "")
            tgt_ok = re.search(r'target\s*=\s*"([^"]*)"', attrs, re.I)
            tgt_val = (tgt_ok.group(1).lower() if tgt_ok else "")
            if tgt_val != "_blank" or "noopener" not in rel_txt:
                ok_attr = False
                break
            if _norm_power_text(inner) not in ("TechSauce", "VeryGood"):
                texts_ok = False
        pair_ok = (
            len(links) == 2
            and _power_href_ok(hrefs[0], _POWER_HOST_A)
            and _power_href_ok(hrefs[1], _POWER_HOST_B, _POWER_PATH_B)
        )
        if len(links) != 2 or not ok_attr or not texts_ok or not pair_ok:
            missing.append(
                f"{f} [署名链接被篡改: 链接={links!r} hrefs={hrefs} 文本ok={texts_ok}]"
            )
    if missing:
        raise RuntimeError(
            "品牌署名保护触发（v1.3.0 字符级+域名精确+双指纹校验）：以下页面页脚署名缺失或被篡改，"
            "构建已终止——「Powered by TechSauce & VeryGood」分毫不能修改，"
            "删除/改名/改字/偷换链接/属性缺失的后果 = 站点立即无法使用。\n  "
+ "\n  ".join(missing)
        )

    # ---------- 插件收尾 ----------
    ctx.emit("finalize", {"out": out, "site": site, "cfg": cfg})

    log(f"  · 生成 {len(ow.files)} 个文件 → {out}")
    return {"posts": len(posts), "pages": len(pages), "tags": len(site["tags"]), "files": ow.files}


def _copy_tree(src: Path, dst: Path) -> None:
    for child in src.rglob("*"):
        if child.is_file():
            rel = child.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, dst / rel)


def _render_page(env, site: dict, template: str, **extra) -> str:
    tpl = env.get_template(template)
    return tpl.render(site=site, **extra)