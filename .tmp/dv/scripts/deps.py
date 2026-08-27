#!/usr/bin/env python3
"""依赖自举（国内源优先）：把"缺依赖"这件事从"静默降级"变成"先尝试装上"。

为什么要有这一层：本技能的多个维度依赖第三方库或 JS 解析器（openpyxl 之于公式重算、
node/esprima 之于内联 JS 语法自检）。装不上的后果不是报错，而是结论退回"未覆盖"——
也就是**没校验**。而官方源在国内经常慢到根本装不完，所以镜像不是提速，是可用性。

设计取舍（沿用实测结论）：
- **国内镜像优先，两条源都试**：清华 / 阿里 → 官方。顺序猜错最多多花一次失败的时间，
  不影响最终能否装上。顺序由 `DUMATE_DELIVERABLE_MIRROR`（auto|cn|official）决定，
  auto 按时区与 locale 猜（零成本强信号，不做联网探测——那等于先花一次超时）。
- **`pip install --target` 而不是 `--user`**：系统 Python 常被标记 externally-managed
  （PEP 668），`--user` 会被直接拒绝。`--target` 装进本技能自己的缓存，不碰系统环境，
  删目录即卸载。每个源都带 `--trusted-host`：企业内网常有自签 TLS 中间证书，握手失败
  会让"明明能连"的镜像变成不可用。
- **安装串行**：`defect_check.py` 是每产物一个进程并行跑的，多个进程同时往同一个
  `--target` 目录装包会互相覆盖，故用文件锁把安装串起来（拿不到锁不阻断）。
- **本模块永不抛栈**：所有网络/子进程操作都有超时与兜底，一律返回 (ok, detail)。

环境变量:
    DUMATE_DELIVERABLE_MIRROR       auto（默认）| cn | official
    DUMATE_DELIVERABLE_CACHE        缓存根目录，默认 ~/.cache/dumate-deliverable-verify
    DUMATE_DELIVERABLE_NO_INSTALL   非空且非 0/false 时只探测不安装（离线/CI）
"""
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

_TMP_ROOT = Path.cwd() / ".tmp"
_INSTALL_LOCK = _TMP_ROOT / "dv-install.lock"
_LOCK_WAIT_S = 240          # 首次装包（含索引响应）最坏几十秒，留足排队余量
_PIP_TIMEOUT_S = 180

# 清华、阿里都是 PyPI 全量同步镜像，装小包的差别主要在索引响应时间上。
_PYPI_CN = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
]
_PYPI_OFFICIAL = ["https://pypi.org/simple"]

_MIRROR_PREF = (os.environ.get("DUMATE_DELIVERABLE_MIRROR") or "auto").strip().lower()


