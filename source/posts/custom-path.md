---
title: 自定义文章路径：dir 与 path 用法示例
date: 2026-08-25 09:00:00
category: 博客
tags:
  - verygood
  - 配置
path: /wz/demo
---

这篇文章通过 front matter 里的 `path: /wz/demo` 把访问地址固定为 `域名/wz/demo/`，与文章文件名无关。

## 路径规则一览

VeryGood v1.2.0 起，文章访问路径有三种写法（优先级从高到低）：

| 写法 | 效果 |
| --- | --- |
| front matter `path: /wz/demo` | 完整自定义，直达 `/wz/demo/` |
| front matter `dir: wz` | 目录前缀：`/wz/{slug}/` |
| config `posts.article_dir: article` | 全局默认：`/article/{slug}/` |

三者都留空时回退到旧式扁平布局 `/slug/`。默认配置下所有文章都在 `/article/` 目录下，互不干扰、清晰可读。