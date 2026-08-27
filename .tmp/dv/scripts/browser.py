#!/usr/bin/env python3
"""把交付产物渲染为逐页 JPEG 图片，供校验子代理做视觉排版审核。

用法:
    python browser.py <file> [--outdir DIR] [--dpi N] [--no-shots]

向 stdout 输出 JSON: {"images": [路径...], "count": N, "error": null|str}

临时产出位置：默认输出到 **工作目录下的 .tmp/dv-render-<文件名>-<路径hash>/**（自动创建），
路径 hash 保证不同目录下的同名产物互不覆盖；不使用系统 /tmp——沙箱内 /tmp 在工作区外，
子代理 read 渲染图片会触发目录授权；工作目录天然可读，且 .tmp 为隐藏目录，不会被交付物
扫描误收。目录内已有的 page-*.jpg/png 会在重渲染时清除，防止上次残留混入本次结果。

`--no-shots`（html）只跑导航 + 运行时探针 + innerText 导出，不截任何图：视觉排版审核
关闭时走这条路径，省掉 deck 逐页 / 视口分片这部分最耗时的串行截图。

html 渲染还会在**同一个浏览器会话**里跑一次渲染后排版几何审计（checkers/html_layout_audit.js）：
装饰线是否压穿/贴在内容框边上、脱离文档流的浮框是否压住正文行、同一段线是否被画了两遍。
结果并入 `probe.layout`（含可信度门 `trust` 与"未覆盖"原因），不新增会话、不写产物目录。

支持:
    - office (pptx/docx/xlsx): LibreOffice(soffice) → PDF → pdftoppm 逐页图
    - pdf: 直接 pdftoppm 逐页图
    - html: 经 dumate-browser-cli 驱动无头浏览器 —— 忠实还原 JS/现代 CSS(flex/grid)/
      web 字体，与用户在浏览器中所见一致；LibreOffice 的 HTML 引擎不跑 JS、不支持现代
      CSS，对 html 不可靠，故 html 不走 soffice。加载序列为 `init --mode headless` →
      `open --file <路径>` → run-code 取证 → `close`（走 CDP 通道，因为扩展通道被 Chrome
      禁止访问本地文件），这样外链 css/js 才按真实路径解析；打不开时回落 `setContent`
      文本注入，实际协议与对应判定口径回传在 `probe.protocol` / `probe.protocol_note`，
      加载期事件是否可信回传在 `probe.load_events`。普通长页面走 1280×900
      视口分片；JS 分页演示稿（deck/幻灯片）检出后逐页驱动每张可见再各截一张。

内联了 LibreOffice 在沙箱环境（AF_UNIX socket 受限）下的 LD_PRELOAD shim（编译产物放 .tmp）。
本脚本永不抛栈，失败进 JSON。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# 本 skill 的所有临时产物统一放工作目录下的 .tmp（隐藏目录）
_TMP_ROOT = Path.cwd() / ".tmp"
_SHIM_SO = _TMP_ROOT / "lo_socket_shim.so"
_MIN_SHOT_S = 20  # 剩余预算低于此值不再截新图（截图串行，避免把调用方超时耗光）

# 在 AF_UNIX 被禁的沙箱里用 socketpair 顶替 socket(AF_UNIX)，让 soffice 的
# 本地单实例监听退化为可用；转换完成后 listener close 触发 _exit(0)。
_SHIM_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

static int (*real_socket)(int, int, int);
static int (*real_socketpair)(int, int, int, int[2]);
static int (*real_listen)(int, int);
static int (*real_accept)(int, struct sockaddr *, socklen_t *);
static int (*real_close)(int);
static int (*real_read)(int, void *, size_t);

static int is_shimmed[1024];
static int peer_of[1024];
static int wake_r[1024];
static int wake_w[1024];
static int listener_fd = -1;

__attribute__((constructor))
static void init(void) {
    real_socket     = dlsym(RTLD_NEXT, "socket");
    real_socketpair = dlsym(RTLD_NEXT, "socketpair");
    real_listen     = dlsym(RTLD_NEXT, "listen");
    real_accept     = dlsym(RTLD_NEXT, "accept");
    real_close      = dlsym(RTLD_NEXT, "close");
    real_read       = dlsym(RTLD_NEXT, "read");
    for (int i = 0; i < 1024; i++) { peer_of[i] = -1; wake_r[i] = -1; wake_w[i] = -1; }
}

int socket(int domain, int type, int protocol) {
    if (domain == AF_UNIX) {
        int fd = real_socket(domain, type, protocol);
        if (fd >= 0) return fd;
        int sv[2];
        if (real_socketpair(domain, type, protocol, sv) == 0) {
            if (sv[0] >= 0 && sv[0] < 1024) {
                is_shimmed[sv[0]] = 1;
                peer_of[sv[0]]    = sv[1];
                int wp[2];
                if (pipe(wp) == 0) { wake_r[sv[0]] = wp[0]; wake_w[sv[0]] = wp[1]; }
            }
            return sv[0];
        }
        errno = EPERM;
        return -1;
    }
    return real_socket(domain, type, protocol);
}

int listen(int sockfd, int backlog) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) { listener_fd = sockfd; return 0; }
    return real_listen(sockfd, backlog);
}

int accept(int sockfd, struct sockaddr *addr, socklen_t *addrlen) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) {
        if (wake_r[sockfd] >= 0) { char buf; real_read(wake_r[sockfd], &buf, 1); }
        errno = ECONNABORTED;
        return -1;
    }
    return real_accept(sockfd, addr, addrlen);
}

int close(int fd) {
    if (fd >= 0 && fd < 1024 && is_shimmed[fd]) {
        int was_listener = (fd == listener_fd);
        is_shimmed[fd] = 0;
        if (wake_w[fd] >= 0) { char c = 0; write(wake_w[fd], &c, 1); real_close(wake_w[fd]); wake_w[fd] = -1; }
        if (wake_r[fd] >= 0) { real_close(wake_r[fd]); wake_r[fd] = -1; }
        if (peer_of[fd] >= 0) { real_close(peer_of[fd]); peer_of[fd] = -1; }
        if (was_listener) _exit(0);
    }
    return real_close(fd);
}
"""


def _needs_shim():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.close()
        return False
    except OSError:
        return True


def _ensure_shim():
    if _SHIM_SO.exists():
        return _SHIM_SO
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    src = _TMP_ROOT / "lo_socket_shim.c"
    src.write_text(_SHIM_SOURCE)
    try:
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-o", str(_SHIM_SO), str(src), "-ldl"],
            check=True, capture_output=True,
        )
    finally:
        try:
            src.unlink()
        except OSError:
            pass
    return _SHIM_SO


def soffice_env():
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    try:
        if _needs_shim():
            env["LD_PRELOAD"] = str(_ensure_shim())
    except Exception:
        pass  # shim 编译失败（如无 gcc）时退化为直接调用，由 soffice 自身报错兜底
    return env


