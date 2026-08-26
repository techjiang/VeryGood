"""插件系统（v1.3.0）：

- 内置插件：verygood/plugins/*.py 或 verygood/plugins/*/plugin.py（开箱即用）
- 用户插件：仓库根 plugins/*/plugin.py 自动发现，或 config.plugins 显式列出
- 能力：短代码 / 钩子 / 模板注入 / 全局变量 / Jinja 过滤器 / 元信息 / 静态资源
- 隔离：单个钩子抛异常仅记日志，不中断构建

插件开发详见 docs/插件开发文档.md。
"""
from __future__ import annotations

import ast
import importlib.util
import pkgutil
import sys
from pathlib import Path

# 内置插件名（目录式插件用），用于跳过 __init__ 等系统文件
_SKIP_MODULES = {"__init__", "pycache"}

# 注入位置清单（v1.3.0 扩充）：
#   head           <head> 末尾
#   header_extra   顶栏容器内
#   footer_extra   页脚主区
#   body_end       </body> 前
#   sidebar_data   左侧栏（站点数据组件位置，v1.3.0）
#   content_top    主内容区顶部（v1.3.0）
#   content_bottom 主内容区底部（v1.3.0：base.html 预留，见 base.html）
#   rightbar       右侧栏（v1.4.0：时间卡片 / 微语等右栏组件）
_INJECT_POSITIONS = ("head", "header_extra", "footer_extra", "body_end", "sidebar_data", "content_top", "content_bottom", "rightbar")


def _collect_meta(mod) -> dict:
    """从插件模块顶层常量收集元信息（__title__ / __description__ / __version__ / __author__）。"""
    meta = {}
    for key in ("__title__", "__description__", "__version__", "__author__"):
        val = getattr(mod, key, "")
        if isinstance(val, str) and val:
            meta[key] = val
    return meta


def _static_dir_of(locator: Path) -> Path | None:
    """按插件定位目录找 static/ 子目录（不存在返回 None）。"""
    d = locator / "static"
    return d if d.is_dir() else None


class PluginContext:
    """插件上下文：注册短代码 / 挂钩子 / 追加模板注入片段 / 注入全局变量与 Jinja 过滤器。"""

    def __init__(self, log):
        self.log = log
        self.shortcodes: dict = {}
        self.hooks: dict[str, list] = {}
        self.template_injections: dict[str, list[str]] = {}  # 位置 -> 注入的 html
        self.globals: dict = {}   # v1.2.0：模板全局变量（插件 → 模板）
        self.filters: dict = {}   # v1.2.0：Jinja 过滤器（插件 → 模板）
        self.meta: dict[str, dict] = {}            # v1.3.0：插件名 -> {title, description, version, author, source}
        self.static_dirs: dict[str, Path] = {}     # v1.3.0：插件名 -> static 目录（构建期拷到 dist/plugins/{name}/）

    def _register(self, name: str, mod, source: str, static_dir: Path | None):
        """登记插件元信息与静态资源目录（由加载器调用）。"""
        self.meta.setdefault(name, {"source": source})
        self.meta[name].update(_collect_meta(mod))
        self.meta[name]["source"] = source
        if static_dir is not None:
            self.static_dirs.setdefault(name, static_dir)

    # ---- 短代码 ----
    def register_shortcode(self, name: str, fn):
        self.shortcodes[name] = fn

    # ---- 全局变量与过滤器（v1.2.0：插件向模板暴露能力） ----
    def add_global(self, name: str, value):
        """向全部模板注入一个全局变量：ctx.add_global('build_year', 2026)。
        模板中直接 {{ build_year }} 使用；覆盖同名内置全局时以插件为准。"""
        self.globals[name] = value

    def add_filter(self, name: str, fn):
        """注册一个 Jinja 过滤器：ctx.add_filter('emoji', fn)。模板中 {{ 'x' | emoji }} 使用。"""
        self.filters[name] = fn

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
        """向指定位置注入 HTML 片段。
        position（v1.4.0）：head / header_extra / footer_extra / body_end / sidebar_data / content_top / content_bottom / rightbar
        注入内容中的 __BASE__ 占位符会在渲染时替换为站点 basePath（如 /VeryGood）。
        """
        if position not in _INJECT_POSITIONS:
            self.log(f"  [plugin] 未知注入位置 {position!r}，已忽略（可用：{', '.join(_INJECT_POSITIONS)}）")
            return
        self.template_injections.setdefault(position, []).append(html)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        sys.modules.pop(name, None)
        raise
    return mod


def _apply_plugin(ctx: PluginContext, entry: Path, name: str, source: str, is_builtin: bool = False):
    """执行单个插件的 setup() 并登记元信息/静态资源；成功返回 True 或说明。"""
    try:
        mod = _load_module(entry, f"vg_{'builtin' if is_builtin else 'plugin'}_{name}")
        if mod is None or not hasattr(mod, "setup"):
            return False
        mod.setup(ctx)
        if is_builtin:
            # 目录式内置插件 loc=自身目录；单文件内置插件允许同名目录携带 static/
            _mp = Path(mod.__file__).parent
            loc = _mp if _mp.name == name else _mp / name
        else:
            loc = entry.parent
        ctx._register(name, mod, source, _static_dir_of(loc))
        ctx.log(f"  [plugin] {'内置' if is_builtin else '用户'} {name}"
                + (f"（{ctx.meta[name].get('__description', '')}）" if ctx.meta[name].get("__description") else ""))
        return True
    except Exception as e:  # noqa: BLE001
        ctx.log(f"  [plugin] {'内置' if is_builtin else '用户'} {name} 加载失败: {e}")
        return False


