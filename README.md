# VeryGood · 粉色系开源博客主题

> **用 Issue 写博客，让 GitHub Actions 帮你发布。** 粉色 · 极简 · 顶级 SEO · 超高可玩性。

VeryGood 是一个为 GitHub Pages 量身定制的开源博客主题。它追随 Gmeek 的优雅理念：**写作发生在 GitHub Issue 里**，标签即状态机，关闭 Issue 即下线文章——你只需要专注内容，剩下的交给自动化。

**当前版本：v1.3.0** —— 左侧栏「最近更新」默认关闭（与右栏「近期文章」去重），改为内置插件 **site-stats** 站点数据组件（文章数/全站字数/浏览量/访客数/页面加载耗时/访客地区）；插件生态大升级：目录式内置插件 + 插件静态资源自动拷贝（`/plugins/{插件名}/`）+ 插件元信息 + `plugins_disabled` 禁用开关 + `sidebar_data`/`content_top` 新注入点 + `__BASE__` 占位符；品牌署名防护升级为**构建层双指纹 + 运行时 SHA-256 指纹重算 + 遮挡/隐藏探测**（`data-vg-fp`/`data-vg-sig`）。此前：插件生态（短代码/钩子/注入/全局变量/Jinja 过滤器）v1.2.0 · 移动端顶栏锁定 · 分类独立页 · 文章路径可定制 · 友链头像圆形化 · 品牌署名字符级锁定 v1.1.8 · 媒体灯箱 · 正文 1360px 满宽 · 公告弹窗 v1.1.6 · 朋友圈动态 · 全站内容 Actions · 三栏布局。

## ✨ 特性一览

| 维度 | 能力 |
| --- | --- |
| 🌸 颜值 | 低饱和玫瑰灰配色（莫兰迪粉，不甜腻、不过气），深浅双主题跟随系统 + 手动切换并记忆；友链头像圆形化（透明/白底 logo 兼容） |
| 🧱 布局 | 桌面三栏：左侧固定信息栏（品牌 + 站点数据 + 导航）/ 中间正文 / 右侧 Widget（近期文章、标签云、分类、友链）；**移动端顶栏锁定不随滚动**，窄屏优雅降级；左栏「最近更新」v1.3.0 起默认关闭（避免与右栏「近期文章」重复） |
| ✍️ 写作 | Gmeek 式 Issue 写作；也支持直接写 Markdown 推到 `source/posts/`；两种方式可混用；**文章访问路径可定制**（`path: /abc` → 域名/abc） |
| 🚀 部署 | 一条 GitHub Actions 工作流：Issue 事件 → 同步 Markdown → 构建 → 部署 Pages |
| 🔍 SEO | 结构化数据（BlogPosting / BreadcrumbList / WebSite+SearchAction）、Sitemap（含图片）、分类独立页、RSS、robots、humans、Open Graph、Twitter Card、canonical、noindex 分页、百度收录推送钩子 |
| ⚡ 性能 | 纯静态零框架、图片懒加载、CSS 构建压缩、环形回顶进度、轻量交互、插件钩子错误隔离 |
| 💬 互动 | 公告条（可关闭记忆）、朋友圈动态（站长/站点管理者用 Issue + Actions 推送，非访客留言）、giscus / utterances 评论、相关推荐、上下篇 |
| 🔌 可玩性 | **插件生态**（`python -m verygood plugins` 查看清单；短代码 / 钩子 / 模板注入 / 全局变量 / Jinja 过滤器 API；v1.3.0 起：目录式内置插件、插件静态资源、元信息、`plugins_disabled` 禁用、`sidebar_data`/`content_top` 注入点、`__BASE__` 占位符）、内置 **site-stats 站点数据组件**（浏览量/访客/加载耗时/地区）、主题整套可复制改写、前端实时搜索、标签/分类/归档、友链页、分类/标签自定义描述与置顶 |

## 🚀 快速开始（GitHub Pages + Issue 写作）

