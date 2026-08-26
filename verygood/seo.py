"""SEO 输出：sitemap.xml / rss.xml / robots.txt / humans.txt 生成。"""
from __future__ import annotations

import datetime as _dt
from email.utils import format_datetime


def sitemap_xml(abs_url, urls: list[dict]) -> str:
    """urls: [{loc_abs, lastmod(date), freq, priority, images?: [abs_url]}]"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for u in urls:
        last = u.get("lastmod") or _dt.date.today()
        lastmod = last.strftime("%Y-%m-%d") if hasattr(last, "strftime") else str(last)
        loc = _esc(u["loc_abs"])
        lines.append(
            f"  <url><loc>{loc}</loc>"
            f"<lastmod>{lastmod}</lastmod>"
            f"<changefreq>{u.get('freq', 'weekly')}</changefreq>"
            f"<priority>{u.get('priority', 0.7)}</priority>"
        )
        unique = []
        for img in u.get("images") or []:
            img = _esc(img)
            if img and img not in unique:
                unique.append(img)
                lines.append(f"    <image:image><image:loc>{img}</image:loc></image:image>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _aware(dt, tz_name: str = "") -> _dt.datetime:
    """把可能无时区的 datetime 转成带时区的时间（用于 RSS 的 UTC 输出）。"""
    if dt.tzinfo is not None:
        return dt
    try:
        if tz_name:
            from zoneinfo import ZoneInfo

            return dt.replace(tzinfo=ZoneInfo(tz_name))
    except Exception:
        pass
    return dt.replace(tzinfo=_dt.timezone.utc)


def rss_xml(abs_url, cfg: dict, posts: list[dict], version: str = "") -> str:
    site = cfg["site"]
    author = cfg["author"]
    tz_name = site.get("timezone", "")
    title = _esc(site["title"])
    desc = _esc(site["description"])
    link = abs_url("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{title}</title>",
        f"    <description>{desc}</description>",
        f"    <link>{link}</link>",
        f'    <atom:link href="{abs_url("/rss.xml")}" rel="self" type="application/rss+xml"/>',
        f"    <language>{_esc(site['language'])}</language>",
        f"    <generator>VeryGood {version}</generator>",
        f"    <managingEditor>{_esc(author.get('email', ''))} ({_esc(author.get('name', ''))})</managingEditor>",
]
    for p in posts:
        pub = format_datetime(_aware(p["date"], tz_name).astimezone(_dt.timezone.utc), usegmt=True)
        lines += [
            "    <item>",
            f"      <title>{_esc(p['title'])}</title>",
            f"      <link>{abs_url(p['url'])}</link>",
            f"      <guid isPermaLink=\"false\">{abs_url(p['url'])}</guid>",
            f"      <pubDate>{pub}</pubDate>",
            f"      <description><![CDATA[{_esc_cdata(p['summary'])}  <a href=\"{abs_url(p['url'])}\">阅读全文 →</a>]]></description>",
        ]
        for t in p["tags"]:
            lines.append(f"      <category>{_esc(t)}</category>")
        lines.append("    </item>")
    lines += ["  </channel>", "</rss>"]
    return "\n".join(lines) + "\n"


def robots_txt(abs_url, cfg=None) -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /search/\n"
        "\n"
        f"Sitemap: {abs_url('/sitemap.xml')}\n"
    )


def humans_txt(cfg: dict) -> str:
    site = cfg["site"]
    author = cfg["author"]
    lines = [
        "/* TEAM */",
        f"Author: {author.get('name', '')}",
    ]
    if author.get("email"):
        lines.append(f"Contact: {author['email']}")
    if author.get("social", {}).get("github"):
        lines.append(f"GitHub: https://github.com/{author['social']['github']}")
    lines += [
        "",
        "/* SITE */",
        f"Site: {site['title']}",
        f"URL: {site['url']}",
        "Powered by VeryGood - an open-source pink blog theme for GitHub Pages.",
    ]
    return "\n".join(lines) + "\n"


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _esc_cdata(s: str) -> str:
    return str(s).replace("]]>", "]]]]><![CDATA[>")