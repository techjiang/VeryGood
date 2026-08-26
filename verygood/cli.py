"""CLI：python -m verygood build / serve / version"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from . import __version__, config as _cfg

BASE_DIR = Path(__file__).resolve().parent.parent


def log(msg: str):
    print(msg, flush=True)


def cmd_build(args) -> int:
    cfg = _cfg.load_config(args.config, BASE_DIR)
    from .builder import build

    try:
        stats = build(cfg, log=log, include_drafts=args.drafts)
    except Exception as e:  # noqa: BLE001
        log(f"[error] 构建失败: {e}")
        if args.debug:
            raise
        return 1
    log(f"[done] 构建完成：{stats['posts']} 篇文章 / {stats['pages']} 个页面 / {stats['files']} 个文件")
    if _cfg.base_path(cfg):
        log(f"[info] 检测到 basePath='{cfg['site']['basePath']}'，站点将部署在 {cfg['site']['url']}{_cfg.base_path(cfg)}/")
    return 0


def cmd_serve(args) -> int:
    cfg = _cfg.load_config(args.config, BASE_DIR)
    cfg_path = Path(args.config) if args.config else BASE_DIR / "config.yml"
    from .builder import build

    def rebuild():
        try:
            build(cfg, log=lambda m: None, include_drafts=args.drafts)
            return True
        except Exception as e:  # noqa: BLE001
            log(f"[warn] 构建失败: {e}")
            return False

    if not rebuild():
        return 1
    out = cfg["build"]["output_dir"]

    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out), **kw)

        def log_message(self, format, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    port = args.port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    log(f"[serve] 打开 {url}（Ctrl+C 退出）")

    stop = threading.Event()

    def watched():
        """监听：Markdown 内容、主题模板/静态资源、config.yml、用户插件。
        任一变化都会触发重新构建，改完即刷新生效。"""
        files = []
        for r in (cfg["build"]["source_dir"], cfg["theme"]["root"] / "templates",
                  cfg["theme"]["root"] / "static", cfg["theme"]["root"] / ".."):
            r = Path(r).resolve()
            if r.is_dir():
                files += [p for p in r.rglob("*") if p.is_file()
                          and p.suffix in (".md", ".yml", ".yaml", ".css", ".js", ".html", ".xml", ".py")]
        for extra in (cfg["theme"]["root"].parent.parent / "plugins", cfg["theme"]["root"].parent.parent / "scripts"):
            if extra.is_dir():
                files += [p for p in extra.rglob("*.py")]
        files.append(cfg_path)
        return files

    def watcher():
        cur_files = watched()
        last = max(_mtime(p) for p in cur_files) if cur_files else 0
        while not stop.is_set():
            time.sleep(1.2)
            cur_files = watched()
            cur = max(_mtime(p) for p in cur_files) if cur_files else 0
            if cur != last:
                last = cur
                log("[serve] 检测到变更，重新构建…")
                rebuild()

    t = threading.Thread(target=watcher, daemon=True)
    t.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    stop.set()
    return 0


def _walk(d: Path):
    return [p for p in d.rglob("*") if p.is_file() and p.suffix in (".md", ".yml", ".yaml", ".css", ".js")]


def _mtime(p: Path) -> float:
    return p.stat().st_mtime


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verygood", description="VeryGood 博客主题构建器")
    sub = parser.add_subparsers(dest="cmd")

    pb = sub.add_parser("build", help="构建静态站")
    pb.add_argument("--config", default=None, help="config.yml 路径")
    pb.add_argument("--drafts", action="store_true", help="包含草稿")
    pb.add_argument("--debug", action="store_true", help="出错时打印堆栈")

    ps = sub.add_parser("serve", help="本地预览（自动重建）")
    ps.add_argument("--config", default=None)
    ps.add_argument("--port", type=int, default=8000)
    ps.add_argument("--drafts", action="store_true")

    sub.add_parser("version", help="版本号")

    args = parser.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "version":
        log(f"VeryGood v{__version__}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())