### 第一步：fork / 复制本仓库

点击右上角 **Use this template** 创建你自己的仓库（或直接 fork），仓库名建议为 `你的用户名.github.io`。

> 也可以克隆到本地改完再推：`git clone ... && cd VeryGood`

### 第二步：改配置与启用 Pages

1. 编辑 `config.yml`，至少改三处：`site.title`、`site.url`（你的站点地址）、`author` 信息；
2. 仓库 `Settings → Pages`：Source 选择 **GitHub Actions**；
3. （推荐）删除示例内容：`source/posts/issue-*.md`（这些是演示文章）。

之后每次 push 都会自动构建部署。

### 第三步：用 Issue 写第一篇文章

1. 打开仓库 **Issues → New issue**，看到模板后直接清空，写下文章 Markdown 正文；
2. 给 Issue 打标签 **`Article`**（发布）；
3. 点 Create → 等 Actions 跑完 → 打开 `https://你的用户名.github.io` 看效果。

### 给文章设置自定义访问路径（v1.2.0）

文章默认在 `/article/{标题}/`，可在 front matter 加 `path` 改**访问地址**（优先级最高，直达）：

```markdown
---
path: /abc        # 文章变成 域名/abc；同理 path: /wz/abc → 域名/wz/abc
---
```

也可用 `dir: /notes`（只换目录前缀，保留标题）或全局配置 `posts.article_dir: blog`（所有文章默认 `/blog/{标题}/`）。

### 给文章加封面（v1.1.7）

封面会自动出现在首页文章卡片、文章页顶部、社交分享图（og:image）与 sitemap 图片里。两种写法：

**写法 A：Issue 正文顶部写 front matter 指令**（最方便，Issue 即文章时用）：

```markdown
---
cover: https://example.com/cover.png   # 封面图 URL（外链或站内路径均可）
cover_alt: 封面描述                     # 可选，无障碍/分享用
summary: 自定义摘要                     # 可选，覆盖自动截取
---

这里是你真正的文章正文……
```

**写法 B：推送 Markdown 时在文件头部写 front matter**：

```markdown
---
title: 我的文章
cover: /assets/my-cover.png    # 放 source/assets/ 下的图会发布到 /assets/
cover_alt: 封面描述
---
```

规则：`cover` 填外链 URL 或站内相对路径都行；不填则用 `config.yml` 的 `posts.cover_default`（可为空，空就不显示封面）。图片建议 1200×630 比例（16:9），压缩到 ≤300KB，加载更快。

### 标签即状态机

| 标签 | 作用 |
| --- | --- |
| `Article` | **发布**这篇文章（可配置 `issues.publish_label`） |
| `Draft` | 存为**草稿**，线上不发布（本地 `build --drafts` 可见） |
| `Page` | 生成**独立页面**（如「关于我」），路由 `/issue-编号/` |
| `Moment` | 发一条**朋友圈动态**，展示在 `/board/` 时间线（站长碎碎念/站点动态） |
| `分类:技术` | 归入「技术」分类（前缀形如 `分类:` / `category:` 均可） |
| 其他任意标签 | 自动成为文章的 **tags** |

**关闭 Issue = 删除这篇文章/这条动态**；重新打开 = 恢复发布；编辑正文 = 更新站点。评论交流直接在 Issue 里进行，天然留档。
**文章、独立页、朋友圈动态、公告、友链、分类/标签等全站内容**都能通过 GitHub Actions + Issue 推送生效。

## 🖥 本地开发

```bash
pip install -r requirements.txt

python -m verygood build          # 构建到 dist/
python -m verygood build --drafts # 构建（含草稿）
python -m verygood serve --port 8000   # 本地预览（文件变更自动重建）
python -m verygood plugins        # 查看插件清单（内置 / 自动发现 / 显式配置）
```

## 📁 目录结构

