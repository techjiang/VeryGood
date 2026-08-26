"""post-stats：文章统计增强插件（v1.2.0 示例插件）

演示插件系统的另外两类能力：
  1. ctx.hook('post_parsed', post)   —— 每篇文章解析完后挂钩（可改 post 字段）
  2. ctx.add_filter(name, fn)        —— 注册 Jinja 过滤器，模板中 {{ value | filter }} 使用

能力：
  · 给每篇文章计算「字数」（中英文混合统计），写入 post['word_count']
  · 注册 | reading_time 过滤器：按字数估算阅读时长（分钟）
  · 注册 | wc 过滤器：任意文本的字数

启用方式：放在仓库根 plugins/ 下自动加载。
"""
from __future__ import annotations

import math
import re

_CN = re.compile(r"[\u4e00-\u9fff]")


def _count_words(text: str) -> int:
    """中文按字计，其余按单词计（英文空格分词），得到近似总字数。"""
    if not text:
        return 0
    cn = len(_CN.findall(text))
    rest = _CN.sub("", text)
    words = len(rest.split())
    return cn + words


def setup(ctx):
    def reading_time(text: str, wpm: int = 200) -> str:
        minutes = max(1, math.ceil(_count_words(text) / wpm))
        return f"约 {minutes} 分钟"

    ctx.add_filter("reading_time", reading_time)
    ctx.add_filter("wc", _count_words)

    @ctx.hook("post_parsed")
    def _attach_stats(post):
        body = post.get("content") or post.get("excerpt") or ""
        post["word_count"] = _count_words(body)