#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VeryGood · Issue 同步脚本（Gmeek 式写作的核心）
==================================================
用法（在 GitHub Actions 中运行）：
    python scripts/sync_issues.py

功能：
  0. 自动确保 Article / Draft / Page / Moment 四个发布标签存在于仓库
     （不存在则自动创建，幂等；只读权限下跳过、不阻塞构建）。
  5. 仓库一个 Issue 都没有时（首次部署），自动创建一条「欢迎引导 Issue」，
     手把手教会站长用 Issue 写文章（可 issues.welcome_issue: false 关闭）。
  1. 用 gh CLI 拉取仓库全部 Issue（open + closed）。
  2. 打上「发布标签」（默认 Article，可在 config.yml issues.publish_label 修改）
     的 Issue → 生成 source/posts/issue-{编号}.md（含 front matter）。
  3. 打上「草稿标签」（默认 Draft）→ 生成草稿（本地构建时可见，线上不可见）。
  4. 打上「页面标签」（默认 Page）→ 生成 source/pages/issue-{编号}.md 独立页面。
  5. 打上「动态标签」（默认 Moment）→ 生成 source/moments/issue-{编号}.md
     朋友圈动态（/board/ 时间线）。
  6. Issue 被关闭/删除 → 删除对应 md 文件（关闭即下线对应内容）。
  7. 其余 Label 自动成为文章的 tags；形如「分类:xx」的 Label 成为 category。

作者互斥约定：Article / Draft / Page / Moment 四类标签互斥使用，
同时打多个时按 Page > Moment > Draft > Article 的优先级取其一。

依赖：gh CLI（GitHub Actions 内置）、PyYAML。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# fallback 默认值（与 config.yml 保持一致）
DEFAULTS = {
    "publish_label": "Article",
    "draft_label": "Draft",
    "page_label": "Page",
    "moment_label": "Moment",
    "slug_prefix": "issue",
    "welcome_issue": True,
}

CATEGORY_PREFIXES = ("分类:", "分类：", "category:", "Category:")


def log(msg: str):
    print(msg, flush=True)


def load_issues_cfg() -> dict:
    cfg_path = ROOT / "config.yml"
    if not cfg_path.exists():
        log(f"[sync] 未找到 config.yml，使用默认配置: {DEFAULTS}")
        return dict(DEFAULTS)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    issues = dict(DEFAULTS)
    issues.update(cfg.get("issues") or {})
    return issues


def gh(*args: str, fields: str | None = None) -> list[dict]:
    """调用 gh CLI 并解析 JSON 输出。

    fields: 自定义 --json 字段列表（逗号分隔），默认使用 Issue 常用字段；
    标签 / 其他实体没有 number/body 等字段，必须显式传（如 "name"）。
    支持环境变量 VERYGOOD_GH 覆盖可执行命令（默认 "gh"），
    便于测试或使用自定义 gh 路径。
    """
    exe_cmd = shlex.split(os.environ.get("VERYGOOD_GH", "gh"))
    fields = fields or "number,title,state,body,createdAt,updatedAt,labels,url"
    cmd = exe_cmd + [*args, "--json", fields]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "[]")