```
VeryGood/
├── config.yml                    # 站点配置（唯一需要经常改的文件）
├── requirements.txt
├── verygood/                     # 构建引擎（纯 Python + Jinja2）
│   ├── builder.py                # 构建器：分页/标签/分类/归档/搜索/SEO/动态路由/署名校验
│   ├── config.py                 # 配置加载与默认值/规整
│   ├── content.py                # Markdown / front matter 解析 / 文章路径定制
│   ├── mdrender.py               # 渲染扩展：TOC、懒加载、短代码
│   ├── seo.py                    # sitemap / rss / robots / humans
│   ├── cli.py                    # build / serve / version / plugins 命令
│   └── plugins/                  # 插件系统 + 内置插件
├── plugins/                      # 用户插件自动发现目录（v1.2.0 生态入口）
│   ├── footer-note/              # 示例：页脚留言
│   └── post-stats/               # 示例：文章字数统计
├── themes/verygood/              # 主题（整套可复制自定义）
│   ├── theme.yml                 # 主题元数据
│   ├── templates/                # 12 个 Jinja2 模板 + 4 个 partials
│   └── static/                   # css / js（main.js + search.js）/ img
├── source/                       # 本地内容源
│   ├── posts/                    # 文章目录（issue-*.md 由 Actions 生成）
│   ├── pages/                    # 独立页面
│   ├── moments/                  # 朋友圈动态（打 Moment 标签的 Issue 生成）
│   └── assets/                   # 你的资源（图片等，会复制到 /assets/）
├── scripts/
│   ├── sync_issues.py            # Issue → Markdown（工作流调用，分页拉取防截断）
│   └── gen_assets.py             # 示例封面生成器（可选）
├── docs/                         # 使用文档 / 开发文档 / 插件开发文档
└── .github/workflows/build.yml   # 页面部署工作流（核心）
```

## ⚙️ 配置速查（`config.yml`）

