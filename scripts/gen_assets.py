#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VeryGood · 示例封面/分享图生成器（可选）
==========================================
生成一张统一的粉色渐变「占位封面」风格图：
  - source/assets/og-default.png   社交分享默认图 1200x630
  - source/assets/cover-{name}.png 示例文章封面 1200x630

用法：python scripts/gen_assets.py
依赖：Pillow（pip install Pillow）
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "source" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

W, H = 1200, 630

# 品牌渐变端点
PALETTE = [
    ((192, 119, 142), (233, 191, 201)),   # 主粉
    ((182, 106, 128), (226, 168, 184)),   # 深粉
    ((211, 148, 168), (246, 229, 235)),   # 浅粉
]


def find_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        r"/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_cover(path: Path, title: str, fine: str = "VeryGood Blog", seed: int = 0):
    rnd = random.Random(seed)
    (c1, c2) = PALETTE[seed % len(PALETTE)]

    # 垂直渐变底
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))

    # 柔和光斑（高斯模糊叠上去）
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(5):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        rr = rnd.randint(120, 320)
        alpha = rnd.randint(26, 60)
        c = (255, 250, 245, alpha)
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=c)
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    d = ImageDraw.Draw(img)

    # 装饰圆环
    for _ in range(3):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        rr = rnd.randint(90, 200)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(255, 255, 255, 40), width=rnd.randint(2, 6))

    # 左上品牌
    small = find_font(30)
    d.text((56, 52), "♥  VeryGood", font=small, fill=(255, 255, 255, 230))

    # 标题（居中，自动换行）
    big = find_font(72)
    mid = find_font(34)
    lines = []
    cur = ""
    for ch in title:
        if d.textlength(cur + ch, font=big) > W - 140:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    lines = lines[:2] or [""]

    y = H // 2 - len(lines) * 52
    for ln in lines:
        w = d.textlength(ln, font=big)
        d.text(((W - w) / 2, y), ln, font=big, fill=(255, 255, 255))
        y += 100

    fine_w = d.textlength(fine, font=mid)
    d.rounded_rectangle([(W - fine_w) / 2 - 26, y - 4, (W + fine_w) / 2 + 26, y + 48],
                        radius=26, outline=(255, 255, 255), width=2)
    d.text(((W - fine_w) / 2, y + 6), fine, font=mid, fill=(255, 255, 255))

    img.save(path, "PNG")
    print(f"[assets] 生成 {path.name}")


def main():
    random.seed(7)
    make_cover(ASSETS / "og-default.png", "VeryGood", "Pink · Fast · SEO Ready", seed=0)
    covers = [
        ("cover-welcome.png", "欢迎使用 VeryGood", "开源博客主题", 1),
        ("cover-frontend.png", "前端性能优化实战", "Performance", 2),
        ("cover-actions.png", "Issue 写作自动发布", "GitHub Actions", 0),
        ("cover-life.png", "生活里的粉色美学", "Lifestyle", 1),
    ]
    for fname, title, fine, seed in covers:
        make_cover(ASSETS / fname, title, fine, seed)
    print("[assets] 完成")


if __name__ == "__main__":
    main()