def gh_raw(*args: str) -> str:
    """调用 gh CLI 的写操作/非 JSON 命令（label create / issue create 等）。"""
    exe_cmd = shlex.split(os.environ.get("VERYGOOD_GH", "gh"))
    proc = subprocess.run(
        exe_cmd + list(args),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc.stdout.strip()


def to_local(dt_iso: str, tz_name: str) -> str:
    """ISO 时间 → 站点时区的 '%Y-%m-%d %H:%M:%S'。"""
    try:
        dt = _dt.datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        tz = _dt.timezone(_dt.timedelta(hours=8)) if not tz_name else None
        if tz_name:
            import zoneinfo

            tz = zoneinfo.ZoneInfo(tz_name)
        local = dt.astimezone(tz)
        return local.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt_iso[:10] + " 00:00:00"


def sanitize_tag(label: str) -> str:
    t = label.strip()
    t = re.sub(r"\s+", "-", t)
    return t


def classify_labels(labels: list[str], cfg: dict) -> tuple[str, list[str], bool, bool, bool]:
    """返回 (category, tags, is_draft, is_page, is_moment)。"""
    publish = cfg["publish_label"]
    draft = cfg["draft_label"]
    page = cfg["page_label"]
    moment = cfg["moment_label"]
    category = ""
    tags: list[str] = []
    is_draft = is_page = is_moment = False
    seen = set()
    for raw in labels:
        label = raw.strip()
        if label == publish:
            continue
        if label == draft:
            is_draft = True
            continue
        if label == page:
            is_page = True
            continue
        if label == moment:
            is_moment = True
            continue
        matched = False
        for pfx in CATEGORY_PREFIXES:
            if label.startswith(pfx):
                category = sanitize_tag(label[len(pfx):])
                matched = True
                break
        if matched or not label:
            continue
        t = sanitize_tag(label)
        if t and t not in seen:
            seen.add(t)
            tags.append(t)
    return category or "", tags, is_draft, is_page, is_moment


def fm_value(text: str) -> str:
    """front matter 单行安全转义。"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    if any(ch in text for ch in ":,[]{}#&*!|>%@`"):  # yaml 特殊字符 → 加引号
        return '"' + text + '"'
    return text


def extract_front_matter(body: str) -> tuple[dict, str]:
    """从 Issue 正文顶部提取用户 front matter（用于封面等指令）。

    格式（写在 Issue 正文最开头）：
        ---
        cover: https://example.com/cover.png
        cover_alt: 封面描述
        summary: 自定义摘要
        ---
    返回 (fm, 剥离指令后的正文)。没有指令块时返回 ({}, body)。
    """
    stripped = body.lstrip("\ufeff\r\n")
    if not stripped.startswith("---"):
        return {}, body
    end = stripped.find("\n---", 3)
    if end < 0:
        return {}, body
    block = stripped[3:end].strip()
    rest = stripped[end + 4:].lstrip("\r\n")
    try:
        fm = yaml.safe_load(block) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        return {}, body
    # 只保留构建器认识的字段，其余忽略
    # v1.4.6: 新增 path / dir / type 支持，使自定义路径页面和特殊类型页面也能 Issue 化
    allowed = {"cover", "cover_alt", "slug", "summary", "excerpt", "path", "dir", "type"}
    fm = {k: v for k, v in fm.items() if k in allowed and v not in (None, "")}
    return fm, rest


def render_front_matter(title: str, tags: list[str], category: str,
                        date: str, updated: str, issue: int, draft: bool,
                        extra: dict | None = None) -> str:
    lines = ["---"]
    lines.append(f"title: {fm_value(title)}")
    lines.append(f"date: {date}")
    lines.append(f"updated: {updated}")
    lines.append(f"issue: {issue}")
    lines.append(f"excerpt: {fm_value(extra.get('excerpt', '')) if extra else ''}")
    if extra and extra.get("cover"):
        lines.append(f"cover: {fm_value(extra['cover'])}")
    if extra and extra.get("cover_alt"):
        lines.append(f"cover_alt: {fm_value(extra['cover_alt'])}")
    if extra and extra.get("slug"):
        lines.append(f"slug: {fm_value(extra['slug'])}")
    # v1.4.6: 支持自定义路径与特殊页面类型（从 Issue 正文 front matter 指令传入）
    if extra and extra.get("path"):
        lines.append(f"path: {fm_value(extra['path'])}")
    if extra and extra.get("dir"):
        lines.append(f"dir: {fm_value(extra['dir'])}")
    if extra and extra.get("type"):
        lines.append(f"type: {fm_value(extra['type'])}")
    if category:
        lines.append(f"category: {fm_value(category)}")
    if tags:
        lines.append("tags:")
        for t in tags:
            lines.append(f"  - {fm_value(t)}")
    lines.append(f"draft: {str(draft).lower()}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_moment_front_matter(date: str, updated: str, issue: int) -> str:
    """朋友圈动态的 front matter（不含标签/分类/草稿语义）。"""
    return (
        "---\n"
        f"title: 动态 #{issue}\n"
        f"date: {date}\n"
        f"updated: {updated}\n"
        f"issue: {issue}\n"
        "draft: false\n"
        "---\n"
    )


def gh_list_issues(cfg: dict) -> list[dict]:
    """拉取全部 Issue（open + closed）。

    注意：gh issue list 内部自动分页、不接受 --page 参数；
    用大 --limit 一次性取全（gh 会不断翻页直到取满或取完）。
    """
    return gh("issue", "list", "--state", "all", "--limit", "100000")


# 发布标签的名称 / 颜色 / 说明（自动创建时使用；颜色统一莫兰迪粉系）
_LABEL_META = {
    "publish_label": ("C0778E", "带此标签的 Issue 发布为博客文章"),
    "draft_label": ("9E9E9E", "草稿：仅本地预览可见，不上线"),
    "page_label": ("4A90D9", "独立页面：生成 /页面名/ 独立页"),
    "moment_label": ("E68A5E", "动态：同步到 /board/ 朋友圈时间线"),
}


def ensure_labels(cfg: dict) -> None:
    """确保四个发布标签存在于仓库（不存在则自动创建），幂等。

    标签是 Gmeek 式写作的「开关」：没有标签用户就无法按玩法发文章，
    这是「Issue 玩法不可用」最常见的根因。只读权限（如 `issues: read`）
    下创建会失败，仅告警不中断（构建仍可用）。
    """
    try:
        existing = gh("label", "list", fields="name,color")
    except RuntimeError as e:
        log(f"[sync] 无法读取标签列表（跳过自动建标签）：{e}")
        return
    have = {l.get("name") for l in existing}
    for key, (color, desc) in _LABEL_META.items():
        name = cfg[key]
        if name in have:
            continue
        try:
            gh_raw("label", "create", name, "--color", color, "--description", desc)
            log(f"[sync] 已自动创建标签「{name}」（颜色 #{color}）")
        except RuntimeError as e:
            # 高概率是权限不足（issues: read），也可能是并发竞争，均不致命
            log(f"[sync] 自动创建标签「{name}」失败（不影响构建）：{e}")


_WELCOME_TITLE = "👋 欢迎使用 VeryGood —— 用 Issue 写博客"

_WELCOME_BODY = """欢迎！这个仓库的博客正在通过 **GitHub Issues** 驱动：\n\n## ✍️ 发布一篇文章\n\n1. 点右上角 **New issue**，标题写文章标题，正文写 Markdown 内容；\n2. 给这个 Issue 打上标签 **`Article`**（站点第一次部署时已自动创建好这个标签）；\n3. 等 GitHub Actions 跑完，文章就自动发布到博客了 🎉\n\n## 📌 更多玩法\n\n| 标签 | 作用 |\n| --- | --- |\n| **Article** | 发布为博客文章 |\n| **Draft** | 草稿，只有本地构建可见，不上线 |\n| **Page** | 独立页面（可自定义路径） |\n| **Moment** | 同步到 `/board/` 朋友圈动态 |\n| `分类:XX` | 给文章设置分类（中文冒号或英文冒号均可） |\n| 其他任意标签 | 自动变成文章的 tag |\n\n> 关闭 Issue = 下线对应内容；再次打开 = 重新上线。\n\n本引导 Issue 可随时关闭或编辑，不会影响线上博客。\n想了解全部玩法，请看仓库 README：**Use Issue to write → 用 Issue 写博客**。\n"""


def ensure_welcome_issue(cfg: dict, items: list[dict]) -> None:
    """仓库一个 Issue 都没有时，自动创建一条引导 Issue（幂等、可关闭）。"""
    if not cfg.get("welcome_issue", True):
        return
    if items:
        return
    try:
        gh_raw("issue", "create", "--title", _WELCOME_TITLE, "--body", _WELCOME_BODY)
        log("[sync] 仓库暂无 Issue：已自动创建引导 Issue（用 Issue 写博客的玩法说明）")
    except RuntimeError as e:
        log(f"[sync] 自动创建引导 Issue 失败（不影响构建，可用 issues.welcome_issue: false 关闭）：{e}")


def is_synced_file(path: Path) -> bool:
    """判断文件是否为 sync 生成（front matter 含 `issue: 编号` 字段）。

    手工放在 source/posts 下的文章（如示例文章）没有该字段，属于
    作者直接维护的源文件——它们不参与 Issue 生命周期，sync 绝不删除/覆盖。
    """
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:600]
    except OSError:
        return False
    return bool(re.search(r"(?m)^issue:\s*\d+", head))