```yaml
site:
  title: My Blog                # 站点名（必填）
  subtitle: 副标题
  url: https://xxx.github.io    # 站点地址（必填，无末尾斜杠）
  basePath: ""                  # 部署在 /仓库名/ 子路径时填仓库名
  language: zh-CN
  timezone: Asia/Shanghai

  # v1.1.6：公告弹窗（进入页面自动弹出，访客关闭后本浏览器不再弹）
  announcement:
    enabled: true               # 是否启用弹窗
    title: "欢迎来访"            # 弹窗标题（可留空）
    text: "🎉 欢迎来访"          # 文案（支持少量 HTML）
    link: "/board/"             # 点击跳转，留空则不显示按钮
    btn_text: "去看看"           # 按钮文案，留空默认「了解更多」
    type: info                  # info / tip / warn

  # v1.1：右侧栏（≥1366px 宽屏显示，330px 宽）
  rightbar:
    enabled: true
    show_toc: true              # 文章页目录放右栏，不挤正文
    show_recent: true           # 近期文章
    show_tags: true             # 标签云
    show_categories: true       # 分类
    show_links: true            # 友链缩略
    recent_count: 5
    tags_max: 24
    links_max: 8

  sidebar:
    recent_count: 0             # v1.3.0：左侧栏「最近更新」条数（默认 0 = 关闭，避免与右栏重复；改数字即可开启）
    site_data: true             # v1.3.0：站点数据组件（文章/字数/浏览/访客/加载耗时/地区，内置插件 site-stats）
    collapse: false             # true 时侧栏模块默认折叠，访客可展开
    custom:                      # 追加自定义模块（HTML 自由书写）
      # - title: 我的项目
      #   icon: "✨"
      #   html: "<p>任意 HTML</p>"

  nav:                          # 追加导航项
    - label: 友链
      url: /links/

author:
  name: Me
  email: me@example.com
  avatar: "https://..."          # 头像 URL，留空则不显示
  bio: 一句话介绍自己
  social:
    github: yourname
    twitter: ""
    weibo: ""
    rss: ""

taxonomies:                     # v1.1：分类/标签元数据（描述、置顶）
  categories:
    技术:
      desc: 技术相关的文章
      pin: true
  tags:
    verygood:
      desc: 关于主题的更新日志

board:                         # v1.1.2：朋友圈动态 /board/（站长 Issue → Actions 推送）
  enabled: true
  title: 朋友圈动态
  desc: 站长的碎碎念 —— 打上 Moment 标签即发布，关闭 Issue 即下线
  per_page: 30                  # 时间线最多展示条数
  repo: ""                      # 形如 "owner/repo"：动态卡片跳转对应 GitHub Issue，留空不显示
  giscus: false                 # 同步挂评论区

seo:
  image: /assets/og-default.png # 社交分享默认图（1200x630）
  twitter_handle: ""
  google_site_verification: ""  # Google Search Console 校验
  baidu_site_verification: ""   # 百度站长校验
  baidu_push: false             # 百度收录主动推送
  sitemap: true                 # 生成 sitemap.xml（含图片）
  rss: true
  robots: true
  noindex_page_2plus: true      # 分页第 2+ 页 noindex

posts:
  per_page: 8                   # 首页每页文章数
  excerpt_length: 150
  toc: true                     # 文章目录
  toc_depth: 2-3
  related: 3                    # 相关推荐条数
  date_format: "%Y-%m-%d"
  cover_default: ""             # 无封面时的默认封面
  article_dir: article          # v1.2.0：文章默认目录前缀（front matter path > dir > 此项）

post_extra:                     # v1.1.7：文章页底部信息，全部可开关
  show_updated: true            # 显示「更新于」时间（有更新时）
  show_copyright: true          # 显示版权行（作者 + 原文链接）
  show_share: true              # 显示分享栏（微博 / X / LinkedIn / 复制链接）
  license: ""                   # 自定义版权协议文案（如 "CC BY-NC-SA 4.0"），留空不显示

comments:                       # none / giscus / utterances
  provider: none                # ← 想要评论就改成 giscus 或 utterances 并填下方仓库参数
  giscus:
    repo: ""                    # user/comment-repo
    repo_id: ""
    category: ""
    category_id: ""
    mapping: pathname
    lang: zh-CN
  utterances:
    repo: ""

links:                          # 友链（/links/ + 右栏缩略）
  - name: GitHub
    url: https://github.com
    desc: 全球最大代码托管平台
    avatar: "https://github.com/github.png"   # v1.1：头像图，v1.2.0 起圆形展示；留空显示首字母彩球

issues:                         # Issue 写作配置
  publish_label: Article
  draft_label: Draft
  page_label: Page
  moment_label: Moment          # Moment 标签 → 朋友圈动态（/board/）
  slug_prefix: issue

plugins: ["plugins/my-plugin"]  # 显式声明用户插件；仓库根 plugins/ 下目录自动发现（v1.2.0）
plugins_disabled: []            # v1.3.0：禁用插件（内置名/目录名），如 ["site-stats", "footer-note"]
```

完整配置请看 [docs/使用文档.md](./docs/使用文档.md) 与 `config.yml` 内的中文注释。

## 🎨 自定义主题

VeryGood 的主题 = 一套可整体复制的 `themes/` 目录：

1. `cp -r themes/verygood themes/my-theme`
2. 改 `config.yml` 里 `theme.name: my-theme`；
3. 改 `theme.yml` 元数据与 `static/css/main.css` 顶部的 CSS 变量（全站配色都在里面）：

```css
:root {
  --rose-500: #C77A90;  /* 主粉色（莫兰迪，不高饱和） */
  --bg: #FBF8F9;        /* 页面底色 */
  --ink: #3A2A31;       /* 正文色 */
}
```

模板共 11 个，沿用 Jinja2 语法，核心文件：`base.html`（骨架与 SEO）、`index.html`（首页）、`post.html`（文章页）、`partials/_card.html`（卡片）。

## 🔌 插件开发（可玩性的尽头）

