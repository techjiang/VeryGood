#!/usr/bin/env python3
"""链接可用性探测（只读、只判能否访问，不评估链接内容）。

用法（三种链接来源可混用，多个产物一次传入 → 全局按 URL 去重，同一链接只探一次）:
    python3 link_probe.py <file> [<file> ...]         # 直接给交付产物：自行取链接
    python3 link_probe.py --from <extract 输出目录> [<目录> ...]   # 读现成的 links.json
    python3 link_probe.py --url URL [URL ...]
    可选: [--max 50] [--budget-s 90] [--timeout 8] [--concurrency 10]

直传产物路径时链接从哪来：优先复用该产物 extract 目录里已有的 `links.json`（content_extract.py
跑过就有），没有则内部调 `content_extract.extract_all()` 自己解析一遍。因此**本脚本不依赖
content_extract.py 先跑完**，可与 defect_check.py / content_extract.py 在同一轮里并行发起。

判定三档（调用方据此下 verdict，不可混用）:
    ok      = 2xx/3xx（含重定向），链接此刻可访问
    dead    = 404/410、DNS 解析失败、连接被拒 —— 链接不存在或已失效
    unknown = 401/403/429/5xx、超时、SSL 异常、疑似无外网 —— 可能是鉴权/风控/环境限制，
              **不得据此判产物缺陷**

并发与预算：默认 10 并发，全部待探测链接一次性提交给线程池。单条链接内部是串行两次
尝试（HEAD → 回落 GET Range），故单条最坏耗时 ≈ 2×timeout；预算只在任务**启动前**检查，
已启动的任务会跑完，实际墙钟上限 ≈ budget + 2×timeout。默认 50 条 / 10 并发 = 5 批，
坏网络下最坏 5×16s = 80s，故 budget 默认 90s；调用方 bash timeout 应 ≥ budget + 30s。

抽样规则：URL 去重后，若超过 --max，先保证每个域名至少 1 条，再按出现顺序补足；
`sampled=true` 时未探测的链接如实回传在 `not_checked`。

无外网识别：若 ≥3 个不同域名全部以 DNS/连接层错误失败，判为 `no_egress_suspected`，
该批全部记 unknown——沙箱常态无外网，绝不能把整批链接判成 dead。

本脚本永不抛栈，一切失败收敛进 JSON。
"""
import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_extract  # noqa: E402  取链接时复用同一套抽取实现
from extractors.common import merge_links  # noqa: E402

UA = "Mozilla/5.0 (compatible; dumate-deliverable-verify/1.0)"
DEAD_CODES = {404, 410}
UNKNOWN_CODES = {401, 403, 405, 429}


def _domain(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _sample(links, max_n):
    """去重后抽样：每域名至少 1 条，再按顺序补足到 max_n。"""
    seen, uniq = set(), []
    for it in links:
        u = it.get("url")
        if u and u not in seen:
            seen.add(u)
            uniq.append(it)
    if len(uniq) <= max_n:
        return uniq, [], False
    picked, used_domains = [], set()
    for it in uniq:
        d = _domain(it["url"])
        if d not in used_domains:
            used_domains.add(d)
            picked.append(it)
        if len(picked) >= max_n:
            break
    for it in uniq:
        if len(picked) >= max_n:
            break
        if it not in picked:
            picked.append(it)
    rest = [it["url"] for it in uniq if it not in picked]
    return picked, rest, True


def _request(url, method, timeout):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    if method == "GET":
        req.add_header("Range", "bytes=0-0")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return int(getattr(resp, "status", 0) or 0), None


def probe(url, timeout):
    """HEAD 优先，被拒或不支持时回落 GET Range。返回 (status, code, detail, layer)。"""
    last = None
    for method in ("HEAD", "GET"):
        try:
            code, _ = _request(url, method, timeout)
            if 200 <= code < 400:
                return "ok", code, "", ""
            if code in DEAD_CODES:
                return "dead", code, f"HTTP {code}", "http"
            last = ("unknown", code, f"HTTP {code}", "http")
        except urllib.error.HTTPError as e:
            code = int(e.code or 0)
            if code in DEAD_CODES:
                return "dead", code, f"HTTP {code}", "http"
            if code in UNKNOWN_CODES or code >= 500:
                last = ("unknown", code, f"HTTP {code}", "http")
                if method == "HEAD":
                    continue  # 部分站点拒 HEAD，换 GET 再试
            else:
                last = ("unknown", code, f"HTTP {code}", "http")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.gaierror):
                return "dead", 0, f"DNS 解析失败: {reason}", "dns"
            if isinstance(reason, ConnectionRefusedError):
                return "dead", 0, "连接被拒", "conn"
            if isinstance(reason, (socket.timeout, TimeoutError)):
                last = ("unknown", 0, "超时", "timeout")
            elif isinstance(reason, ssl.SSLError):
                last = ("unknown", 0, f"SSL 错误: {reason}", "ssl")
            else:
                last = ("unknown", 0, f"{reason}", "conn")
        except Exception as e:
            last = ("unknown", 0, f"{e}", "other")
    return last or ("unknown", 0, "未知失败", "other")


