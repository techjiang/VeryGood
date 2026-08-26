"""内置插件：阅读时长 —— post_parsed 钩子示例。

在文章/卡片 Meta 中展示「预计阅读 N 分钟」。构建引擎已内置计算，
此插件演示如何在 post_parsed 阶段追加自定义字段。
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")


def setup(ctx):
    @ctx.hook("post_parsed")
    def add_reading_meta(post):
        text = _TAG_RE.sub(" ", post["body_html"])
        words = len(text.split())
        minutes = max(1, round(words / 300))
        post["reading_time"] = f"{minutes} 分钟"
        post["word_count"] = words
        post["reading_note"] = f"全文约 {words} 字"