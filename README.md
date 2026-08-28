# VeryGood · 莫兰迪粉开源博客主题

> 用 Issue 写博客，让 GitHub Actions 帮你发布。粉色 · 极简 · 顶级 SEO · 超高可玩性。

VeryGood 是一个为 GitHub Pages 量身定制的开源博客主题。写作发生在 GitHub Issue 里——标签即状态机，关闭 Issue 即下线文章。你只管写，剩下的交给自动化。

**当前版本：v1.6.0** — 左侧栏心电图特效（纯 CSS/SVG 动画，零外部资源依赖）、彻底移除幻灯片功能、静态资源版本戳 v=6。

## 特性一览

| 维度 | 能力 |
| --- | --- |
| 🌸 颜值 | 低饱和玫瑰灰配色（莫兰迪粉 #C0778E），不甜腻、不过气；深浅双主题跟随系统 + 手动切换并记忆 |
| 🧱 布局 | 桌面三栏：左侧固定信息栏（含心电图特效）/ 中间正文 / 右侧 Widget；移动端顶栏吸顶，窄屏优雅降级 |
| ✍️ 写作 | Gmeek 式 Issue 写作，标签即状态机；也支持直接推 Markdown 到 `source/posts/`，两种方式互不干扰 |
| 🚀 部署 | 一条 GitHub Actions 工作流完成全链路：Issue 同步 → 构建 → 部署 Pages |
| 🔍 SEO | 结构化数据（BlogPosting / BreadcrumbList / WebSite+SearchAction）、Sitemap（含图片）、RSS、Open Graph、Twitter Card、canonical、百度推送 |
| ⚡ 性能 | 纯静态零框架、图片懒加载、CSS 构建压缩、环形回顶进度 |
| 💬 互动 | 公告弹窗、朋友圈动态（站长 Issue 推送）、giscus / utterances 评论 |
| 🔌 可玩性 | 插件生态：5 个内置插件 + 用户自动发现，短代码 / 钩子 / 模板注入 / Jinja 过滤器全链路 API |
| 🔒 署名锁定 | 五层防线：构建层校验 + 运行时 SHA-256 + MutationObserver + CSS 防篡改 + CSS 伪元素备份 |
| 💗 心跳特效 | 左侧栏纯 CSS/SVG 心电图动画，零 JS 依赖、零外部资源，流畅无卡顿 |

## 快速开始

### 1. 创建仓库

点击右上角 **Use this template** 创建你自己的仓库（或直接 fork），仓库名建议为 `用户名.github.io`。

### 2. 改配置

编辑 `config.yml`，至少改三处：

```yaml
site:
  title: My Blog
  url: https://用户名.github.io    # 无末尾斜杠
author:
  name: 你的名字
```

### 3. 启用 Pages

仓库 `Settings → Pages`：Source 选择 **GitHub Actions**。

### 4. 用 Issue 写第一篇文章

1. 打开仓库 **Issues → New issue**，直接写下 Markdown 正文；
2. 给 Issue 打标签 **`Article`** 即发布（首次部署后 Actions 自动创建标签）；
3. 等 Actions 跑完，打开 `https://用户名.github.io` 看效果。

> 关闭 Issue = 删除文章；重新打开 = 恢复发布；编辑正文 = 更新站点。评论交流直接在 Issue 里进行，天然留档。

## 标签即状态机

| 标签 | 作用 |
| --- | --- |
| `Article` | 发布这篇文章 |
| `Draft` | 存为草稿，线上不发布 |
| `Page` | 生成独立页面（如「关于」） |
| `Moment` | 发一条朋友圈动态，展示在 `/board/` 时间线 |
| `分类:技术` | 归入「技术」分类（前缀 `分类:` / `category:` 均可） |
| 其他任意标签 | 自动成为文章 tags |

## v1.6.0 更新内容

**左侧栏心电图特效** — 彻底移除 v1.5.x 的图片链接幻灯片功能，在左侧栏空出位置新增纯 CSS/SVG 心电图动画：SVG path 描线动画（`stroke-dasharray` + `stroke-dashoffset` 循环绘制），粉色波形连续滚动，顶部装饰圆点随心跳脉动。零 JavaScript 依赖、零外部资源请求，兼容 PC 端与移动端，流畅无卡顿。

**左侧栏固定不动** — 明确锁定左侧栏 `position: fixed`，不随页面滚动移动，视觉稳定。

**稳定性提升** — 移除幻灯片后消除了此前 PC 端图片不显示的根因（外部图床被浏览器追踪防护拦截），不再依赖任何外部图片域名，所有视觉元素均在仓库内自包含。

**静态资源版本戳** — v=6，确保浏览器缓存正确更新。