def links_of_file(path):
    """取一个产物的链接：优先复用 extract 已落盘的 links.json，否则自己解析一遍。

    自己解析走 `content_extract.links_only()`——html 只读源码抽链接、**不触发浏览器渲染**，
    否则会与 extract 抢独占的浏览器会话。返回 (链接列表, 来源说明)。
    """
    name = Path(path).name
    cached = Path(content_extract.outdir_for(path)) / "links.json"
    if cached.exists():
        try:
            got = json.loads(cached.read_text(encoding="utf-8"))
            return [{**it, "where": _prefix_where(name, it.get("where"))} for it in got], "cached"
        except Exception:
            pass
    got = content_extract.links_only(path)
    return [{**it, "where": _prefix_where(name, it.get("where"))} for it in got], "parsed"


def _prefix_where(name, where):
    """位置标签带上产物名，多产物合并后仍能看出链接出自哪份文件。"""
    ws = where if isinstance(where, (list, tuple)) else [where]
    return [f"{name}:{w}" if w else name for w in ws] or [name]


def main():
    ap = argparse.ArgumentParser(description="Check link availability (read-only).")
    ap.add_argument("files", nargs="*", help="交付产物路径（可多个；自动取链接并全局去重）")
    ap.add_argument("--from", dest="src", nargs="*", default=[], help="content_extract.py 的输出目录或 links.json")
    ap.add_argument("--url", nargs="*", default=[], help="直接指定 URL")
    ap.add_argument("--max", type=int, default=50)
    ap.add_argument("--budget-s", type=int, default=90)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()

    groups, scanned, notes = [], [], []
    if args.url:
        groups.append([{"url": u, "where": "cli", "source": "text"} for u in args.url])
    for d in args.src:
        p = Path(d)
        f = p if p.is_file() else p / "links.json"
        try:
            groups.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            notes.append(f"读取 {f} 失败: {e}")
    for fp in args.files:
        if not os.path.exists(fp):
            notes.append(f"产物不存在，已跳过: {fp}")
            continue
        try:
            got, origin = links_of_file(fp)
        except Exception as e:
            notes.append(f"{fp} 取链接失败: {e}")
            continue
        groups.append(got)
        scanned.append({"file": fp, "links": len(got), "origin": origin})

    # 跨产物全局去重：同一 URL 只探一次，出现位置累加（带产物名）
    links = merge_links(*groups)
    if not links:
        print(json.dumps({"total": 0, "checked": 0, "sampled": False, "budget_exhausted": False,
                          "no_egress_suspected": False, "results": [], "not_checked": [],
                          "scanned": scanned, "notes": notes, "error": None}, ensure_ascii=False))
        return

    picked, rest, sampled = _sample(links, max(args.max, 1))
    deadline = time.monotonic() + max(args.budget_s, 10)
    results, skipped = [], []

    def task(it):
        if time.monotonic() > deadline:
            return None
        st, code, detail, layer = probe(it["url"], args.timeout)
        return {"url": it["url"], "status": st, "code": code, "detail": detail,
                "layer": layer, "where": it.get("where") or []}

    with ThreadPoolExecutor(max_workers=max(args.concurrency, 1)) as pool:
        for it, r in zip(picked, pool.map(task, picked)):
            if r is None:
                skipped.append(it["url"])
            else:
                results.append(r)

    # 无外网识别：≥3 个不同域名全部栽在 DNS/连接层 → 环境问题，不是链接失效
    net_fail_domains = {_domain(r["url"]) for r in results if r["layer"] in ("dns", "conn", "timeout")}
    ok_any = any(r["status"] == "ok" for r in results)
    no_egress = (not ok_any) and len(net_fail_domains) >= 3
    if no_egress:
        for r in results:
            if r["status"] == "dead" and r["layer"] in ("dns", "conn"):
                r["status"] = "unknown"
                r["detail"] += "（疑似沙箱无外网，不作为链接失效依据）"

    print(json.dumps({
        "total": len(links),
        "checked": len(results),
        "sampled": sampled,
        "budget_exhausted": bool(skipped),
        "no_egress_suspected": no_egress,
        "results": results,
        "not_checked": rest + skipped,
        "scanned": scanned,
        "notes": notes,
        "error": None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