插件 = 仓库根 `plugins/` 下的一个目录（含 `plugin.py`）或单文件 `xxx.py`，**即装即用**，无需改 config。也可在 `config.plugins` 里显式声明目录路径。**完整 API / 钩子清单 / 示例 / 发布规范见 [插件开发文档](./docs/插件开发文档.md)。**

```python
# plugins/my-plugin/plugin.py
# v1.3.0：可选元信息（`python -m verygood plugins` 清单会展示）
__title__ = "我的插件"
__description__ = "一句话说明"
__version__ = "1.0.0"
__author__ = "你"

def setup(ctx):                 # 必须实现 setup(ctx)
    # 1) 注册短代码：正文里写 {{< box >}}...
    ctx.register_shortcode("box", box)

    # 2) 注册生命周期钩子（装饰器用法）
    @ctx.hook("post_parsed")
    def on_post(post):          # 每篇文章解析后执行
        post["my_field"] = "hi"

    # 3) 模板注入（v1.3.0 新增 sidebar_data / content_top / content_bottom；__BASE__ 占位符自动替换为站点 basePath）
    ctx.inject("head", '<meta name="x-custom" content="1">')
    ctx.inject("sidebar_data", '<div class="side-block">我的侧栏组件</div>')

    # 4) v1.2.0：向全部模板暴露能力
    ctx.add_global("build_year", 2026)        # 模板里 {{ build_year }}
    ctx.add_filter("wc", lambda s: len(s))    # 模板里 {{ text | wc }}
```

v1.3.0 还支持**目录式插件 + 静态资源**：把 `plugin.py` 与 `static/` 放进一个目录，构建时静态资源自动拷贝到 `dist/plugins/{插件名}/`，配合 `__BASE__/plugins/{插件名}/xxx.css` 引用（参考内置插件 `verygood/plugins/site-stats/`）。

可用的钩子（事件均为可选）：

| 钩子 | 时机 | payload |
| --- | --- | --- |
| `init` | 构建初始化 | `cfg`（dict） |
| `post_parsed` | 每篇文章解析后 | `post`（dict，可加自定义字段） |
| `page_parsed` | 每个页面解析后 | `page`（dict） |
| `site_ready` | 站点模型就绪 | `site`（dict） |
| `tpl_context` | 每个模板渲染前（v1.3.0） | `{"template": 模板名, "ctx": 渲染上下文}`（可注入键） |
| `finalize` | 构建收尾 | `{"out": 输出目录, "site": site, "cfg": cfg}` |

钩子抛异常不会中断构建（错误隔离），只记日志。禁用某插件：`plugins_disabled: ["插件名"]`（内置名或仓库 `plugins/` 目录名），`python -m verygood plugins` 会标记「已禁用」。

内置短代码开箱即用：

```markdown
{{< youtube dQw4w9WgXcQ >}}     # 嵌入 YouTube
{{< bilibili BV1xx411c7mD >}}  # 嵌入 B 站
```

内置插件：`shortcodes`（视频嵌入）、`reading_time`（阅读时长，`post.reading_time` 自动注入卡片/文章头部）、`random_post`（/random/ 随机文章跳转）、`site-stats`（v1.3.0 站点数据组件：文章数/全站字数服务端直出，浏览量/访客数不蒜子统计+本地兜底，加载耗时/访客地区运行时计算；`site.sidebar.site_data: false` 关闭）。

仓库自带两个示例插件（即装即用 + 现成代码参考）：`plugins/footer-note`（页脚留言）、`plugins/post-stats`（字数统计 / 阅读时长过滤器）。用 `python -m verygood plugins` 随时核对启用了哪些插件。

## 🤖 与 Gmeek 的对照

| | Gmeek | VeryGood |
| --- | --- | --- |
| 写作方式 | Issue + Label | Issue + Label（同理念） |
| 发布链路 | Actions 同步+构建 | Actions 同步+构建（同样可审计、可 fork 改进） |
| 主题风格 | 面向程序员 | 「程序员 + 生活向」通用，莫兰迪粉色高级感 |
| 布局 | 单栏/双栏 | 桌面三栏（信息栏/正文/右栏），窄屏自适应 |
| SEO | 基础 | 更深：BlogPosting/Breadcrumb/SearchAction 结构化数据 + 图片 sitemap |
| 互动 | 评论 | 评论区 + 公告 + 朋友圈动态（站长 Issue 推送） |
| 扩展 | 改主题 | 插件系统 + 主题复制机制，双重扩展 |