## v1.5.2 更新内容

**右侧栏音乐播放器** — 在右侧栏"微语"下方新增音乐功能卡片：封面旋转动画、进度条拖拽 seek、上一首/下一首切换、自动播放下一首、加载 shimmer 效果、播放错误友好提示。通过 `config.yml` 的 `music` 配置段自定义曲目列表。

**署名五层防线** — 在 v1.5.1 四层防线基础上新增：① CSS 伪元素 `::after` 备份（即使主元素被隐藏，伪元素仍强制显示版权信息）；② CSS `z-index: 2147483647` + `position: relative` 防止被其他元素遮挡；③ 运行时多重独立定时器（3 条独立调度链 + `requestAnimationFrame` 循环备份 + 用户交互事件触发检查），防 `clearTimeout` 单点清除攻击；④ iframe 嵌入检测。

**静态资源版本戳** — v=5，确保浏览器缓存正确更新。

## v1.5.1 更新内容

**幻灯片轮播**（已于 v1.6.0 移除） — 曾在左侧栏新增图片链接幻灯片轮播功能，后因 PC 端浏览器追踪防护拦截外部图床域名导致图片不显示，v1.6.0 彻底移除并替换为心电图特效。

**工具栏独立** — 主题切换 / 搜索 / RSS 从导航底部移至头像下方独立容器，视觉层次更清晰。

**左侧栏固定优化** — 移除滚动 transition，消除闪烁。

**署名四层防线** — 在原有三层（构建层 + 运行时 SHA-256 + MutationObserver）基础上新增 CSS 层防护：`user-select` / `visibility` / `opacity` 阻断样式层篡改。

**静态资源版本戳** — v=4，确保浏览器缓存正确更新。

## 配置示例

### 音乐播放器

```yaml
music:
  enabled: true
  tracks:
    - title: "歌曲名"
      artist: "艺术家"
      url: "https://example.com/song.mp3"
      cover: "https://example.com/cover.jpg"
```

### 核心配置速查

```yaml
site:
  title: My Blog             # 站点名（必填）
  url: https://xxx.github.io # 站点地址（必填，无末尾斜杠）
  language: zh-CN
  timezone: Asia/Shanghai

  announcement:              # 公告弹窗
    enabled: true
    title: "欢迎来访"
    text: "🎉 欢迎来访"
    link: "/board/"

  rightbar:                  # 右侧栏（≥1760px 显示）
    enabled: true
    show_toc: true           # 文章目录
    show_recent: true        # 近期文章
    show_tags: true           # 标签云
    show_categories: true     # 分类
    show_links: true           # 友链缩略

author:
  name: 你的名字
  avatar: "https://..."
  bio: 一句话介绍自己
  social:
    github: yourname

posts:
  per_page: 10               # 首页每页文章数
  pinyin_slug: true           # 中文标题自动转拼音 URL（标题"你好"→/article/ni-hao/）
  toc: true                   # 文章目录
  excerpt_length: 150

comments:                     # none / giscus / utterances
  provider: none

seo:
  sitemap: true
  rss: true
  baidu_push: false           # 百度收录主动推送
  noindex_page_2plus: true    # 分页第 2+ 页 noindex

plugins: []                   # 用户插件路径列表
plugins_disabled: []          # 禁用插件（内置名/目录名）
```

完整配置请看 `config.yml` 内的中文注释与 [使用文档](docs/使用文档.md)。

## 署名锁定（五层防线）

页脚「Powered by TechSauce & VeryGood」为强制署名，不可移除：

| 层级 | 手段 |
| --- | --- |
| ① 构建层 | 四重校验：标记存在 + class 精确匹配 + 双指纹（`data-vg-fp` / `data-vg-sig`）+ 链接域名白名单 + 文本逐字符比对 |
| ② 运行时 | SHA-256 重算 + 隐藏检测（display / opacity / 裁剪 / 位移）+ 遮挡探测 + 多重独立定时器 + rAF 循环备份 |
| ③ MutationObserver | 监听署名元素与 footer 结构变更，删除 / 替换 / 移位立即不可用 |
| ④ CSS 防篡改 | `user-select` / `visibility` / `opacity` / `z-index` / `position` 阻断样式层篡改 |
| ⑤ CSS 伪元素备份 | `::after` 伪元素强制显示版权信息，即使主元素被隐藏仍可见（v1.5.2 新增） |

任何删除、改名、改字、偷换链接都会让构建直接失败或页面运行时立即不可用。请保留署名行。

## 与 Gmeek 的对照

