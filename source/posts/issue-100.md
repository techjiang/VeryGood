---
title: 欢迎使用 VeryGood：用 Issue 写博客的粉色系主题
date: 2026-08-20 10:30:00
category: 博客
tags:
  - verygood
  - 入门
  - 教程
cover: /assets/cover-welcome.png
---

VeryGood 是一个开源博客主题：**粉色、轻量、SEO 顶级、可玩性极高**。它专门为 GitHub Pages 设计，并借鉴了 Gmeek 的核心理念——**不用动仓库，用 Issue 就能写文章**。

## 它是如何工作的

把博客当成一个「填满 Issue 的仓库」：

1. 新建一个 Issue；
2. 打好 `Article` 标签（发布）或 `Draft` 标签（草稿）；
3. 推送后，GitHub Actions 自动把 Issue 同步为 Markdown、构建网站并部署。

> 关闭 Issue，文章就会从站点上下线——发布、下线、改稿都在 Issue 里完成。

## 一分钟上手

```bash
git clone https://github.com/你的名字/your-blog.git
cd your-blog
python -m verygood serve        # 本地预览
```

然后到 GitHub 上新建 Issue 写第一篇文章吧。

## 它有哪些亮点

- 🌸 **粉色但不过气**：用低饱和玫瑰色系调配，深浅双主题；
- 🚀 **顶级 SEO**：结构化数据、Sitemap、RSS、Open Graph、Twitter Card 全套；
- 🔌 **超高拓展性**：插件系统、主题复制自定义、百来个可玩点；
- ⚡ **流畅体验**：零框架、懒加载、阅读进度、全站客户端搜索。

| 能力 | 说明 |
| --- | --- |
| 写作方式 | Issue / Markdown / 两者混用 |
| 评论 | giscus / utterances |
| 搜索 | 前端实时搜索，无需服务端 |
| 部署 | GitHub Actions，一次配置永久自动 |

## 下一步

查看右侧目录，或阅读仓库里的 `README.md`。祝玩得开心 ♥