def _to_pdf(path, outdir):
    pdf = Path(outdir) / f"{Path(path).stem}.pdf"
    r = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(path)],
        capture_output=True, text=True, env=soffice_env(),
    )
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"soffice conversion failed: {(r.stderr or r.stdout).strip()[:200]}")
    return pdf


def _pdf_to_images(pdf, outdir, dpi):
    prefix = Path(outdir) / "page"
    r = subprocess.run(
        ["pdftoppm", "-jpeg", "-r", str(dpi), str(pdf), str(prefix)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {r.stderr.strip()[:200]}")
    return sorted(str(p) for p in Path(outdir).glob("page-*.jpg"))


# 加载完成后注入的 DOM 审计 JS：一次 evaluate 收齐确定性布局/资源问题。
# 只做只读检查，返回可 JSON 序列化的对象。
_AUDIT_JS = """
() => {
  const out = { broken_images: [], horizontal_overflow: [], truncated_text: 0,
                empty_charts: 0, placeholders: [], visible_text_len: 0, visible_elements: 0 };
  const vw = document.documentElement.clientWidth;
  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    else if (el.className && typeof el.className === "string")
      s += "." + el.className.trim().split(/\\s+/).slice(0, 2).join(".");
    return s.slice(0, 80);
  };
  for (const img of document.images) {
    if (img.complete && img.naturalWidth === 0 && img.src)
      out.broken_images.push({ el: label(img), src: (img.getAttribute("src") || "").slice(0, 200) });
  }
  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 2)
    out.horizontal_overflow.push({ el: "html", overflow_px: de.scrollWidth - de.clientWidth });
  const all = document.querySelectorAll("body *");
  let visText = 0, visEls = 0;
  for (const el of all) {
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    visEls++;
    if (out.horizontal_overflow.length < 10 && r.right > vw + 8 && st.position !== "fixed")
      out.horizontal_overflow.push({ el: label(el), overflow_px: Math.round(r.right - vw) });
    if (el.children.length === 0) {
      const t = (el.textContent || "").trim();
      visText += t.length;
      if (t && st.overflow !== "visible" && st.textOverflow !== "ellipsis"
          && el.scrollWidth > el.clientWidth + 4) out.truncated_text++;
    }
    if ((el.tagName === "CANVAS" || el.tagName === "svg") && r.width > 50 && r.height > 50) {
      if (el.tagName === "CANVAS") {
        try {
          const c = el.getContext && el.getContext("2d");
          if (c) {
            const d = c.getImageData(0, 0, Math.min(el.width, 50), Math.min(el.height, 50)).data;
            if (!d.some((v, i) => i % 4 !== 3 && v !== 0)) out.empty_charts++;
          }
        } catch (e) {}
      } else if (!el.children.length) out.empty_charts++;
    }
  }
  out.visible_text_len = visText;
  out.visible_elements = visEls;
  const bodyText = document.body ? document.body.innerText : "";
  for (const pat of [/\\bxxx+\\b/i, /lorem\\s+ipsum/i, /\\bTODO\\b/, /\\[insert[^\\]]*\\]/i, /占位符/]) {
    const m = bodyText.match(pat);
    if (m) out.placeholders.push(m[0].slice(0, 50));
  }
  return out;
}
"""


# ── html 渲染：经 dumate-browser-cli 驱动无头浏览器 ──
# 沙箱 VM 内没有 chromium 二进制；浏览器能力统一由 dumate-browser-use 体系提供
# （CLI → daemon → 无头浏览器通道，BROWSER_USE_HEADLESS 默认开启）。
# 所有数据（探针 JSON / innerText / 截图 base64）都通过 run-code 的返回值经 stdout
# 回传，不落浏览器侧文件系统——浏览器进程无论在沙箱侧还是宿主侧都成立。

_CLI_CANDIDATES = ["dumate-browser-cli", os.path.expanduser("~/.local/bin/dumate-browser-cli")]

# 浏览器会话是**独占**的：CLI 的 init/open/run-code 都作用在同一个 connId 上，两个进程并发
# 驱动会互相抢——实测过一次事故：extract 与 link_probe 在同一轮并行启动，两次 init/open 交错，
# 后发者的 open 拿到未就绪的浏览器，run-code 直接 exit 1（"Browser is not open"），
# 于是 html 渲染失败、退化成源码去标签。故渲染阶段用文件锁跨进程串行。
_RENDER_LOCK = _TMP_ROOT / "dv-render.lock"
_RENDER_LOCK_WAIT_S = 180


def _acquire_render_lock(timeout=_RENDER_LOCK_WAIT_S):
    """取渲染独占锁；拿不到也不阻断（最坏退回无锁行为）。返回句柄或 None。"""
    try:
        import fcntl
    except Exception:
        return None
    try:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        f = open(_RENDER_LOCK, "w")
    except Exception:
        return None
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except Exception:
            if time.monotonic() > deadline:
                try:
                    f.close()
                except Exception:
                    pass
                return None
            time.sleep(0.3)


def _release_render_lock(f):
    if f is None:
        return
    try:
        import fcntl

        fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        f.close()
    except Exception:
        pass


def _cli_bin():
    import shutil
    for c in _CLI_CANDIDATES:
        found = shutil.which(c) if os.sep not in c else (c if os.path.exists(c) else None)
        if found:
            return found
    return None


_SESSION_SUFFIX = "-dv"


def cli_env():
    """驱动 dumate-browser-cli 时的环境。

    1. `PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS=true` —— 放开 playwright-cli 那层的
       本地文件守卫。不放开时导航到 file:// 会被拒，本地 html 只能退化成文本注入
       （base 变 about:blank、相对路径的外链 css/js 与图片全部加载失败）。该变量由
       playwright-cli 读取，CLI 的 `core/opRunner.ts: buildEnv()` 会把 `process.env` 整体
       透传，故在此设置即可生效。注意它在 daemon 启动时读取，因此必须配合下面的会话隔离，
       避免复用未带该变量启动的旧 daemon。
    2. 会话隔离：CLI 的 connId / dataDir / config.json / daemon 目录都由 SANDBOX_SESSION_ID
       派生。换个 id 既能拿到按上述变量启动的独立 daemon，也不会改写本会话共享的模式配置，
       dumate-browser-use 等既有流程不受影响（它们不设这两个变量，行为完全不变）。
    """
    env = os.environ.copy()
    env["PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS"] = "true"
    base = env.get("SANDBOX_SESSION_ID") or "default"
    if not base.endswith(_SESSION_SUFFIX):
        env["SANDBOX_SESSION_ID"] = f"{base}{_SESSION_SUFFIX}"
    return env


def _cli_run(cli, args, timeout_s=60):
    r = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout_s, env=cli_env())
    if r.returncode != 0:
        raise RuntimeError(f"dumate-browser-cli {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _run_code_json(cli, code, timeout_s=90):
    """run-code 执行 Playwright 代码并从 stdout 提取 JSON 返回值。
    代码约定 return 一个对象；stdout 可能混有 CLI 日志行与 Playwright 代码块（含花括号），
    按 ### Result 段精确提取，避免代码块花括号干扰。"""
    out = _cli_run(cli, ["run-code", code], timeout_s)
    m = re.search(r"### Result\s*\n(.*?)\n###", out, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    start, end = out.find("{"), out.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"run-code returned no JSON: {out.strip()[:200]}")
    return json.loads(out[start : end + 1])


# 导航 + 探针 + 审计 + 文本 + deck 检测，一次 run-code 完成（监听器必须在导航前挂上）。
# {AUDIT} 为 _AUDIT_JS 函数体，{DECK_DETECT} 为 _DECK_DETECT_JS 函数体，{NAV} 为导航片段
# （_NAV_GOTO / _NAV_NONE / _NAV_SETCONTENT）。三种导航协议的差别见 _html_to_images 文档。
_NAV_PROBE_CODE = """async page => {
  const probe = { console_errors: [], page_errors: [], failed_requests: [] };
  page.on('console', m => { if (m.type() === 'error' && probe.console_errors.length < 20) probe.console_errors.push(String(m.text()).slice(0, 300)); });
  page.on('pageerror', e => { if (probe.page_errors.length < 20) probe.page_errors.push(String(e).slice(0, 300)); });
  page.on('requestfailed', r => {
    if (probe.failed_requests.length < 30) probe.failed_requests.push({
      url: r.url().slice(0, 300),
      error: ((r.failure() && r.failure().errorText) || '').slice(0, 120),
      relative: !/^https?:\\/\\//.test(r.url()) || r.url().startsWith('http://127.0.0.1'),
    });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  let nav_error = null;
  {NAV}
  await page.waitForTimeout(500);
  const audit = await page.evaluate({AUDIT});
  const text = await page.evaluate(() => document.body ? document.body.innerText : '');
  let deck = { is_deck: false, count: 0 };
  try { deck = await page.evaluate({DECK_DETECT}); } catch (e) {}
  probe.audit = audit;
  probe.blank_page = (audit.visible_text_len < 20 && audit.visible_elements < 3);
  const total = await page.evaluate(() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0));
  const loc = await page.evaluate(() => String(location.href).slice(0, 300));
  const domBytes = await page.evaluate(() => document.documentElement ? document.documentElement.outerHTML.length : 0);
  return { probe: probe, text: text.slice(0, 200000), total_height: total, deck: deck,
           nav_error: nav_error, location: loc, dom_html_bytes: domBytes };
}"""

# 协议 A：真实文件导航。浏览器与本脚本共享文件系统时，相对路径资源（./x.png、外链 css/js）
# 会按真实路径解析，资源加载结论最忠实。浏览器在宿主侧时该路径不存在 → goto 抛错，回落协议 B。
_NAV_GOTO = "try { await page.goto({URL}, { waitUntil: 'networkidle', timeout: 12000 }); } catch (e) { nav_error = String(e).slice(0, 300); }"
# 协议 A'：页面已由 CLI `open --file` 导航完成（这条路径不受 playwright 层 file:// 守卫
# 影响），此处不再导航，只等页面静默后就地取证。代价：监听器挂在加载之后，拿不到加载期
# 事件（failed_requests / console_errors / page_errors），见 probe.load_events。
_NAV_NONE = "try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch (e) {}"
# 协议 B：文本注入。base 为 about:blank，相对资源必然请求失败（协议假象，见 protocol_note）。
_NAV_SETCONTENT = "await page.setContent({HTML}, { waitUntil: 'networkidle', timeout: 30000 });"

_PROTOCOL_NOTE = {
    "goto:file": (
        "页面经 CLI `init --mode headless` + `open --file <路径>` 真实加载，相对路径资源按真实"
        "路径解析：failed_requests / broken_images 中的相对条目**是真实缺陷**，可作为判定依据。"
        "若 probe.load_events=unavailable，说明监听器挂在加载之后，failed_requests / "
        "console_errors / page_errors 为空**不构成「无异常」的证据**（应按未覆盖处理）；"
        "broken_images、placeholders、overflow、layout 等 DOM 层结论不受影响，仍然可信。"
    ),
    "setContent": (
        "页面经 page.setContent 注入、base 为 about:blank（浏览器与产物不在同一文件系统，"
        "file:// 导航不可用），相对路径资源（./x.png、外链 css/js）必然请求失败："
        "failed_requests 中 relative=true 的条目与由此产生的 broken_images 属协议假象，"
        "不得据此判定产物缺陷；本地引用是否缺失以 defect_check.py 的 local_refs 为准。"
    ),
}

# 单片截图：滚动到偏移 → 稳定 → JPEG base64 回传
_SHARD_CODE = """async page => {
  await page.evaluate(y => window.scrollTo(0, y), {OFFSET});
  await page.waitForTimeout(120);
  const buf = await page.screenshot({ type: 'jpeg', quality: 85, fullPage: false });
  return { b64: buf.toString('base64') };
}"""


# ===== 渲染后排版几何审计（checkers/html_layout_audit.js）=====
# 为什么必须在浏览器里做：判据是渲染后的坐标。`li::before{top:0;border-top:2px}` 与
# `.callout{position:absolute}` 在源码里都完全合法，错的是它在真实 layout 里正好落到卡片
# 边框那一行、或正好压在正文上——纯静态分析对这类缺陷结构性不可见。
#
# 为什么单独一次 run-code、不并入 _NAV_PROBE_CODE：
#   ① 失败隔离——几何审计挂了不牵连已取到的 probe / innerText；
#   ② 避免 argv 膨胀——setContent 协议下 nav 的 argv 已含整份 HTML，再塞审计脚本会逼近 ARG_MAX。
_LAYOUT_JS_PATH = Path(__file__).resolve().parent / "checkers" / "html_layout_audit.js"
_LAYOUT_SETTLE_MS = 2500  # 落定等待预算上限：判据是坐标，布局没落定量出来就是错的
_LAYOUT_ENV_OFF = ("0", "false", "no")

# 落定：字体 → 未完成的图片 → 页面尺寸连续两次采样不变；等不到时回报 settle_warning
# 而不是静默给结论（常见于产物引用了外网字体/图片而当前环境访问不了）。
_LAYOUT_CODE = """async page => {
  const settle = await page.evaluate(async (budget) => {
    const t0 = Date.now();
    let warn = null;
    const left = () => Math.max(0, budget - (Date.now() - t0));
    try {
      if (document.fonts && document.fonts.ready)
        await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, left()))]);
    } catch (e) {}
    const pending = [...document.images].filter(im => !im.complete);
    if (pending.length) {
      await Promise.race([
        Promise.all(pending.map(im => new Promise(r => {
          im.addEventListener('load', r, { once: true });
          im.addEventListener('error', r, { once: true });
        }))),
        new Promise(r => setTimeout(r, left())),
      ]);
      if ([...document.images].some(im => !im.complete))
        warn = '部分图片在预算内未加载完成，布局可能尚未落定';
    }
    const size = () => {
      const de = document.documentElement;
      return [de.scrollWidth, de.scrollHeight, document.body ? document.body.scrollHeight : 0].join('x');
    };
    let prev = size(), stable = 0, settled = false;
    while (left() > 0) {
      await new Promise(r => setTimeout(r, 50));
      const now = size();
      if (now === prev) { if (++stable >= 2) { settled = true; break; } }
      else { stable = 0; prev = now; }
    }
    if (!settled) warn = warn || '布局在预算内未落定（页面尺寸仍在变化），几何结论可信度下降';
    return warn;
  }, {BUDGET});
  const audit = await page.evaluate({AUDIT});
  return { audit: audit, settle_warning: settle };
}"""

_LINK_CSS_RE = re.compile(r"<link\b[^>]*>", re.I)
_STYLESHEET_RE = re.compile(r"""rel\s*=\s*["']?stylesheet""", re.I)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*?(?<![\w-])src\s*=\s*["']([^"']+)["']""", re.I)
_ABS_PREFIXES = ("http://", "https://", "data:", "//", "about:", "blob:")


_ASSIGN_RE = re.compile(r"^\s*window\.__LAYOUT_AUDIT\s*=\s*", re.M)


def _layout_js():
    """把 html_layout_audit.js 变成可直接交给 page.evaluate 的箭头函数（去掉 window 赋值与尾分号）。

    只认**行首**的那处赋值：文件顶部注释里也会提到 window.__LAYOUT_AUDIT，按首次出现切会
    把整段注释当成函数体（node --check 直接报错）。
    """
    src = _LAYOUT_JS_PATH.read_text(encoding="utf-8")
    m = _ASSIGN_RE.search(src)
    if not m:
        raise RuntimeError("html_layout_audit.js 缺少 window.__LAYOUT_AUDIT 定义")
    return src[m.end():].strip().rstrip(";")


def _relative_style_refs(source):
    """页面引用的**相对路径**外部样式/脚本。setContent 协议下这些必然加载失败（base 为
    about:blank），此时量出来的坐标不代表真实排版 → 几何维度必须按未覆盖处理，否则必然误报。"""
    refs = []
    for m in _LINK_CSS_RE.finditer(source):
        tag = m.group(0)
        if not _STYLESHEET_RE.search(tag):
            continue
        href = _HREF_RE.search(tag)
        if href and not href.group(1).lower().startswith(_ABS_PREFIXES):
            refs.append(href.group(1))
    for m in _SCRIPT_SRC_RE.finditer(source):
        if not m.group(1).lower().startswith(_ABS_PREFIXES):
            refs.append(m.group(1))
    return refs[:10]


def _layout_audit(cli, protocol, source, deadline=None):
    """渲染后几何审计。返回 probe.layout 用的 dict；永不抛栈，失败即"未覆盖"。"""
    if os.environ.get("DUMATE_DELIVERABLE_LAYOUT_AUDIT", "").strip().lower() in _LAYOUT_ENV_OFF:
        return {"available": False, "trust": None,
                "unavailable_reason": "disabled (DUMATE_DELIVERABLE_LAYOUT_AUDIT=0)"}
    trust, trust_note = "ok", None
    if protocol == "setContent":
        rel = _relative_style_refs(source)
        if rel:
            return {
                "available": False,
                "trust": "unreliable",
                "unavailable_reason": (
                    "setContent 协议下相对路径的外部样式/脚本必然加载失败（"
                    + ", ".join(rel[:3])
                    + " 等），渲染坐标不代表真实排版 → 几何维度按未覆盖处理"
                ),
            }
        trust_note = "setContent 协议，但页面样式/脚本全为内联，几何仍成立"

    budget = _LAYOUT_SETTLE_MS
    if deadline is not None:
        budget = min(budget, max(500, int((deadline - time.monotonic() - 5) * 1000)))
    try:
        code = _LAYOUT_CODE.replace("{BUDGET}", str(budget)).replace("{AUDIT}", _layout_js())
        r = _run_code_json(cli, code, timeout_s=90)
    except Exception as e:
        _diag(f"layout audit failed: {str(e)[:200]}")
        return {"available": False, "trust": trust,
                "unavailable_reason": f"几何审计执行失败: {str(e)[:200]}"}
    audit = r.get("audit") or {}
    groups = audit.get("line_on_box") or []
    return {
        "available": True,
        "trust": trust,
        "trust_note": trust_note,
        # 压穿：装饰线中轴落在内容框内；贴边：中轴距框边 ≤2px（含越出量）
        "line_crosses_box": [g for g in groups if g.get("kind") == "line_crosses_box"],
        "line_flush_box_edge": [g for g in groups if g.get("kind") == "line_flush_box_edge"],
        "box_over_text": audit.get("box_over_text") or [],
        "coincident_lines": audit.get("coincident_lines") or [],
        "counts": audit.get("counts") or {},
        "truncated": bool(audit.get("truncated")),
        "settle_warning": r.get("settle_warning"),
        "unavailable_reason": None,
    }


# ===== JS 驱动的分页型 HTML（幻灯片/deck）检测与逐页捕获 =====
# 不少交付 HTML 是「一屏一页、靠脚本切页」的演示稿（reveal/swiper/自研 slide 等）：
# body overflow:hidden、页面本身不高，多张 .slide 用 absolute/transform 叠在同一位置，
# 只有 .active 一张可见，翻页全靠 JS。此时整页截图只会拿到第 1 页、视口分片也无从切起——
# 其余页永不进入视觉审核。故检出 deck 后逐页驱动可见再各截一张。全程走同一 run-code 会话
# （daemon 保活页面：setContent 与 detect 阶段打的 data-dv-slide 标记在多次 run-code 间持续）。
_DECK_MAX_SLIDES = 60     # 逐页捕获上限，避免异常页面把渲染拖垮（下游还有抽样兜底）
_DECK_SETTLE_MS = 650     # 切页后等待：覆盖入场动画(slideUp≈0.5s)与背景过渡

# 在浏览器里判定是否 deck：页面不高(未走滚动) + 同一父节点下 ≥2 张几乎铺满且相互堆叠
# （同位置）的候选页。命中则给每张打 data-dv-slide 序号，返回页数与截图裁剪框（deck 外框）。
# 判非 deck 时同样回传诊断字段（scroll_h/vh/candidates/best/stacked/reason）：deck 检测是启发式，
# 漏判会导致"只渲染了第 1 屏、后面几十页从未被核验"却毫无提示，诊断字段用于把这种漏审显式化。
_DECK_DETECT_JS = r"""() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const scrollH = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const diag = { scroll_h: scrollH, vh: vh, candidates: 0, best: 0, stacked: 0 };
  if (scrollH > vh * 1.5)
    return Object.assign({ is_deck: false, count: 0, reason: 'page is scrollable (scroll_h > 1.5*vh)' }, diag);
  const SEL = ['.slide', '[class*="slide"]', 'section.slide', '.reveal .slides > section',
    '.swiper-slide', '.carousel-item', '.carousel .item', '.page', '.step', '[data-bg]', '[data-background]'];
  const seen = new Set(), els = [];
  for (const s of SEL) {
    let list; try { list = document.querySelectorAll(s); } catch (e) { continue; }
    for (const el of list) if (!seen.has(el)) { seen.add(el); els.push(el); }
  }
  const cand = els.filter(el => {
    const r = el.getBoundingClientRect();
    return r.width >= vw * 0.5 && r.height >= vh * 0.5;
  });
  diag.candidates = cand.length;
  const byParent = new Map();
  for (const el of cand) {
    const p = el.parentElement; if (!p) continue;
    (byParent.get(p) || byParent.set(p, []).get(p)).push(el);
  }
  let best = [];
  for (const arr of byParent.values()) if (arr.length > best.length) best = arr;
  diag.best = best.length;
  if (best.length < 2)
    return Object.assign({ is_deck: false, count: 0, reason: 'fewer than 2 full-size siblings' }, diag);
  const f = best[0].getBoundingClientRect();
  const stacked = best.filter(el => {
    const r = el.getBoundingClientRect();
    return Math.abs(r.top - f.top) < vh * 0.3 && Math.abs(r.left - f.left) < vw * 0.3;
  });
  diag.stacked = stacked.length;
  if (stacked.length < 2)
    return Object.assign({ is_deck: false, count: 0, reason: 'siblings are not stacked at same position' }, diag);
  stacked.forEach((el, i) => el.setAttribute('data-dv-slide', String(i)));
  const frame = stacked[0].offsetParent || stacked[0].parentElement || stacked[0];
  const fr = frame.getBoundingClientRect();
  let x = Math.max(0, Math.floor(fr.left)), y = Math.max(0, Math.floor(fr.top));
  let w = Math.min(vw - x, Math.ceil(fr.width)), h = Math.min(vh - y, Math.ceil(fr.height));
  if (w <= 0 || h <= 0) { x = 0; y = 0; w = vw; h = vh; }
  return Object.assign({ is_deck: true, count: stacked.length, reason: null,
                         clip: { x, y, width: w, height: h } }, diag);
}"""

# 把第 i 张页强制显示、其余隐藏（覆盖 opacity/transform/visibility/display，加 !important），
# 并尽力还原该页背景（把 data-bg 写到 deck 内的背景层）。不依赖具体框架翻页 API，纯样式覆盖，
# 对自研/第三方 deck 都通用。
_DECK_SHOW_JS = r"""(i) => {
  const slides = document.querySelectorAll('[data-dv-slide]');
  slides.forEach(el => {
    const on = String(el.getAttribute('data-dv-slide')) === String(i);
    if (on) {
      el.style.setProperty('opacity', '1', 'important');
      el.style.setProperty('visibility', 'visible', 'important');
      el.style.setProperty('transform', 'none', 'important');
      el.style.setProperty('pointer-events', 'auto', 'important');
      el.style.setProperty('z-index', '9999', 'important');
      if (getComputedStyle(el).display === 'none') el.style.setProperty('display', 'block', 'important');
      el.classList.add('active'); el.classList.remove('prev');
      const bg = el.getAttribute('data-bg') || el.getAttribute('data-background') || el.getAttribute('data-background-color');
      if (bg) {
        const frame = el.offsetParent || el.parentElement;
        if (frame) for (const sib of frame.querySelectorAll('*')) {
          if (/bg|background/i.test(sib.getAttribute('class') || '') && sib.getBoundingClientRect().width > 0)
            sib.style.setProperty('background', bg, 'important');
        }
      }
    } else {
      el.style.setProperty('opacity', '0', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('pointer-events', 'none', 'important');
      el.style.setProperty('z-index', '0', 'important');
      el.classList.remove('active');
    }
  });
}"""

# deck 逐页截图：显示第 {SLIDE} 页 → 稳定 → 按 deck 外框 clip 截图 → JPEG base64 回传。
# {SHOW} 为 _DECK_SHOW_JS 函数体，{CLIP} 为裁剪框 JSON（或 null）。
_DECK_SHOT_CODE = """async page => {
  await page.evaluate({SHOW}, {SLIDE});
  await page.waitForTimeout({SETTLE});
  const clip = {CLIP};
  const opts = { type: 'jpeg', quality: 90, fullPage: false };
  if (clip && clip.width > 0 && clip.height > 0) opts.clip = clip;
  const buf = await page.screenshot(opts);
  return { b64: buf.toString('base64') };
}"""


def _capture_deck_slides(cli, outdir, deck, deadline=None):
    """deck 逐页驱动可见并各截一张（同一 run-code 会话，复用 nav 阶段设好的 data-dv-slide）。
    截图是串行的（每页一次 run-code），故受 deadline 约束：到点停止、返回已截到的页，
    绝不把调用方的整体超时耗光（超时被 SIGKILL 会连已完成的工作一起丢）。
    返回 [page-1.jpg, ...]；个别页失败跳过、全失败返回 []（调用方回退视口分片，绝不空手）。"""
    count = min(int(deck.get("count", 0)), _DECK_MAX_SLIDES)
    clip = deck.get("clip")
    clip_js = json.dumps(clip) if isinstance(clip, dict) else "null"
    show_js = _DECK_SHOW_JS.strip()
    images = []
    for i in range(count):
        if deadline is not None and (deadline - time.monotonic()) < _MIN_SHOT_S:
            break
        code = (
            _DECK_SHOT_CODE
            .replace("{SHOW}", show_js)
            .replace("{SLIDE}", str(i))
            .replace("{SETTLE}", str(_DECK_SETTLE_MS))
            .replace("{CLIP}", clip_js)
        )
        try:
            shot = _run_code_json(cli, code, timeout_s=60)
        except Exception:
            continue  # 单页失败跳过，其余页照常
        b64 = shot.get("b64")
        if not b64:
            continue
        out = Path(outdir) / f"page-{len(images) + 1}.jpg"
        out.write_bytes(base64.b64decode(b64))
        images.append(str(out))
    return images


# file:// 导航是否已被证实不可达。**只在本进程内记忆**，不落盘——
# 早先用 .tmp/dv-nav-mode.json 持久化过，结果一次无关原因的失败（浏览器会话被抢、超时）
# 就把这个工作目录后续所有运行的 goto 永久关掉，日志里表现为"从来没试过 file://"。
# 现在：仅当错误确实表明"路径在浏览器侧不存在/不可读"时，才在本次进程内不再重试。
_GOTO_UNREACHABLE = None  # None=未探测；str=不可达原因（本进程内不再试）

# 判定"路径确实不可达"的浏览器错误特征。其余错误（超时、会话异常、run-code 失败）
# 都可能是环境抖动，不据此关闭 goto。
_FILE_UNREACHABLE_MARKS = (
    "ERR_FILE_NOT_FOUND",
    "ERR_ACCESS_DENIED",
    "ERR_INVALID_URL",
    "ERR_UNKNOWN_URL_SCHEME",
    "ERR_BLOCKED_BY_CLIENT",
    "Not allowed to load local resource",
    # extension 模式下 CDP 由 Chrome 扩展代理，Chrome 默认禁止扩展把标签页导航到 file://，
    # 报 `-32000 Navigating to local URL is not allowed`。这是确定性的策略拒绝（不是抖动），
    # 同一进程内不必再对每个产物各试一次。要放开需在扩展详情里开启「允许访问文件网址」。
    "Navigating to local URL is not allowed",
)


def _diag(msg):
    """诊断日志走 stderr：会随 bash 工具输出进入会话记录，便于事后排查。"""
    print(f"[render] {msg}", file=sys.stderr)


def _unreachable_reason(nav_error, location, dom_bytes):
    """把一次 goto 失败归类：返回"路径不可达"的原因串，或 None（=原因不明/可重试）。"""
    err = str(nav_error or "")
    for mark in _FILE_UNREACHABLE_MARKS:
        if mark.lower() in err.lower():
            return mark
    if not err and location and not str(location).startswith("file:"):
        return f"navigation did not land on file:// (location={str(location)[:80]})"
    if not err and (dom_bytes or 0) <= 200:
        return f"file:// loaded but DOM nearly empty (dom_html_bytes={dom_bytes})"
    return None


def _nav_probe(cli, path, nav_mode, audit_js, deck_js, html_literal):
    """跑一次"导航 + 探针"。nav_mode: goto | none | setContent。

    `none` 用于"页面已由 CLI `open --file` 导航完成"的情况——此时不在 run-code 里再导航，
    避免 playwright 层对 file:// 的守卫把整次取证打掉；代价是监听器挂在加载之后，
    拿不到加载期事件（见 probe.load_events）。
    """
    if nav_mode == "goto":
        nav = _NAV_GOTO.replace("{URL}", json.dumps(Path(path).absolute().as_uri()))
    elif nav_mode == "none":
        nav = _NAV_NONE
    else:
        nav = _NAV_SETCONTENT
    code = (
        _NAV_PROBE_CODE
        .replace("{AUDIT}", audit_js)
        .replace("{DECK_DETECT}", deck_js)
        .replace("{NAV}", nav)
    )
    # HTML 放最后注入：其内容任意，避免其中偶含 {AUDIT}/{DECK_DETECT}/{NAV} 被误替换
    if nav_mode == "setContent":
        code = code.replace("{HTML}", html_literal)
    return _run_code_json(cli, code, timeout_s=120)


def _html_to_images(path, outdir, dpi, shots=True, deadline=None):
    """html 渲染：dumate-browser-cli 无头浏览器 + 运行时探针 + 逐页图 + 文本导出。

    - **导航协议三级回落，优先真实加载**：
      1. CLI `init --mode headless` + `open --file <绝对路径>`，再在 run-code 里对同一 URL 导航
         一次（监听器挂在导航前，加载期事件可信）。相对路径资源按真实路径解析，
         `failed_requests` / `broken_images` 是真实缺陷证据。`probe.load_events=captured`。
      1'. run-code 里的 goto 被 playwright 的 file:// 守卫拒、但 CLI 已把页面打开：不再导航，
         就地取证。DOM 层结论（白屏/占位符/裂图/溢出/几何）照样可信，但拿不到加载期事件，
         `probe.load_events=unavailable` —— 那三项为空不构成"无异常"的证据。
      2. `page.setContent(html)`——上面两条都不可用时（旧版 CLI、CDP 起不来、文件被策略
         拦住）只能把 HTML 文本注入页面。**代价**：base 为 about:blank，相对引用一律失败，
         那些 failed_requests/broken_images 是协议假象、不是产物缺陷。
      实际用了哪种写入 `probe.protocol`，判定口径写入 `probe.protocol_note`，
      **导航诊断（试没试、怎么打开的、报了什么错、落到哪个 location）写入 `probe.nav`**，
      同时打到 stderr（`[render] ...`）便于事后排查。只有当错误明确表明"路径在浏览器侧
      不存在/不可读/被策略禁止"时，才在**本进程内**不再重试；超时、会话异常等不确定原因一律重试。
    - 探针/审计/innerText/deck 检测/截图全部经 run-code 返回值回传（截图 base64），
      不依赖浏览器侧文件系统；probe 写 <outdir>/probe.json，文本写 rendered_text.txt。
    - shots=False：只跑导航 + 探针 + 文本导出，不截任何图（视觉审核已关闭时的默认路径，
      省掉 deck 逐页/视口分片这部分最耗时的工作）。
    - deck（JS 分页演示稿）：逐页驱动每张可见再各截一张，每张一"页"；检测未命中时回传
      诊断字段与 `suspect_hidden_pages`，把"可能有页从未被渲染"这件事显式化。
    - 普通长页面：1280x900 视口逐屏滚动分片，片数封顶 20，每片一"页"。
    - 收尾：`--mode headless` 建连成功时在**释放渲染锁之前**调 `close` —— 该模式下宿主会为本技能
      拉起独立 profile 的 Chrome，不关会常驻；回落裸 `init` 时不关（可能连的是用户自己的
      浏览器会话），与合入前行为一致。
    - CLI 不可用时报错降级（html 运行时证据缺失，结构与内容校验保留）。
    """
    cli = _cli_bin()
    if not cli:
        raise RuntimeError(
            "dumate-browser-cli unavailable; html rendering requires the dumate-browser-use CLI"
        )

    # 浏览器会话独占：整段 init/open/run-code 必须串行，否则并发的两个进程会互相抢会话
    lock = _acquire_render_lock()
    mode = None
    try:
        mode = _connect(cli)
        return _render_in_session(cli, path, outdir, shots, deadline)
    finally:
        if mode == "cdp":
            _close(cli)
        _release_render_lock(lock)


def render_html_batch(items, shots=False, deadline=None):
    """一次浏览器会话连续渲染多个 html：**只付一次 init/open 开销**。

    浏览器启动（init + open）实测约 3s，占单个产物渲染耗时的一半以上；且会话独占，
    并发渲染只能排队。故多个 html 产物合并进同一会话，比"并行但互斥等待"更省。
    items: [(html 绝对路径, 该产物的渲染落点 outdir)]。返回 {path: None | 错误说明}。
    """
    cli = _cli_bin()
    if not cli:
        why = "dumate-browser-cli unavailable; html rendering requires the dumate-browser-use CLI"
        return {p: why for p, _ in items}
    out = {}
    lock = _acquire_render_lock()
    mode = None
    try:
        try:
            mode = _connect(cli)
        except Exception as e:
            return {p: f"browser connect failed: {str(e)[:200]}" for p, _ in items}
        for path, outdir in items:
            try:
                _prepare_outdir(outdir)
                _render_in_session(cli, path, outdir, shots, deadline)
                out[path] = None
            except Exception as e:
                out[path] = str(e)[:300]
    finally:
        if mode == "cdp":
            _close(cli)
        _release_render_lock(lock)
    return out


def _connect(cli):
    """建连：`init --mode headless` + open 空白页。会话内只需做一次。返回实际建连模式。

    显式指定 headless 通道（= CDP 通道 + 无头窗口）：extension 模式下 CDP 经 Chrome 的扩展调试
    通道代理，而 Chrome 对扩展访问本地文件有硬性策略（`-32000 Navigating to local URL is not
    allowed`），要放开得让用户手工开「允许访问文件网址」——不能这么假设。CDP 通道没有这层限制，
    本地 html 才能走真实 file:// 加载（外链 css/js 按真实路径解析）。取证不需要可见窗口，故用
    headless 而非 cdp：宿主 Chrome 以 `--headless=new` 启动，不会在用户桌面上弹窗。
    旧版 CLI 不认 `--mode headless` 时会静默回落自动探测（可能停在 extension 而打不开本地文件），
    因此再回落一次裸 `init`（此时能否打开本地文件取决于 CLI 自身选的模式）。

    返回值只用于决定收尾是否 `close`：CDP/headless 模式下浏览器是本技能拉起的、必须关；
    回落模式可能连的是用户自己的 Chrome 会话，不能碰。
    """
    mode = "cdp"
    try:
        _cli_run(cli, ["init", "--mode", "headless"], 90)
    except Exception as e:
        _diag(f"init --mode headless 失败，回落裸 init：{str(e)[:160]}")
        _cli_run(cli, ["init"], 90)
        mode = "default"
    try:
        _cli_run(cli, ["open", "about:blank"], 45)
    except Exception:
        _cli_run(cli, ["open"], 45)  # 部分版本 open 不接受 about:blank，裸 open 仅建连
    return mode


def _open_local(cli, path):
    """用 CLI 打开本地文件：`open --file <绝对路径>`，旧版回落 `open file://<url>`。

    为什么由 CLI 侧导航而不是在 run-code 里 `page.goto(file://…)`：实测这条路径不受
    playwright 那层 file:// 守卫影响，是目前唯一能让本地 html 真实加载的入口。
    """
    try:
        _cli_run(cli, ["open", "--file", str(Path(path).absolute())], 60)
        return "open --file"
    except Exception as e:
        _diag(f"open --file 失败，回落 open file://：{str(e)[:160]}")
        _cli_run(cli, ["open", Path(path).absolute().as_uri()], 60)
        return "open file://"


def _close(cli):
    """会话收尾：`close`。best-effort —— 关不掉不影响已取到的证据。

    `--mode headless` 下宿主会为本技能拉起一个独立 profile 的 Chrome，不关就会常驻，多轮校验后
    攒一堆浏览器进程和 daemon。放在渲染锁释放之前调用，保证排队中的下一个进程从干净状态
    开始 `init`。仅 CDP 模式调用，见 `_connect` 返回值。
    """
    try:
        _cli_run(cli, ["close"], 45)
        _diag("browser closed")
    except Exception as e:
        _diag(f"close 失败（忽略）：{str(e)[:160]}")


_META_CHARSET_TAG_RE = re.compile(r"""(<meta[^>]*charset\s*=\s*["']?)([\w-]+)""", re.I)


def _read_source(path):
    """按声明编码读 html 源码。

    GBK/GB18030 的中文页硬按 utf-8 读会变成乱码——渲染出来的文字宽度全错，换行、卡片高度、
    几何坐标一并跟着错。编码探测与 html_static 共用一套实现，保证口径一致。
    """
    try:
        from checkers import html_static

        return html_static.read_html(str(path))
    except Exception:
        return Path(path).read_text(encoding="utf-8", errors="replace"), None


def _retag_charset(html):
    """setContent 注入的是**已解码的文本**，页面里残留的 charset=gbk 声明会让浏览器再按 GBK
    解释一次 → 二次乱码。注入前统一改写为 utf-8。"""
    return _META_CHARSET_TAG_RE.sub(lambda m: m.group(1) + "utf-8", html, count=1)


def _render_in_session(cli, path, outdir, shots=False, deadline=None, height=900, max_shards=20):
    """在已建连的会话里渲染一个 html：导航取证 → 落盘 → （可选）截图。"""
    # 读取 HTML 文件内容，json.dumps 转为合法 JS 字符串字面量注入 run-code（协议 B 用）
    html_content, enc_note = _read_source(path)
    if enc_note:
        _diag(f"source encoding: {enc_note}")
    html_js_literal = json.dumps(_retag_charset(html_content))
    audit_js = _AUDIT_JS.strip()
    deck_detect_js = _DECK_DETECT_JS.strip()

    global _GOTO_UNREACHABLE
    file_url = Path(path).absolute().as_uri()
    nav_diag = {
        "goto_url": file_url,
        "attempted_goto": False,
        "opened_by_cli": False,
        "opened_by": None,
        "goto_error": None,
        "goto_location": None,
        "goto_dom_html_bytes": None,
        "skip_reason": _GOTO_UNREACHABLE,
    }
    result, via, load_events = None, None, "captured"
    if _GOTO_UNREACHABLE is None:
        nav_diag["attempted_goto"] = True
        _diag(f"opening {file_url}")
        try:
            # 实测可行的序列：`init --mode headless` → `open --file <路径>`，导航由 CLI 完成
            nav_diag["opened_by"] = _open_local(cli, path)
            nav_diag["opened_by_cli"] = True
            # 再在 run-code 里对同一 URL 导航一次：监听器能挂在加载之前，从而拿到
            # requestfailed / pageerror / console 等加载期事件。
            r = _nav_probe(cli, path, "goto", audit_js, deck_detect_js, html_js_literal)
            loc, dom = r.get("location"), int(r.get("dom_html_bytes") or 0)
            landed = str(loc or "").startswith("file:") and dom > 200
            if not r.get("nav_error") and landed:
                result, via = r, "goto:file"
                _diag(f"goto OK: location={loc} dom_html_bytes={dom}")
            else:
                # run-code 里的 goto 被守卫拒了，但 CLI open 已经把页面打开了：不再导航，
                # 直接就地取证（DOM 层结论照样可信，只是拿不到加载期事件）。
                _diag(f"in-page goto rejected (nav_error={r.get('nav_error')} location={loc} dom={dom})"
                      f" → 改为就地取证（已由 CLI open 打开）")
                r2 = _nav_probe(cli, path, "none", audit_js, deck_detect_js, html_js_literal)
                loc2, dom2 = r2.get("location"), int(r2.get("dom_html_bytes") or 0)
                if str(loc2 or "").startswith("file:") and dom2 > 200:
                    result, via, load_events = r2, "goto:file", "unavailable"
                    _diag(f"probe-in-place OK: location={loc2} dom_html_bytes={dom2}（无加载期事件）")
                else:
                    nav_diag["goto_error"] = r.get("nav_error")
                    nav_diag["goto_location"] = loc2 or loc
                    nav_diag["goto_dom_html_bytes"] = dom2 or dom
                    why = _unreachable_reason(r.get("nav_error"), loc2 or loc, dom2 or dom)
                    _diag(f"goto FAILED: nav_error={r.get('nav_error')} location={loc2 or loc} "
                          f"dom={dom2 or dom} → {'路径不可达: ' + why if why else '原因不明，后续产物仍会重试'}")
                    if why:
                        _GOTO_UNREACHABLE = why  # 仅本进程内不再重试
        except Exception as e:
            msg = str(e)[:300]
            nav_diag["goto_error"] = f"open/run-code failed: {msg}"
            why = _unreachable_reason(msg, None, None)
            if why:
                _GOTO_UNREACHABLE = why
                _diag(f"open 被拒: {msg} → 路径不可达: {why}")
            else:
                _diag(f"goto ABORTED (会话/超时类错误，不关闭 goto): {msg}")
    else:
        _diag(f"skip goto (本进程内已判定不可达: {_GOTO_UNREACHABLE})")
    if result is None:
        # 已经 open 过本地文件才需要把页面切回空白，避免上一次的 file:// 页残留影响
        # setContent；没 open 过就别多付一次 CLI 往返（保持回落路径与改动前一致）。
        if nav_diag["opened_by_cli"]:
            try:
                _cli_run(cli, ["open", "about:blank"], 45)
            except Exception:
                pass
        result = _nav_probe(cli, path, "setContent", audit_js, deck_detect_js, html_js_literal)
        via = "setContent"
        _diag(f"fallback to setContent for {Path(path).name}")

    deck = result.get("deck") or {}
    probe = result.get("probe") or {}
    probe["protocol"] = via
    probe["protocol_note"] = _PROTOCOL_NOTE[via]
    # captured = 监听器挂在导航之前，加载期事件（failed_requests/console_errors/page_errors）可信；
    # unavailable = 页面由 CLI 先打开、run-code 未再导航，这三项为空不构成"无异常"的证据。
    probe["load_events"] = load_events
    probe["source_bytes"] = len(html_content)
    probe["dom_html_bytes"] = result.get("dom_html_bytes")
    # 导航诊断落盘：下次排查"为什么没走 file://"直接看这里，不必靠 run-code 次数反推
    nav_diag["skip_reason"] = nav_diag["skip_reason"] or _GOTO_UNREACHABLE
    probe["nav"] = nav_diag
    # deck 漏判会导致后续页从未被渲染/核验：页面不滚动 + 有 ≥2 个铺满候选却未判为 deck，
    # 就是典型的"疑似还有隐藏页"，显式标出来供调用方按"未覆盖"处理。
    probe["deck"] = {
        "is_deck": bool(deck.get("is_deck")),
        "count": int(deck.get("count") or 0),
        "reason": deck.get("reason"),
        "scroll_h": deck.get("scroll_h"),
        "vh": deck.get("vh"),
        "candidates": deck.get("candidates"),
        "best": deck.get("best"),
        "stacked": deck.get("stacked"),
    }
    probe["deck"]["suspect_hidden_pages"] = bool(
        not deck.get("is_deck")
        and int(deck.get("candidates") or 0) >= 2
        and (deck.get("scroll_h") or 0) <= (deck.get("vh") or 0) * 1.5
    )
    # 渲染后排版几何审计：同一会话第二次 run-code（截图之前——deck 逐页截图会改页面可见性）
    probe["layout"] = _layout_audit(cli, via, html_content, deadline)
    try:
        (Path(outdir) / "probe.json").write_text(json.dumps(probe, ensure_ascii=False), encoding="utf-8")
        (Path(outdir) / "rendered_text.txt").write_text(result.get("text") or "", encoding="utf-8")
    except Exception:
        pass

    if not shots:
        return []

    # JS 分页演示稿（deck）：整页截图/视口分片只拿得到第 1 页，改为逐页驱动可见再各截一张。
    if deck.get("is_deck") and int(deck.get("count", 0)) >= 2:
        slides = _capture_deck_slides(cli, outdir, deck, deadline)
        if slides:
            return slides
        # deck 检出但一张都没截到 → 回退普通视口分片，绝不空手

    total = int(result.get("total_height") or height)
    shards = min(max(1, -(-total // height)), max_shards)
    images = []
    for i in range(shards):
        if deadline is not None and (deadline - time.monotonic()) < _MIN_SHOT_S and images:
            break
        shot = _run_code_json(cli, _SHARD_CODE.replace("{OFFSET}", str(i * height)), timeout_s=60)
        b64 = shot.get("b64")
        if not b64:
            raise RuntimeError("shard screenshot returned no data")
        out = Path(outdir) / f"page-{i + 1}.jpg"
        out.write_bytes(base64.b64decode(b64))
        images.append(str(out))
    return images


def _prepare_outdir(outdir):
    """建目录并清除上次渲染残留，防止旧页混入本次结果（目录按产物名+路径 hash 隔离，只清 page-*）。"""
    outdir_p = Path(outdir)
    outdir_p.mkdir(parents=True, exist_ok=True)
    for old in outdir_p.glob("page-*"):
        if old.suffix.lower() in (".jpg", ".jpeg", ".png"):
            try:
                old.unlink()
            except OSError:
                pass
    return outdir_p


def run(path, outdir, dpi, shots=True, deadline=None):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    _prepare_outdir(outdir)
    if ext == "pdf":
        images = _pdf_to_images(Path(path), outdir, dpi)
    elif ext == "html":
        images = _html_to_images(path, outdir, dpi, shots=shots, deadline=deadline)
    elif ext in ("pptx", "docx", "xlsx", "xlsm"):
        images = _pdf_to_images(_to_pdf(path, outdir), outdir, dpi)
    else:
        return {"images": [], "count": 0, "error": f"unsupported type for render: {ext}"}
    return {"images": images, "count": len(images), "error": None}


def outdir_for(input_path):
    """工作目录 .tmp 下按「产物名 + 绝对路径 hash」建独立子目录：
    不同目录下的同名产物不会互相覆盖截图与断点缓存。"""
    p = os.path.abspath(input_path)
    stem = re.sub(r"[^\w.-]+", "_", Path(p).stem) or "artifact"
    h = hashlib.sha1(p.encode()).hexdigest()[:8]
    return str(_TMP_ROOT / f"dv-render-{stem}-{h}")


def main():
    ap = argparse.ArgumentParser(description="Render a deliverable to per-page JPEG images.")
    ap.add_argument("file")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--dpi", type=int, default=120)
    ap.add_argument("--no-shots", action="store_true", help="html 只跑探针与文本导出，不截图")
    args = ap.parse_args()
    outdir = args.outdir or outdir_for(args.file)
    try:
        if not os.path.exists(args.file):
            result = {"images": [], "count": 0, "error": "file not found"}
        else:
            result = run(args.file, outdir, args.dpi, shots=not args.no_shots)
    except Exception as e:
        result = {"images": [], "count": 0, "error": str(e)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
