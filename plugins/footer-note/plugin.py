"""footer-note：页脚自定义留言插件（v1.2.0 示例插件）

演示插件系统的四种能力：
  1. ctx.hook('init', cfg)             —— 构建初始化时拿到完整配置（找注入点）
  2. ctx.inject('footer_extra', html)  —— 向页脚注入一段 HTML
  3. ctx.add_global(name, value)       —— 向全部模板暴露全局变量
  4. ctx.register_shortcode(name, fn)  —— 注册 markdown 短代码

启用方式：把本目录（plugins/footer-note）放进仓库根 plugins/ 即自动加载；
也可在 config.yml 的 plugins: 里显式列出（相对仓库根的目录名）。

配置（可选）：
  site:
    footer:
      plugin_note: "❤ 用 VeryGood 搭建"   # 留空则不显示
"""
from __future__ import annotations

import datetime as _dt


def setup(ctx):
    # 1) 全局变量：构建年份（模板里可直接 {{ build_year }}）
    ctx.add_global("build_year", _dt.date.today().year)

    # 2) 短代码：{{gitee}} 之类可以在文章里用（示例：{{bili}} → 一条 B 站链接）
    def _bili(uin: str = "1"):
        return f'<a href="https://space.bilibili.com/{uin}" rel="noopener" target="_blank">我的 B 站</a>'

    ctx.register_shortcode("bili", _bili)

    # 3) 钩子：构建初始化时读取配置，决定是否注入页脚留言
    @ctx.hook("init")
    def _watch_init(cfg):
        note = ((cfg.get("site") or {}).get("footer") or {}).get("plugin_note", "")
        if not note:
            return
        ctx.inject(
            "footer_extra",
            '<p class="vg-plugin-note" style="margin:10px 0 0;color:var(--ink-faint);'
            'font-size:13px">' + note + "</p>",
        )