def _prefers_cn():
    """猜当前机器是否在国内网络。只用于决定**先试哪条源**，猜错不影响最终能否装上。

    直接读 LANG/LC_ALL 而不用 locale.getdefaultlocale()：后者自 3.11 起已废弃，
    而它读的本来就是这几个环境变量。
    """
    if _MIRROR_PREF == "cn":
        return True
    if _MIRROR_PREF == "official":
        return False
    try:
        if time.strftime("%z") == "+0800":
            return True
    except ValueError:
        pass
    tz = os.environ.get("TZ", "")
    if any(k in tz for k in ("Shanghai", "Chongqing", "Hong_Kong", "Asia/Harbin")):
        return True
    langs = " ".join(os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG"))
    return "zh_CN" in langs or "zh_SG" in langs


def pypi_indexes():
    """按镜像偏好排出尝试顺序，两边都保留——猜错也能装上，只是多一次失败。"""
    return (_PYPI_CN + _PYPI_OFFICIAL) if _prefers_cn() else (_PYPI_OFFICIAL + _PYPI_CN)


def mirror_order():
    """给 doctor 用的可读顺序（只回主机名）。"""
    return [urllib.parse.urlsplit(u).hostname or u for u in pypi_indexes()]


def cache_dir():
    p = os.environ.get("DUMATE_DELIVERABLE_CACHE")
    return Path(p).expanduser() if p else Path.home() / ".cache" / "dumate-deliverable-verify"


def pylib_dir():
    return cache_dir() / "pylibs"


def install_allowed(flag=True):
    """联网安装是否允许：环境变量与调用方开关任一关闭即关闭。"""
    if os.environ.get("DUMATE_DELIVERABLE_NO_INSTALL", "").strip() not in ("", "0", "false"):
        return False
    return bool(flag)


def pylib_env(base=None):
    """把缓存 pylibs 加进 PYTHONPATH，供**子进程** import 缓存里的包。"""
    env = dict(base or os.environ)
    d = str(pylib_dir())
    old = env.get("PYTHONPATH", "")
    if d not in old.split(os.pathsep):
        env["PYTHONPATH"] = d + (os.pathsep + old if old else "")
    return env


def activate():
    """把缓存 pylibs 加进**本进程** sys.path：之前装到缓存里的包这样才 import 得到。"""
    d = str(pylib_dir())
    if d not in sys.path:
        sys.path.append(d)
    return d


activate()  # import 本模块即生效，调用方无需关心缓存路径


def _python():
    import shutil

    return shutil.which("python3") or shutil.which("python") or sys.executable


# ── 安装锁：并行的多个 defect_check.py 进程不能同时往同一个 --target 装包 ──
def _acquire_lock(timeout=_LOCK_WAIT_S):
    try:
        import fcntl
    except Exception:
        return None
    try:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        f = open(_INSTALL_LOCK, "w")
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


def _release_lock(f):
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


def _importable(import_name, env=None):
    """在子进程里验证是否 import 得到（避免污染本进程，也覆盖"pip 报成功但装歪了"）。"""
    try:
        return (
            subprocess.run(
                [_python(), "-c", f"import {import_name}"],
                capture_output=True,
                env=env or pylib_env(),
                timeout=60,
            ).returncode
            == 0
        )
    except Exception:
        return False


def _pip_install(pkg, import_name):
    """按镜像顺序依次尝试 pip install --target；返回 (ok, detail)，永不抛栈。"""
    target = pylib_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"缓存目录不可写 {target}: {str(e)[:120]}"
    errors = []
    for index in pypi_indexes():
        host = urllib.parse.urlsplit(index).hostname or index
        cmd = [
            _python(), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "--index-url", index, "--trusted-host", host,
            "--target", str(target), pkg,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_PIP_TIMEOUT_S)
        except Exception as e:
            errors.append(f"{host}: {str(e)[:120]}")
            continue
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            errors.append(f"{host}: {tail[-1][:140] if tail else '无输出'}")
            continue
        if not _importable(import_name):
            errors.append(f"{host}: pip 报成功但仍无法 import {import_name}")
            continue
        return True, f"已装到 {target}（源 {host}）"
    return False, "所有 PyPI 源均失败 —— " + "；".join(errors[-2:])


def ensure_module(pkg, import_name=None, install=True):
    """确保某个 python 包可用（本进程直接 import 得到）。返回 (ok, detail)。

    先试本进程 import（含缓存 pylibs，activate() 已挂上）；缺了再按国内源优先安装。
    """
    name = import_name or pkg.replace("-", "_")
    try:
        __import__(name)
        return True, "已可用"
    except Exception:
        pass
    if not install_allowed(install):
        return False, "缺失且已禁用自动安装（DUMATE_DELIVERABLE_NO_INSTALL）"
    lock = _acquire_lock()
    try:
        try:  # 排队期间别的进程可能已经装好
            __import__(name)
            return True, "已可用（由并行进程装上）"
        except Exception:
            pass
        ok, detail = _pip_install(pkg, name)
    finally:
        _release_lock(lock)
    if not ok:
        return False, detail
    activate()
    # 目录是刚创建/刚填充的：FileFinder 缓存了旧的目录状态，不失效就会一直报 No module named
    try:
        import importlib

        importlib.invalidate_caches()
    except Exception:
        pass
    try:
        __import__(name)
        return True, detail
    except Exception as e:
        return False, f"{detail}，但本进程仍 import 失败: {str(e)[:120]}"


# ── JS 语法解析器：node 优先，其次 esprima（几百 KB 的真解析器，结论等价）──
def probe_js_parser():
    """只探测、不安装。返回 {"kind": "node"|"esprima"|None, "node", "env", "detail"}。"""
    import shutil

    node = shutil.which("node")
    if node:
        return {"kind": "node", "node": node, "env": None, "detail": node}
    if _importable("esprima", dict(os.environ)):
        return {"kind": "esprima", "node": None, "env": None, "detail": "系统 Python 已装 esprima"}
    if _importable("esprima", pylib_env()):
        return {"kind": "esprima", "node": None, "env": pylib_env(), "detail": f"缓存 {pylib_dir()}"}
    return {"kind": None, "node": None, "env": None, "detail": "无 node，也无 esprima"}


def ensure_js_parser(install=True):
    """确保有真解析器可用；拿不到时 kind 为 None，调用方据此退化为启发式并标"未覆盖"。

    默认装 esprima 而不是 node：两者都是真解析器、结论等价，esprima 几百 KB，node 五十兆。
    """
    got = probe_js_parser()
    if got["kind"]:
        return got
    if not install_allowed(install):
        return {**got, "detail": got["detail"] + "；已禁用自动安装（DUMATE_DELIVERABLE_NO_INSTALL）"}
    lock = _acquire_lock()
    try:
        got = probe_js_parser()  # 排队期间别的进程可能已经装好
        if got["kind"]:
            return got
        ok, detail = _pip_install("esprima", "esprima")
    finally:
        _release_lock(lock)
    if ok:
        return {"kind": "esprima", "node": None, "env": pylib_env(), "detail": detail}
    return {
        "kind": None,
        "node": None,
        "env": None,
        "detail": f"esprima 安装失败（已按顺序尝试 {', '.join(mirror_order())}）：{detail}",
    }
