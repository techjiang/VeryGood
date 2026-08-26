"""插件系统：内置插件（verygood/plugins/*）直接启用；
用户插件在 config.plugins 中列出目录，约定目录内 plugin.py 提供 setup(ctx)。"""
from __future__ import annotations

import importlib.util
import pkgutil
import sys
from pathlib import Path


class PluginContext:
    """插件上下文：注册短代码 / 挂钩子 / 追加模板注入片段。"""

    def __init__(self, log):
        self.log = log
        self.shortcodes: dict = {}
        self.hooks: dict[str, list] = {}
        self.template_injections: dict[str, list[str]] = {}  # 位置 -> 注入的 html

    # ---- 短代码 ----
    def register_shortcode(self, name: str, fn):
        self.shortcodes[name] = fn

# ---- 钩子 ----
    def hook(self, name: str):
        """注册钩子处理器（装饰器用法）：@ctx.hook('after_build')"""
        def deco(fn):
            self.hooks.setdefault(name, []).append(fn)
            return fn
        return deco

    def emit(self, name: str, payload=None):
        """触发钩子。单个钩子抛异常仅记日志，不中断构建（错误隔离）。"""
        for fn in self.hooks.get(name, []):
            try:
                fn(payload)
            except Exception as e:  # noqa: BLE001
                self.log(f"  [plugin] 钩子 {name} 执行失败: {e}")

    # ---- 模板注入 ----
    def inject(self, position: str, html: str):
        """position: head / header_extra / footer_extra / body_end"""
        self.template_injections.setdefault(position, []).append(html)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_plugins(cfg: dict, log) -> PluginContext:
    ctx = PluginContext(log)
    root = cfg["theme"]["root"].parent.parent
    loaded: set[Path] = set()

    # 1) 内置插件：verygood/plugins 包下的每个模块
    import verygood.plugins as builtin_pkg

    names = sorted(m.name for m in pkgutil.iter_modules(builtin_pkg.__path__))
    for n in names:
        try:
            mod = __import__(f"verygood.plugins.{n}", fromlist=["setup"])
            if hasattr(mod, "setup"):
                mod.setup(ctx)
                log(f"  [plugin] 内置 {n}")
        except Exception as e:  # noqa: BLE001
            log(f"  [plugin] 内置 {n} 加载失败: {e}")

    def _load(entry: Path, label: str):
        """加载单个 plugin.py，成功返回 True。"""
        if not entry.exists():
            return False
        if entry.resolve() in loaded:
            return False
        try:
            mod = _load_module(entry, f"vg_user_plugin_{label}")
            if mod and hasattr(mod, "setup"):
                mod.setup(ctx)
                loaded.add(entry.resolve())
                log(f"  [plugin] 用户 {label}")
                return True
        except Exception as e:  # noqa: BLE001
            log(f"  [plugin] 用户 {label} 加载失败: {e}")
        return False

    # 2) 用户插件目录即装即用：仓库根 plugins/ 下自动发现
    #    plugins/xxx/plugin.py（目录插件）或 plugins/xxx.py（单文件插件）
    auto_dir = root / "plugins"
    if auto_dir.is_dir():
        for d in sorted(auto_dir.iterdir()):
            if d.is_dir():
                _load(d / "plugin.py", d.name)
            elif d.suffix == ".py" and not d.name.startswith("_"):
                _load(d, d.stem)

    # 3) 显式配置：config.plugins 中列出的目录（相对仓库根），取目录内 plugin.py
    for item in cfg["plugins"] or []:
        p = Path(item)
        if not p.is_absolute():
            p = root / p
        entry = p / "plugin.py"
        if not _load(entry, p.name):
            if not entry.exists():
                log(f"  [plugin] 未找到用户插件入口: {entry}")

    return ctx