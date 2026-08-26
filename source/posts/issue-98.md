---
title: 用 GitHub Actions 把 Issue 变成博客文章：写给非程序员
date: 2026-08-15 09:20:00
category: 技术
tags:
  - GitHub Actions
  - DevOps
  - 教程
cover: /assets/cover-actions.png
---

很多人以为「用 GitHub 写博客」门槛很高，其实整条链路已经成熟到和发朋友圈差不多。这篇文章用一个视频 + 图解的方式讲清楚。

## 一条工作流搞定一切

{{< youtube dQw4w9WgXcQ >}}

视频里演示的就是本博客的发布流程：新建 Issue → 打标签 → 几十秒后站点更新。背后的产物是仓库里这份 `build.yml`：

```yaml
on:
  issues:
    types: [opened, edited, reopened, closed, labeled, unlabeled]
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python scripts/sync_issues.py    # Issue → Markdown
      - run: python -m verygood build         # Markdown → 静态站
      - uses: actions/upload-pages-artifact@v3
      - uses: actions/deploy-pages@v4         # 部署到 GitHub Pages
```

## 标签即状态机

这套系统把「标签」玩成了内容管理：

| 标签 | 含义 | 效果 |
| --- | --- | --- |
| `Article` | 发布 | 生成文章并部署 |
| `Draft` | 草稿 | 本地可见，线上不发布 |
| `Page` | 独立页面 | 生成 /xxx 页面 |
| `分类:技术` | 分类 | 归入「技术」分类 |
| 其他任意标签 | 标签 | 自动成为文章标签 |

## 为什么值得一试

- **零维护**：内容存在 GitHub，永不丢失，随时导出；
- **无服务端**：静态站点，全球免费 CDN；
- **协作友好**：审稿、纠错可以直接在 Issue 里评论；
- **可迁移**：所有文章都是标准 Markdown，随时换框架。

## 踩坑提示

首次部署记得在仓库 `Settings → Pages` 里把 Source 选成 **GitHub Actions**，这是最常见的「明明部署了但没生效」的原因。