def unlink_if_synced(path: Path) -> None:
    """仅当文件确实由 Issue 同步生成时才删除（手工源文件一律保留）。"""
    try:
        if path.exists() and is_synced_file(path):
            path.unlink()
    except OSError:
        pass


def target_exists_manual(path: Path) -> bool:
    """目标文件已存在、且不是 sync 生成的（即作者手工维护）→ 不覆盖不删除。"""
    return path.exists() and not is_synced_file(path)


def main() -> int:
    cfg = load_issues_cfg()
    tz_name = ""
    cfg_path = ROOT / "config.yml"
    if cfg_path.exists():
        try:
            tz_name = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("site", {}).get("timezone", "")
        except Exception:
            pass

    log(f"[sync] 拉取仓库 Issue（发布: {cfg['publish_label']} / 草稿: {cfg['draft_label']} / 页面: {cfg['page_label']} / 动态: {cfg['moment_label']}）")
    ensure_labels(cfg)
    items = gh_list_issues(cfg)
    if not items:
        # 仓库暂无任何 Issue：为「用 Issue 写博客」的玩法创建一条引导 Issue，
        # 若创建失败或用户关闭 welcome_issue 则跳过同步并保留现有内容。
        ensure_welcome_issue(cfg, items)
        items = gh_list_issues(cfg)
        if not items:
            log("[sync] 仓库暂无 Issue，跳过同步（保留现有内容）")
            return 0

    posts_dir = ROOT / "source" / "posts"
    pages_dir = ROOT / "source" / "pages"
    moments_dir = ROOT / "source" / "moments"
    posts_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    moments_dir.mkdir(parents=True, exist_ok=True)

    existing_posts = {p for p in posts_dir.glob(f"{cfg['slug_prefix']}-*.md")}
    existing_pages = {p for p in pages_dir.glob(f"{cfg['slug_prefix']}-*.md")}
    existing_moments = {p for p in moments_dir.glob(f"{cfg['slug_prefix']}-*.md")}

    written_posts: set[str] = set()
    written_pages: set[str] = set()
    written_moments: set[str] = set()

    for item in items:
        number = int(item["number"])
        file_post = posts_dir / f"{cfg['slug_prefix']}-{number}.md"
        file_page = pages_dir / f"{cfg['slug_prefix']}-{number}.md"
        file_moment = moments_dir / f"{cfg['slug_prefix']}-{number}.md"

        labels = [l["name"] for l in item.get("labels", [])]
        category, tags, is_draft, is_page, is_moment = classify_labels(labels, cfg)
        state = item.get("state", "open").lower()

        # 非开放 Issue（已关闭）或完全没有标签 → 删除对应文件 = 下线
        # 仅删除由 sync 生成的文件；手工创作的源文件不受 Issue 生命周期影响
        if state != "open" or (not labels):
            unlink_if_synced(file_post)
            unlink_if_synced(file_page)
            unlink_if_synced(file_moment)
            continue

        # 发布类别互斥时取其一：Page > Moment > Draft > Article
        if is_page:
            kind = "page"
        elif is_moment:
            kind = "moment"
        else:
            publish = cfg["publish_label"]
            if is_draft:
                kind = "draft"
            elif publish in labels:
                kind = "post"
            else:
                # 普通 open Issue（仅讨论类标签）不参与发布
                continue

        title = (item.get("title") or f"issue {number}").strip()
        body = (item.get("body") or "").strip()
        if not body and kind != "page":
            body = f"来自 GitHub Issue #{number} 的正文，暂无内容。编辑 Issue 即可更新。"
        date_ = to_local(item["createdAt"], tz_name)
        updated = to_local(item["updatedAt"], tz_name)

        if kind == "moment":
            if target_exists_manual(file_moment):
                log(f"[sync] 跳过动态 #{number}：{file_moment.name} 为手工文件，不会被 Issue 覆盖")
                continue
            fm = render_moment_front_matter(date_, updated, number)
            target = file_moment
            target.write_text(fm + body + "\n", encoding="utf-8")
            unlink_if_synced(file_post)
            unlink_if_synced(file_page)
            written_moments.add(str(target.name))
            log(f"[sync] 动态 #{number} <- {title!r}")
            continue

        # v1.1.7：正文顶部 front matter 指令（封面 / 摘要 / slug）
        user_fm, body_rest = extract_front_matter(body)
        fm = render_front_matter(
            title=title,
            tags=tags,
            category=category,
            date=date_,
            updated=updated,
            issue=number,
            draft=kind == "draft",
            extra=user_fm,
        )
        target = file_page if kind == "page" else file_post
        peer = file_post if kind == "page" else file_page  # 同 Issue 的另一类别文件
        if target_exists_manual(target):
            log(f"[sync] 跳过写入 {target.name}：该文件为手工维护，不会被 Issue 覆盖（如需接管请删除文件后重跑）")
            unlink_if_synced(file_moment)
            unlink_if_synced(peer)
            continue
        target.write_text(fm + body_rest + "\n", encoding="utf-8")
        unlink_if_synced(file_moment)
        unlink_if_synced(peer)
        if kind == "page":
            written_pages.add(str(target.name))
        else:
            written_posts.add(str(target.name))
        log(f"[sync] {'页面' if kind == 'page' else ('草稿' if kind == 'draft' else '文章')} #{number} <- {title!r} (tags={tags})")

    # 清理：已被关闭/删除的 Issue 残留（仅清理 sync 生成的文件，手工源文件保留）
    for f in sorted(existing_posts, key=lambda p: p.name):
        if f.name not in written_posts:
            unlink_if_synced(f)
            if not f.exists():
                log(f"[sync] 移除已删除的文章文件 {f.name}")
    for f in sorted(existing_pages, key=lambda p: p.name):
        if f.name not in written_pages:
            unlink_if_synced(f)
            if not f.exists():
                log(f"[sync] 移除已删除的页面文件 {f.name}")
    for f in sorted(existing_moments, key=lambda p: p.name):
        if f.name not in written_moments:
            unlink_if_synced(f)
            if not f.exists():
                log(f"[sync] 移除已删除的动态文件 {f.name}")

    log(f"[sync] 完成：文章 {len(written_posts)} 篇，页面 {len(written_pages)} 个，动态 {len(written_moments)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())