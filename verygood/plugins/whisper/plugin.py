"""VeryGood 内置插件：右栏时钟 + 打字机微语卡片（v1.4.0）。

右栏新增两个小组件：
- 时间卡片（vg-clock）：本地时间，秒级刷新，与服务端无依赖，纯前端。
- 微语卡片（vg-whisper）：打字机效果逐条轮播短句，可暂停 / 继续。

配置（config.yml → site.rightbar）：
- show_clock: true/false         # 是否显示时间卡片，默认 true
- show_micro: true/false         # 是否显示微语卡片，默认 true
- micro_notes: [ "短句1", ... ]  # 自定义微语内容；不填则使用插件内置示例

本插件演示 v1.4.0 新增的 rightbar 注入点：
  · inject('head')      样式
  · inject('rightbar')  卡片骨架（右栏组件列表尾部）
  · inject('body_end')  运行时脚本
"""
from __future__ import annotations

import json

__title__ = "时钟与微语"
__description__ = "右栏时间卡片（秒级刷新）+ 打字机微语卡片（可暂停轮播）"
__version__ = "1.0.0"
__author__ = "VeryGood Team"

_STATIC_URL = "__BASE__/plugins/whisper/"

_DEFAULT_NOTES = [
    "用 Issue 写文章，推送即发布。",
    "莫兰迪粉：温柔，但不失深度。",
    "这篇要不要也放个封面？",
    "快捷键：左侧栏一键切换深浅色。",
    "好代码如好诗：简练、清晰、有余韵。",
]


def setup(ctx):
    @ctx.hook("site_ready")
    def _inject(site):
        rb = (site.get("cfg") or {}).get("site", {}).get("rightbar", {})
        if not rb.get("enabled", False):
            return  # 右栏整体关闭时无需注入
        show_clock = rb.get("show_clock", True)
        show_micro = rb.get("show_micro", True)
        if not (show_clock or show_micro):
            return

        ctx.inject("head", f'<link rel="stylesheet" href="{_STATIC_URL}whisper.css">')

        parts = []
        if show_clock:
            parts.append(
                '<section class="side-widget vg-clock" aria-label="当前时间">'
                '<h3 class="side-widget__title">'
                '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
                "此刻</h3>"
                '<div class="vg-clock__time">'
                '<span class="vg-clock__digit" id="vg-clock-h">--</span><i class="vg-clock__colon">:</i>'
                '<span class="vg-clock__digit" id="vg-clock-m">--</span><i class="vg-clock__colon vg-clock__colon--sec">:</i>'
                '<span class="vg-clock__sec" id="vg-clock-s">--</span>'
                "</div>"
                '<div class="vg-clock__date" id="vg-clock-date">--</div>'
                "</section>"
            )
        if show_micro:
            notes = rb.get("micro_notes") or _DEFAULT_NOTES
            # 注意：<script type="application/json"> 是 raw text 元素，浏览器不会反转义
            # &quot; 等实体——textContent 拿到的仍是字面 &quot;，JSON.parse 会失败。
            # 因此此处不做 quote 转义，只需防御 </script> 提前闭合。
            data = json.dumps(notes, ensure_ascii=False).replace("</", "<\\/")
            parts.append(
                '<section class="side-widget vg-whisper" aria-label="微语">'
                '<h3 class="side-widget__title">'
                '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>'
                "微语</h3>"
                '<div class="vg-whisper__stage">'
                '<p class="vg-whisper__text" id="vg-whisper-text"></p>'
                '<span class="vg-whisper__cursor" aria-hidden="true"></span>'
                "</div>"
                '<div class="vg-whisper__foot">'
                '<button class="vg-whisper__pause" id="vg-whisper-pause" type="button">暂停</button>'
                '<span class="vg-whisper__idx" id="vg-whisper-idx"></span>'
                "</div>"
                f'<script type="application/json" id="vg-whisper-data">{data}</script>'
                "</section>"
            )
        if parts:
            ctx.inject("rightbar", "\n".join(parts))
            ctx.inject("body_end", f'<script src="{_STATIC_URL}whisper.js" defer></script>')