def load_plugins(cfg: dict, log) -> PluginContext:
    ctx = PluginContext(log)
    root = cfg["theme"]["root"].parent.parent
    disabled = {str(x).strip() for x in (cfg.get("plugins_disabled") or []) if str(x).strip()}

    def _skip(name: str) -> bool:
        if name in disabled:
            log(f"  [plugin] 跳过已禁用插件: {name}")
            return True
        return False

    # 1) 内置插件：verygood/plugins 包下的模块与目录插件
    import verygood.plugins as builtin_pkg

    builtin_dir = Path(builtin_pkg.__file__).parent
    for n in sorted(m.name for m in pkgutil.iter_modules(builtin_pkg.__path__)):
        if n.startswith("_") or _skip(n):
            continue
        _apply_plugin(ctx, builtin_dir / f"{n}.py", n, "内置", is_builtin=True)
    # 目录式内置插件（v1.3.0）：verygood/plugins/xxx/plugin.py（可自带 static/）
    for child in sorted(builtin_dir.iterdir()):
        if child.is_dir() and (child / "plugin.py").is_file():
            n = child.name
            if n.startswith("_") or _skip(n):
                continue
            if n not in (m.name for m in pkgutil.iter_modules(builtin_pkg.__path__)):
                _apply_plugin(ctx, child / "plugin.py", n, "内置", is_builtin=True)

    def _load_user(entry: Path, name: str, source: str):
        """加载单个用户插件；成功返回 True。"""
        if not entry.exists():
            return False
        if _skip(name):
            return True
        return _apply_plugin(ctx, entry, name, source)

    # 2) 用户插件目录即装即用：仓库根 plugins/ 下自动发现
    #    plugins/xxx/plugin.py（目录插件）或 plugins/xxx.py（单文件插件）
    auto_dir = root / "plugins"
    if auto_dir.is_dir():
        for d in sorted(auto_dir.iterdir()):
            if d.is_dir() and (d / "plugin.py").is_file():
                _load_user(d / "plugin.py", d.name, "自动发现")
            elif d.suffix == ".py" and not d.name.startswith("_") and d.name != "plugin.py":
                _load_user(d, d.stem, "自动发现")

    # 3) 显式配置：config.plugins 中列出的目录（相对仓库根），取目录内 plugin.py
    for item in cfg["plugins"] or []:
        p = Path(item)
        if not p.is_absolute():
            p = root / p
        entry = p / "plugin.py"
        if not _load_user(entry, p.name, "显式配置"):
            if not entry.exists():
                log(f"  [plugin] 未找到用户插件入口: {entry}")

    return ctx


def _peek_meta(entry: Path) -> dict:
    """静态读取插件文件的元信息（不执行插件代码）。"""
    try:
        tree = ast.parse(entry.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("__title__", "__description__", "__version__", "__author__")
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def list_plugins(cfg: dict, log=print) -> dict:
    """枚举插件清单（不执行插件代码）：内置插件 + 仓库根 plugins/ 自动发现 + config.plugins 显式配置。"""
    import verygood.plugins as builtin_pkg

    builtin_dir = Path(builtin_pkg.__file__).parent
    root = cfg["theme"]["root"].parent.parent
    disabled = {str(x).strip() for x in (cfg.get("plugins_disabled") or []) if str(x).strip()}

    def _line(name: str, entry: Path, source: str):
        meta = _peek_meta(entry)
        tag = "  [已禁用]" if name in disabled else ""
        desc = meta.get("__description", "")
        ver = meta.get("__version", "")
        log(f"  · {name}{tag}"
            + (f" —— {desc}" if desc else "")
            + (f"（v{ver}）" if ver and desc else (f"（v{ver}）" if ver else "")))

    builtin = []
    for m in sorted(pkgutil.iter_modules(builtin_pkg.__path__)):
        if m.name.startswith("_"):
            continue
        builtin.append(m.name)
        _line(m.name, builtin_dir / f"{m.name}.py", "内置")
    for child in sorted(builtin_dir.iterdir()):
        if child.is_dir() and (child / "plugin.py").is_file() and child.name not in builtin:
            builtin.append(child.name)
            _line(child.name, child / "plugin.py", "内置")

    auto: list[str] = []
    auto_dir = root / "plugins"
    if auto_dir.is_dir():
        for d in sorted(auto_dir.iterdir()):
            if d.is_dir() and (d / "plugin.py").is_file():
                auto.append(d.name)
                _line(d.name, d / "plugin.py", "自动发现")
            elif d.suffix == ".py" and not d.name.startswith("_") and d.name != "plugin.py":
                auto.append(d.stem)
                _line(d.stem, d, "自动发现")

    config: list[str] = []
    for item in cfg["plugins"] or []:
        p = Path(item)
        if not p.is_absolute():
            p = root / p
        entry = p / "plugin.py"
        if entry.exists():
            config.append(p.name)
            _line(p.name, entry, "显式配置")
        else:
            config.append(f"{p.name}（未找到 plugin.py）")
            log(f"  · {p.name}（未找到 plugin.py）")

    log(f"  内置插件 {len(builtin)} 个：{', '.join(builtin) or '—'}")
    log(f"  自动发现 {len(auto)} 个：{', '.join(auto) or '—'}")
    log(f"  显式配置 {len(config)} 个：{', '.join(config) or '—'}")
    if disabled:
        log(f"  已禁用 {sorted(disabled)}：构建时跳过")
    return {"builtin": builtin, "auto": auto, "config": config, "disabled": sorted(disabled)}