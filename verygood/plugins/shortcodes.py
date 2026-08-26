"""内置插件：视频嵌入短代码（YouTube / Bilibili）。"""
from __future__ import annotations


def _make_embed(provider: str, url: str, title: str = "") -> str:
    return (
        f'<div class="embed embed--{provider}">'
        f'<iframe src="{url}" title="{title}" loading="lazy" '
        f'frameborder="0" allowfullscreen allow="accelerometer; autoplay; '
        f'clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share">'
        f"</iframe></div>"
    )


def setup(ctx):
    def youtube(args):
        vid = args[0] if args else ""
        if not vid:
            return None
        return _make_embed("youtube", f"https://www.youtube-nocookie.com/embed/{vid}?rel=0", "YouTube 视频")

    def bilibili(args):
        bv = args[0] if args else ""
        if not bv:
            return None
        return _make_embed("bilibili", f"//player.bilibili.com/player.html?bvid={bv}&high_quality=1&danmaku=0", "Bilibili 视频")

    ctx.register_shortcode("youtube", youtube)
    ctx.register_shortcode("bilibili", bilibili)