| | Gmeek | VeryGood |
| --- | --- | --- |
| 写作方式 | Issue + Label | Issue + Label（同理念） |
| 发布链路 | Actions 同步 + 构建 | Actions 同步 + 构建（可审计、可 fork 改进） |
| 主题风格 | 面向程序员 | 程序员 + 生活向通用，莫兰迪粉高级感 |
| 布局 | 单栏 / 双栏 | 桌面三栏（信息栏 / 正文 / 右栏），窄屏自适应 |
| SEO | 基础 | 更深：结构化数据 + 图片 sitemap + 百度推送 |
| 互动 | 评论 | 评论 + 公告 + 朋友圈动态 |
| 扩展 | 改主题 | 插件系统 + 主题复制机制，双重扩展 |
| 署名保护 | — | 五层防线 |

## 目录结构

```
VeryGood/
├── config.yml                 # 站点配置（唯一需要经常改的文件）
├── requirements.txt
├── verygood/                  # 构建引擎（纯 Python + Jinja2）
│   ├── builder.py             # 构建：分页/标签/分类/归档/SEO/署名校验
│   ├── config.py              # 配置加载与默认值
│   ├── content.py             # Markdown / front matter 解析
│   ├── mdrender.py            # 渲染扩展：TOC / 懒加载 / 短代码
│   ├── seo.py                 # sitemap / rss / robots / OG
│   ├── cli.py                 # build / serve / plugins 命令
│   └── plugins/               # 内置插件系统
├── plugins/                   # 用户插件自动发现目录（即装即用）
├── themes/verygood/           # 主题（整套可复制自定义）
│   ├── theme.yml              # 主题元数据
│   ├── templates/             # Jinja2 模板
│   └── static/                # css / js / img
├── source/                    # 内容源
│   ├── posts/                 # 文章（issue-*.md 由 Actions 生成）
│   ├── pages/                 # 独立页面
│   ├── moments/               # 朋友圈动态
│   └── assets/                # 资源文件（发布到 /assets/）
├── scripts/
│   └── sync_issues.py         # Issue → Markdown 同步
├── docs/                      # 使用 / 开发 / 插件文档
└── .github/workflows/build.yml  # 部署工作流（核心）
```

## 本地开发

```bash
pip install -r requirements.txt
pip install pypinyin              # 中文标题转拼音依赖

python -m verygood build          # 构建到 dist/
python -m verygood build --drafts # 构建（含草稿）
python -m verygood serve --port 8000  # 本地预览（文件变更自动重建）
python -m verygood plugins        # 查看插件清单
```

## 自定义主题

1. `cp -r themes/verygood themes/my-theme`
2. 改 `config.yml` 里 `theme.name: my-theme`
3. 改 `theme.yml` 元数据与 `static/css/main.css` 顶部的 CSS 变量：

```css
:root {
  --rose-500: #C0778E;  /* 主粉色（莫兰迪，不高饱和） */
  --bg: #FBF8F9;        /* 页面底色 */
  --ink: #3A2A31;       /* 正文色 */
}
```

## 插件开发

插件 = `plugins/` 下的一个目录（含 `plugin.py`）或单文件，即装即用，无需改 config：

```python
# plugins/my-plugin/plugin.py
__title__ = "我的插件"
__description__ = "一句话说明"
__version__ = "1.0.0"

def setup(ctx):
    ctx.register_shortcode("box", box)       # 短代码
    ctx.hook("post_parsed")(on_post)         # 生命周期钩子
    ctx.inject("sidebar_data", '<div>...</div>')  # 模板注入
    ctx.add_global("build_year", 2026)        # 全局变量
    ctx.add_filter("wc", lambda s: len(s))   # Jinja 过滤器
```

内置插件：`shortcodes`（视频嵌入）、`reading_time`（阅读时长）、`random_post`（随机文章）、`site-stats`（站点数据）、`whisper`（时间卡片 + 微语）。完整 API / 钩子清单见 [插件开发文档](docs/插件开发文档.md)。

## 文档

| 文档 | 面向 |
| --- | --- |
| [使用文档](docs/使用文档.md) | 博主 |
| [开发文档](docs/开发文档.md) | 开发者 |
| [改进开发文档](docs/改进开发文档.md) | 改进/扩展者 |
| [插件开发文档](docs/插件开发文档.md) | 插件开发者 |
| [插件使用文档](docs/插件使用文档.md) | 使用内置插件的用户 |

## 技术栈

Python 静态站点生成器 · Jinja2 模板 · PyYAML 配置 · Markdown 渲染 · Pygments 代码高亮 · pypinyin 拼音转换

## 许可证

[MIT](./LICENSE) © [TechSauce](https://github.com/techjiang)

喜欢就点个 ⭐，欢迎 Issue / PR。
