#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VeryGood · Issue 同步脚本（Gmeek 式写作的核心）
==================================================
用法（在 GitHub Actions 中运行）：
    python scripts/sync_issues.py

功能：
  1. 用 gh CLI 拉取仓库全部 Issue（open + closed）。
  2. 打上「发布标签」（默认 Article，可在 config.yml issues.publish_label 修改）
     的 Issue → 生成 source/posts/issue-{编号}.md（含 front matter）。
  3. 打上「草稿标签」（默认 Draft）→ 生成草稿（本地构建时可见，线上不可见）。
  4. 打上「页面标签」（默认 Page）→ 生成 source/pages/issue-{编号}.md 独立页面。
  5. 打上「动态标签」（默认 Moment）→ 生成 source/moments/issue-{编号}.md
     朋友圈动态（/board/ 时间线），站长/站点管理者的碎碎念与站点动态。
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


def gh(*args: str) -> list[dict]:
    """调用 gh CLI 并解析 JSON 输出。

    支持环境变量 VERYGOOD_GH 覆盖可执行命令（默认 "gh"），
    便于测试或使用自定义 gh 路径。
    """
    exe_cmd = shlex.split(os.environ.get("VERYGOOD_GH", "gh"))
    cmd = exe_cmd + [*args, "--json", "number,title,state,body,createdAt,updatedAt,labels,url"]
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


def render_front_matter(title: str, tags: list[str], category: str,
                        date: str, updated: str, issue: int, draft: bool,
                        extra: dict | None = None) -> str:
    lines = ["---"]
    lines.append(f"title: {fm_value(title)}")
    lines.append(f"date: {date}")
    lines.append(f"updated: {updated}")
    lines.append(f"issue: {issue}")
    lines.append(f"excerpt: {fm_value(extra.get('excerpt', '')) if extra else ''}")
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
    items = gh_list_issues(cfg)
    if not items:
        # 仓库暂无任何 Issue：跳过同步并保留现有内容（模板示例可正常构建上线，
        # 待首个 Issue 创建后即以 GitHub Issues 为准开始同步）。
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
        if state != "open" or (not labels):
            file_post.unlink(missing_ok=True)
            file_page.unlink(missing_ok=True)
            file_moment.unlink(missing_ok=True)
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
            fm = render_moment_front_matter(date_, updated, number)
            target = file_moment
            target.write_text(fm + body + "\n", encoding="utf-8")
            file_post.unlink(missing_ok=True)
            file_page.unlink(missing_ok=True)
            written_moments.add(str(target.name))
            log(f"[sync] 动态 #{number} <- {title!r}")
            continue

        fm = render_front_matter(
            title=title,
            tags=tags,
            category=category,
            date=date_,
            updated=updated,
            issue=number,
            draft=kind == "draft",
        )
        target = file_page if kind == "page" else file_post
        target.write_text(fm + body + "\n", encoding="utf-8")
        file_moment.unlink(missing_ok=True)
        (file_post if kind == "page" else file_page).unlink(missing_ok=True)
        if kind == "page":
            written_pages.add(str(target.name))
        else:
            written_posts.add(str(target.name))
        log(f"[sync] {'页面' if kind == 'page' else ('草稿' if kind == 'draft' else '文章')} #{number} <- {title!r} (tags={tags})")

    # 清理：已被删除/改名不存在的 issue 残留
    for f in sorted(existing_posts, key=lambda p: p.name):
        if f.name not in written_posts:
            f.unlink(missing_ok=True)
            log(f"[sync] 移除已删除的文章文件 {f.name}")
    for f in sorted(existing_pages, key=lambda p: p.name):
        if f.name not in written_pages:
            f.unlink(missing_ok=True)
            log(f"[sync] 移除已删除的页面文件 {f.name}")
    for f in sorted(existing_moments, key=lambda p: p.name):
        if f.name not in written_moments:
            f.unlink(missing_ok=True)
            log(f"[sync] 移除已删除的动态文件 {f.name}")

    log(f"[sync] 完成：文章 {len(written_posts)} 篇，页面 {len(written_pages)} 个，动态 {len(written_moments)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())