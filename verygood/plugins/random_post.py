"""内置插件：随机文章 —— 在 /random/ 生成一个跳转到随机文章的页面。"""
from __future__ import annotations

import json

_RANDOM_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>随机文章 - {title}</title>
<meta name="robots" content="noindex,nofollow">
<script>
(function() {{
  var urls = {urls_json};
  var target = urls[Math.floor(Math.random() * urls.length)];
  if (!target) target = "{home}";
  location.replace(target);
}})();
</script>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;color:#8F4A60;background:#FBF8F9}}
a{{color:#AD5F76}}</style>
</head>
<body>
<noscript><p>请启用 JavaScript，或<a href="{home}">返回首页</a>。</p></noscript>
</body>
</html>
"""


def setup(ctx):
    @ctx.hook("finalize")
    def write_random(payload):
        site = payload["site"]
        out = payload["out"]
        from .. import config as c

        real = [c.abs_url(site["cfg"], p["url"]) for p in site["posts"]]
        home = c.abs_url(site["cfg"], "/")
        (out / "random").mkdir(parents=True, exist_ok=True)
        (out / "random" / "index.html").write_text(
            _RANDOM_HTML.format(
                title=site["cfg"]["site"]["title"],
                urls_json=json.dumps(real, ensure_ascii=False),
                home=home,
            ),
            encoding="utf-8",
        )