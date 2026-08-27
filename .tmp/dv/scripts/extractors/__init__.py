"""extractors 包：按产物类型分模块抽取正文与链接，对外只暴露 load()。

content_extract.py / defect_check.py 都经此入口取解析能力，保证「一套解析、多处复用」。
"""

_ROUTES = {
    "docx": "docx",
    "pptx": "pptx",
    "xlsx": "xlsx",
    "xlsm": "xlsx",
    "pdf": "pdf",
    "html": "html",
}


def supported(ext):
    return (ext or "").lower().lstrip(".") in _ROUTES


def load(ext):
    """按扩展名返回对应抽取模块；不支持的类型返回 None。"""
    key = _ROUTES.get((ext or "").lower().lstrip("."))
    if not key:
        return None
    mod = __import__(f"extractors.{key}", fromlist=["extract"])
    return mod