## ❓ FAQ

**Q：打开仓库没看见 issue 模板？**
模板在 `.github/ISSUE_TEMPLATE/article.md`，fork 模板仓库时默认带过来；也可以直接新建空白 Issue 开写。

**Q：想让 issue-*.md 不进 git 历史？**
全量切到 Issue 写作后，可在 `.gitignore` 加入：

```
source/posts/issue-*.md
```

Actions 每次自动同步生成，无需手提交。

**Q：Articles 页面的搜索怎么更新？**
搜索索引 `search.json` 在每次构建时自动生成，全前端实时搜索，无需任何后端。

**Q：如何接入评论？**
`config.yml` 的 `comments.provider` 改为 `giscus`，按 giscus.app 引导填入仓库、repo_id、category 等即可；utterances 同理。动态页也可通过 `board.giscus: true` 挂一套评论区。

**Q：百度收录？**
`seo.baidu_push` 为 true 时会在构建产物里输出推送钩子脚本（需结合站长平台主动推送 token 使用，见模板注释）。

**Q：友链头像不显示？**
在 `links` 条目里填 `avatar` 为图片 URL 即可；留空会显示首字母彩球。v1.2.0 起头像统一圆形展示（`object-fit: cover` 自动裁剪居中），透明底 / 白底 logo 都兼容，无需提前抠图。

**Q：文章想放到自定义路径（比如 域名/abc）？**
在文章 front matter 写 `path: /abc`（直达，支持任意层级如 `/wz/abc`）；`dir: /notes` 只换前缀保留标题；或用 `posts.article_dir` 改全站默认前缀。详见 README「自定义访问路径」一节。

**Q：公告条/侧栏折叠状态忘了怎么开？**
公告与折叠状态存在浏览器 localStorage（`vg-ann-close`、`vg-side-block:*`），换浏览器或清缓存即恢复默认。

**Q：页脚的「Powered by TechSauce & VeryGood」可以删掉吗？**
不可以。这是主题的强制署名，v1.3.0 起为**构建层 + 运行时双重防线**：构建时先验证 `vg-power-51f3a8` 标记，再对署名可见文本逐字符比对（剥离零宽/双向控制字符）、链接域名精确白名单 + 可见文本必须恰为 TechSauce / VeryGood，最后校验双指纹 `data-vg-fp` / `data-vg-sig`（SHA-256 与署名文本绑定）——任何删除、改名、改字、偷换链接、属性缺失都会让**构建直接失败**；即使绕过构建层，**页面运行时守卫**会重算 SHA-256 指纹、检测隐藏（display/opacity/裁剪/位移）、遮挡（elementFromPoint）并以 3-9 秒随机周期复查 + MutationObserver 监听，一经发现整页立即不可用。请保留署名行。

**Q：分类页和归档页什么关系？**
归档 `/archive/` 是时间线（分类云 + 按年归档）；v1.2.0 起分类有独立的 `/categories/` 页面（聚合所有分类卡片，页脚默认导航自带入口），每个分类的文章在 `/category/{分类名}/`。

**Q：朋友圈动态怎么发？**
新建 Issue → 写下正文（Markdown，支持图片、视频）→ 打上 `Moment` 标签 → Actions 自动同步到 `/board/` 时间线；想下线哪条就关闭对应 Issue。也可把 `board.repo` 配成 `owner/repo`，动态卡片会带「Issue #编号」跳转链接，方便观众查看原始内容。

## 📜 许可证

[MIT](./LICENSE) © VeryGood

喜欢就点个 ⭐，欢迎 Issue / PR。