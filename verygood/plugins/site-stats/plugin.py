"""VeryGood 内置插件：站点数据组件（v1.3.0）。

侧栏「站点数据」卡片：文章总数 / 全站字数 / 浏览量 / 访客数。

- 文章数与总字数为构建期静态值（服务端直出，无刷可见）
- 浏览量 / 访客数由不蒜子统计（busuanzi）运行时填充，不可达时本地 localStorage 兜底
- v1.4.4：移除无效的「加载耗时 / 访客地区」面板项与代码

本插件同时是 v1.3.0 插件生态的完整示范：
  · 元信息（__title__ / __description__ / __version__ / __author__）
  · hook('post_parsed') 累计全站字数
  · hook('site_ready') 在站点模型就绪后注入组件骨架
  · inject('head'/'sidebar_data'/'body_end') 三处注入
  · __BASE__ 占位符（渲染时自动替换为站点 basePath）
  · 目录式内置插件 + static/ 静态资源（构建期拷到 dist/plugins/site-stats/）

关闭：config.yml 里 site.sidebar.site_data: false（保留其他插件能力）。
"""
from __future__ import annotations

__title__ = "站点数据"
__description__ = "侧栏站点数据卡片：文章/字数/浏览/访客"
__version__ = "1.0.0"
__author__ = "VeryGood Team"

_STATIC_URL = "__BASE__/plugins/site-stats/"


def setup(ctx):
    counter = {"words": 0}

    @ctx.hook("post_parsed")
    def _count_words(post):
        # 文章解析完成后累计全站字数（依赖 content 解析时写入的 word_count 字段）
        counter["words"] += int(post.get("word_count") or 0)

    @ctx.hook("site_ready")
    def _inject(site):
        sb = (site.get("cfg") or {}).get("site", {}).get("sidebar", {})
        if not sb.get("site_data", True):
            return
        posts = site.get("posts") or []
        n_posts = len(posts)
        n_words = counter["words"]

        # 1) 样式：head 注入
        ctx.inject("head", f'<link rel="stylesheet" href="{_STATIC_URL}site-stats.css">')
        # 2) 组件骨架：左侧栏注入（数值由服务端直出，开启 JS 前即可见）
        skeleton = (
            '<section class="side-stats" id="vg-stats" aria-label="站点数据">'
            '<h4 class="side-stats__title">站点数据</h4>'
            '<div class="side-stats__grid">'
            f'<div class="side-stats__cell"><b id="vg-stats-posts">{n_posts}</b><span>文章</span></div>'
            f'<div class="side-stats__cell"><b id="vg-stats-words">{n_words}</b><span>字数</span></div>'
            '<div class="side-stats__cell"><b id="vg-stats-pv">–</b><span>浏览</span></div>'
            '<div class="side-stats__cell"><b id="vg-stats-uv">–</b><span>访客</span></div>'
            "</div></section>"
        )
        ctx.inject("sidebar_data", skeleton)
        # 3) 运行时脚本：body_end 注入
        ctx.inject("body_end", f'<script src="{_STATIC_URL}site-stats.js" defer></script>')