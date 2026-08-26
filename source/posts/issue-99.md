---
title: 前端性能优化实战：从 LCP 到 CLS 的完整清单
date: 2026-08-18 21:15:00
category: 技术
tags:
  - 前端
  - 性能
  - 优化
cover: /assets/cover-frontend.png
---

性能优化不是玄学，而是一套可量化、可验证的工程实践。本文给出一个适用于绝大多数内容站点的优化清单，按「收益 / 成本」排序。

## 一、先测量，再优化

一切优化都要以指标为前提。三个核心 Web Vitals：

- **LCP**（最大内容绘制）：目标 < 2.5s
- **INP**（交互延迟）：目标 < 200ms
- **CLS**（布局偏移）：目标 < 0.1

Chrome DevTools Performance 面板 + Lighthouse 是起步标配。

## 二、图片：最大的可优化空间

```html
<!-- 懒加载 + 明确尺寸，双管齐下消除 CLS -->
<img
  src="cover.webp"
  width="1200"
  height="630"
  loading="lazy"
  decoding="async"
  alt="示例封面"
>
```

要点：

1. 用 `webp/avif` 替代 jpeg，常见省 30-60% 体积；
2. 必须声明 `width`/`height` 防止布局抖动；
3. `loading="lazy"` 对首屏以外的图片开箱即用。

## 三、CSS：交给构建器

VeryGood 在构建阶段会压缩 CSS，但更重要的一条原则是——**别在首屏引入无关样式**：

```css
/* 推荐：媒体查询拆分，首屏只加载必需的样式 */
@media (min-width: 1180px) {
  .post-layout--with-toc { grid-template-columns: 210px minmax(0, 760px); }
}
```

## 四、字体：亲测有效的三连

```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
```

同时给 `font-family` 写全系统字体栈，**保证字体加载失败时页面依然美观**——这是很多站点忽略的兜底手段。

## 五、常见指标速查表

| 指标 | 含义 | 目标值 | 常见优化 |
| --- | --- | --- | --- |
| LCP | 最大内容绘制 | < 2.5s | 图片压缩、CDN、preload |
| INP | 交互延迟 | < 200ms | 减少主线程长任务 |
| CLS | 布局偏移 | < 0.1 | 显式尺寸、字体交换 |
| TTFB | 首字节时间 | < 800ms | 静态托管、压缩 |

## 小结

记住一个公式：**性能 = 测量 → 定位 → 优化 → 复测**。不要凭感觉优化，把闭环跑起来比任何技巧都重要。