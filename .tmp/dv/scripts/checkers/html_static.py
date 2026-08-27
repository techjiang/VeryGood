#!/usr/bin/env python3
"""html 源码层静态校验：内联 JS 语法自检 + 图表容器/引库约定。

为什么必须有这一项：html 里手写的内联 `<script>`（尤其 ECharts 的 `option` 对象）极易出现
括号/引号配对错误——多层嵌套对象、箭头函数 `s=>({...})`、跨行字符串。代码通读一遍看不出问题，
但只要有一处失配，整个 `<script>` 块就会 `SyntaxError`，**该页所有图表全部不渲染**（不是某一个
图空，是全空）。文件写成功了、浏览器能打开、页面骨架也在，唯独图表区一片空白——纯源码层能给出
确定性结论的静默失败，只有这一类。

本模块只做**分析**，不做输出格式与退出码：结果按 `deliverable-verify` 的 `checks[].status`
四档（fail / warn / skip / pass）回给 `defect_check.py`，全技能只有一套判定标准。

分档依据（不擅自加码）：
- `js_syntax` = **fail**：真解析器（node --check / esprima）给出的确定性结论。
- `chart_container` / `chart_lib` = **warn**：静态推断，高度可能由外部 CSS 供给、容器可能由 JS
  动态创建——恰是"可能是设计意图，单独不足以判 must 不满足"的定义。用推断去阻断一份可能完全
  正常的产物，是比漏报更坏的结果。
- `skip` = 未覆盖：无内联脚本 / 无容器引用（零覆盖不是通过），或无解析器可用。

零第三方依赖（esprima 是可选自举件，由 deps.py 按国内源优先安装，不是 import 依赖）。
本模块永不抛栈：任何一项内部异常都收敛成该项 `skip` + 原因。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 挂 scripts/ 而不是本包目录：esprima 自举用的 deps.py 在上一层
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_HITS = 8            # 单个 check 的 detail 里最多列几条，避免输出爆炸
_NODE_TIMEOUT_S = 30
_ESPRIMA_TIMEOUT_S = 60

# 可被当作 JavaScript 校验的 <script type>；其余（json / importmap / template）跳过
JS_TYPES = {"", "text/javascript", "application/javascript", "text/ecmascript", "module"}

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TYPE_RE = re.compile(r"""(?<![\w-])type\s*=\s*["']?([^"'\s>]+)""", re.I)
# `(?<![\w-])` 而非 `\b`：`\b` 会让 `data-src=` / `data-id=` 命中（连字符也是词边界），
# 于是 data-* 属性被当成真 src/id —— 前者导致内联脚本被误判为外链而跳过语法校验，
# 后者在页面里制造凭空的"id 重复"。
SRC_RE = re.compile(r"(?<![\w-])src\s*=", re.I)
ID_RE = re.compile(r"""(?<![\w-])id\s*=\s*["']([^"']+)["']""", re.I)
# 脚本里动态赋 id 的两种常见写法，用于放宽"容器不存在"的判定
DYN_ID_RE = re.compile(
    r"""\.id\s*=\s*["']([^"']+)["']|setAttribute\(\s*["']id["']\s*,\s*["']([^"']+)["']""",
    re.I,
)
# 图表初始化时直接引用容器：xxx(document.getElementById('x')) 或 querySelector('#x')。
# 两个库分开匹配：容器约定相反（ECharts 给 div 设高；Chart.js 的 canvas 反而**不该**设高，
# 高度要给外层 wrapper），后续高度检查只对 ECharts 生效。
_INIT_TAIL = (
    r"""\(\s*document\.(?:getElementById\(\s*["']([^"']+)["']"""
    r"""|querySelector\(\s*["']#([^"']+)["'])"""
)
ECHARTS_INIT_RE = re.compile(r"echarts\.init" + _INIT_TAIL, re.I)
CHARTJS_INIT_RE = re.compile(r"new\s+Chart" + _INIT_TAIL, re.I)
EXTERNAL_CSS_RE = re.compile(r"""<link[^>]+rel\s*=\s*["']?stylesheet""", re.I)
CANVAS_TAG_RE = re.compile(r"<canvas\b[^>]*>", re.I)
ECHARTS_USE_RE = re.compile(r"\becharts\s*\.")
CHARTJS_USE_RE = re.compile(r"\bnew\s+Chart\s*\(")


def _lib_import_res(*names):
    """某图表库是否被引入：<script src> / import / require / importmap key 四种形态。"""
    alt = "|".join(names)
    return (
        re.compile(rf"""(?:src|href)\s*=\s*["'][^"']*(?:{alt})""", re.I),
        re.compile(rf"""import[^;\n]*["'][^"']*(?:{alt})""", re.I),
        re.compile(rf"""import\(\s*["'][^"']*(?:{alt})""", re.I),
        re.compile(rf"""require\(\s*["'][^"']*(?:{alt})""", re.I),
        re.compile(rf"""["'][^"']*(?:{alt})[^"']*["']\s*:""", re.I),
    )


ECHARTS_IMPORT_RES = _lib_import_res("echarts")
CHARTJS_IMPORT_RES = _lib_import_res(r"chart\.js", r"chart\.umd", r"chart\.min", "chartjs")


def _f(line, msg, hint=""):
    """一条发现（finding）。line 为 HTML 原文行号（0 表示无行号）。"""
    return {"line": line, "msg": msg, "hint": hint}


def _c(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


def _detail(findings, tail="", limit=MAX_HITS):
    """把 findings 拼成 detail：带行号（证据指针），修复提示只保留首条（避免刷屏）。"""
    parts = []
    for f in findings[:limit]:
        loc = f"行{f['line']}: " if f.get("line") else ""
        parts.append(loc + f["msg"])
    if len(findings) > limit:
        parts.append(f"…另有 {len(findings) - limit} 处")
    hint = next((f["hint"] for f in findings if f.get("hint")), "")
    out = "; ".join(parts)
    if hint:
        out += f"（修法: {hint}）"
    return out + (f" {tail}" if tail else "")


def line_of(text, pos):
    """返回 text 中偏移 pos 处的 1-based 行号。"""
    return text.count("\n", 0, pos) + 1


# ── 视图预处理：区分「活代码 / 真实 markup / 脚本文本」 ──
def _blank_spans(text, spans):
    """把给定区间替换为等长空格（保留换行），从而维持行号与偏移完全不变。"""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


# ── JS 词法扫描：识别注释 / 字符串 / 正则字面量 ──
# `/` 出现在这些 token 之后才可能是正则字面量的开头（否则是除号）。
_REGEX_PREV_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete",
    "void", "throw", "do", "else", "case", "yield", "await",
}
_REGEX_PREV_CHARS = "(,=:[!&|?{};+-*%~^<>"


def _skip_string(code, i):
    """从引号处跳到闭合引号之后。模板串的 `${...}` 插值段整段跳过（内部可再嵌字符串）。"""
    q, j, n = code[i], i + 1, len(code)
    while j < n:
        ch = code[j]
        if ch == "\\":
            j += 2
            continue
        if q == "`" and ch == "$" and j + 1 < n and code[j + 1] == "{":
            j = _skip_braces(code, j + 1)
            continue
        if ch == q:
            return j + 1
        j += 1
    return n


def _skip_braces(code, i):
    """从 `{` 跳到配对 `}` 之后（模板串插值用；内部字符串递归跳过）。"""
    depth, j, n = 0, i, len(code)
    while j < n:
        ch = code[j]
        if ch in "'\"`":
            j = _skip_string(code, j)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _skip_regex(code, i):
    """从 `/` 跳到正则字面量结束之后；不是合法正则（如跨行）时返回 i 表示放弃。"""
    j, n, in_class = i + 1, len(code), False
    while j < n:
        ch = code[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "\n":
            return i
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "/":
            j += 1
            while j < n and code[j].isalpha():
                j += 1
            return j
        j += 1
    return i


def _js_token_spans(code):
    """扫描一段 JS，返回 (注释, 字符串, 正则) 三组 [start,end) 区间。

    单独识别正则字面量是必要的：`/[{(]/` 里的括号不该参与配平，否则会在一份完全正常的
    页面上报"疑似括号失配"——校验器一旦爱喊狼来了就会被无视。
    """
    comments, strings, regexes = [], [], []
    i, n, prev, prev_word = 0, len(code), "", ""
    while i < n:
        c = code[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            j = code.find("\n", i)
            j = n if j < 0 else j
            comments.append((i, j))
            i = j
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
            comments.append((i, j))
            i = j
            continue
        if c in "'\"`":
            j = _skip_string(code, i)
            strings.append((i, j))
            i, prev, prev_word = j, c, ""
            continue
        if c == "/" and (prev == "" or prev in _REGEX_PREV_CHARS or prev_word in _REGEX_PREV_KEYWORDS):
            j = _skip_regex(code, i)
            if j > i:
                regexes.append((i, j))
                i, prev, prev_word = j, "/", ""
                continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (code[j].isalnum() or code[j] in "_$"):
                j += 1
            prev, prev_word, i = code[j - 1], code[i:j], j
            continue
        prev, prev_word = c, ""
        i += 1
    return comments, strings, regexes


def prepare_views(html):
    """产出四个等长视图（行号与原文一致，可直接用于定位）：

      live    抹掉 HTML 注释区后的"活代码"。被 <!-- --> 注释掉的旧图表、废弃脚本不该参与
              校验，否则会在一份正常页面上误报。
      markup  在 live 基础上再抹掉 <script> 体，只剩真实 DOM 标记。用于 id 重复判定，
              避免把 JS 字符串模板里的 id="x" 当成 DOM 节点。
      code    在 live 基础上抹掉 JS 里的**注释与正则字面量**，只剩"真在执行"的代码。
              否则「早期版本用 echarts.init 实现」这样一句 JS 注释就会被判成"用了 echarts
              却没引库"。**字符串必须保留**：容器 id 本身就写在字符串里。
      scripts live 中所有 <script> 体拼接（含字符串），用于识别动态创建的容器 id。

    注释区的识别先在"脚本体已抹掉"的副本上做，这样 JS 字符串里出现的 "<!--" 不会伪造出
    一段注释区，从而误抹真实代码。
    """
    no_bodies = _blank_spans(html, [(m.start(2), m.end(2)) for m in SCRIPT_RE.finditer(html)])
    comment_spans = [(m.start(), m.end()) for m in HTML_COMMENT_RE.finditer(no_bodies)]
    live = _blank_spans(html, comment_spans)
    markup = _blank_spans(live, [(m.start(2), m.end(2)) for m in SCRIPT_RE.finditer(live)])
    scripts = "\n".join(m.group(2) for m in SCRIPT_RE.finditer(live))

    dead_spans = []
    for m in SCRIPT_RE.finditer(live):
        base, body = m.start(2), m.group(2)
        comments, _strings, regexes = _js_token_spans(body)
        dead_spans += [(base + s, base + e) for s, e in comments + regexes]
    code = _blank_spans(live, dead_spans)
    return live, markup, code, scripts


def extract_inline_scripts(live):
    """产出 (start_line, body, is_module)。跳过外链脚本与非 JS type。"""
    scripts = []
    for m in SCRIPT_RE.finditer(live):
        attrs, body = m.group(1), m.group(2)
        if SRC_RE.search(attrs):
            continue  # 外链脚本，无内联体可校验
        tmatch = TYPE_RE.search(attrs)
        stype = tmatch.group(1).lower() if tmatch else ""
        if stype not in JS_TYPES:
            continue  # json / importmap / text/template 等，按 JS 校验必然误报
        if not body.strip():
            continue
        scripts.append((line_of(live, m.start(2)), body, stype == "module"))
    return scripts


# ── 语法校验：node --check（首选）→ esprima → 启发式配平 ──
def _pad(body, start_line):
    """左填充换行，使临时文件行号与 HTML 行号一一对应。"""
    return "\n" * (start_line - 1) + body


def _python_bin():
    return shutil.which("python3") or shutil.which("python") or sys.executable


def check_syntax_with_node(scripts, node_bin):
    """逐个脚本调用 node --check。返回 findings（确定性语法错误）。"""
    findings = []
    for start_line, body, is_module in scripts:
        suffix = ".mjs" if is_module else ".js"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
                tmp = fh.name
                fh.write(_pad(body, start_line))
            proc = subprocess.run(
                [node_bin, "--check", tmp], capture_output=True, text=True, timeout=_NODE_TIMEOUT_S
            )
            if proc.returncode != 0:
                line, col, msg = _parse_node_error(proc.stderr, tmp)
                findings.append(
                    _f(
                        line or start_line,
                        (msg or "SyntaxError（node --check 未通过）")
                        + (f"（约第 {col} 列）" if col else ""),
                        hint="检查该行附近的 =>({...}) 与 series:[{...}] 括号/引号配平",
                    )
                )
        except Exception as e:
            findings.append(_f(start_line, f"node --check 执行异常: {str(e)[:120]}"))
        finally:
            if tmp:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
    return findings


def _parse_node_error(stderr, tmp):
    """从 node --check 的 stderr 中解析 (line, col, message)。"""
    line = col = None
    msg = ""
    lines = stderr.splitlines()
    esc = re.escape(tmp)
    for ln in lines:
        m = re.search(esc + r":(\d+)", ln)
        if m:
            line = int(m.group(1))
            break
    for i, ln in enumerate(lines):
        m = re.search(r"((?:Syntax|Reference|Type)?Error:.*)", ln)
        if m:
            msg = m.group(1).strip()
            prev = lines[i - 1] if i > 0 else ""
            if prev.strip() and set(prev.strip()) <= {"^", "~"}:
                col = len(prev) - len(prev.lstrip()) + 1
            break
    if not msg:
        for ln in lines:
            s = ln.strip()
            if s and set(s) <= {"^", "~"}:
                col = len(ln) - len(ln.lstrip()) + 1
                break
    return line, col, msg


_ESPRIMA_PROG = (
    "import sys, json, esprima\n"
    "code = sys.stdin.read()\n"
    "mod = sys.argv[1] == 'module'\n"
    "try:\n"
    "    (esprima.parseModule if mod else esprima.parseScript)(code)\n"
    "    print(json.dumps({'ok': True}))\n"
    "except Exception as e:\n"
    "    print(json.dumps({'ok': False, 'line': getattr(e, 'lineNumber', None), 'msg': str(e)}))\n"
)


def check_syntax_with_esprima(scripts, env=None):
    """node 不可用时的第二级：python + esprima（同为真解析器，结论等价）。

    返回 (findings, ok)。ok=False 表示 esprima 真用时不可用（探测时还在、缓存被删等），
    调用方必须按"未覆盖"处理，不能默认通过。
    """
    py = _python_bin()
    try:
        if subprocess.run([py, "-c", "import esprima"], capture_output=True, env=env, timeout=60).returncode != 0:
            return [], False
    except Exception:
        return [], False

    findings = []
    for start_line, body, is_module in scripts:
        try:
            proc = subprocess.run(
                [py, "-c", _ESPRIMA_PROG, "module" if is_module else "script"],
                input=_pad(body, start_line),
                capture_output=True,
                text=True,
                env=env,
                timeout=_ESPRIMA_TIMEOUT_S,
            )
            res = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            continue
        if not res.get("ok"):
            findings.append(
                _f(
                    res.get("line") or start_line,
                    res.get("msg", "SyntaxError（esprima）"),
                    hint="检查 =>({...}) 与 series:[{...}] 括号/引号配平",
                )
            )
    return findings, True


def heuristic_brace_balance(scripts):
    """第三级：无任何解析器时的括号配平检查（仅参考信号，不是判据）。

    注释、字符串、模板串插值、正则字面量都先经 `_js_token_spans` 抹掉，所以 `/[{(]/`
    这类正则不会误报；但**配平通过不等于语法正确**（`{a:1,,}` 括号是平的）。
    """
    findings = []
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = set("([{")
    for start_line, body, _ in scripts:
        spans = [s for group in _js_token_spans(body) for s in group]
        clean = _blank_spans(body, spans)
        stack, line, mismatched = [], start_line, False
        for c in clean:
            if c == "\n":
                line += 1
            elif c in opens:
                stack.append((c, line))
            elif c in pairs:
                if not stack or stack[-1][0] != pairs[c]:
                    findings.append(_f(line, f"疑似括号失配：出现多余或不匹配的 '{c}'"))
                    mismatched = True
                    break
                stack.pop()
        if not mismatched and stack:
            ch, ln = stack[-1]
            findings.append(_f(ln, f"疑似括号未闭合：'{ch}' 起始处到脚本结尾未见配对"))
    return findings


# ── 结构检查（全部 warn 级：静态推断，不作为交付闸门）──
def _find_tag_with_id(markup, target):
    for m in re.finditer(r"""<[^>]*?(?<![\w-])id\s*=\s*["']([^"']+)["'][^>]*>""", markup, re.I):
        if m.group(1) == target:
            return m.group(0), m.start()
    return None, None


def _style_blocks(live):
    return "\n".join(
        m.group(1) for m in re.finditer(r"<style\b[^>]*>(.*?)</style\s*>", live, re.I | re.S)
    )


# `(?<![\w-])`：`line-height` / `max-height` / `min-height` 都不是元素高度。尤其
# `line-height: 1.6` 会被读成"高度 1.6 > 0 → 有高度"，把一个真实的 0 高度容器判成合格。
_HEIGHT_RE = re.compile(r"(?<![\w-])height\s*:\s*([0-9.]+)\s*(px|%|vh|em|rem|vw|vmin|vmax)?", re.I)
_PCT_UNITS = {"%"}
# 这些声明会让元素从别处拿到高度，静态分析追不下去（flex/grid 的 stretch 与 flex:1、
# 绝对定位的 top+bottom 对撑、aspect-ratio 由宽度反推）。链上出现任一就不下"高度为 0"
# 的结论——误报一次就够让使用者学会忽略这个校验器。
_STRETCH_RE = re.compile(
    r"(?<![\w-])(?:display\s*:\s*(?:flex|inline-flex|grid|inline-grid)"
    r"|position\s*:\s*(?:absolute|fixed)"
    r"|flex\s*:"
    r"|flex-grow\s*:"
    r"|align-self\s*:"
    r"|grid-area\s*:"
    r"|grid-row\s*:"
    r"|aspect-ratio\s*:)", re.I
)


def _height_state(css_text):
    """True(确定的正高度) / False(显式为 0) / "pct"(百分比，取决于祖先) / None(未提及)。

    百分比单独成一档：`height:100%` 相对包含块解析，包含块是 auto 高时它解析为 0。
    "父容器没写高度 + 子容器 100%" 正是 ECharts 空白最经典的成因之一。
    """
    m = _HEIGHT_RE.search(css_text)
    if not m:
        return None
    if float(m.group(1)) <= 0:
        return False
    return "pct" if (m.group(2) or "") in _PCT_UNITS else True


_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}", re.S)
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
_MIN_HEIGHT_RE = re.compile(r"(?<![\w-])min-height\s*:\s*([0-9.]+)\s*\w*", re.I)


def _attr(tag, name):
    m = re.search(rf"""(?<![\w-]){name}\s*=\s*["']([^"']*)["']""", tag, re.I)
    return m.group(1) if m else ""


def _decls_for(tag, styles):
    """收集作用于该标签的声明块，按"就近优先"排序：style 属性 → #id → .class → 标签名。

    这不是真正的 CSS 级联（不解析后代关系、不算权重叠加），只求够用且不会把话说反：
    选择器只看最后一个复合部分，找不到规则时不下结论（宁可漏报）。标签名选择器要求整条
    选择器就是这个名字——否则 `.card > div{}` 会被当成"所有 div 都有这条声明"。
    """
    sa = _attr(tag, "style")
    tiers = [[sa] if sa else [], [], [], []]
    m0 = re.match(r"<\s*([a-zA-Z][\w-]*)", tag)
    tag_name = (m0.group(1) if m0 else "").lower()
    tag_id = _attr(tag, "id")
    classes = set(_attr(tag, "class").split())
    for m in _RULE_RE.finditer(styles):
        sels, body = m.group(1), m.group(2)
        if "@" in sels:
            continue  # @media / @supports 的块结构本正则解析不了
        for sel in sels.split(","):
            s = sel.strip()
            if not s:
                continue
            key = re.split(r"[\s>+~]+", s)[-1].split(":")[0]
            if tag_id and key == "#" + tag_id:
                tiers[1].append(body)
            elif key.startswith(".") and key[1:] in classes:
                tiers[2].append(body)
            elif s == tag_name:
                tiers[3].append(body)
            else:
                continue
            break
    return [d for tier in tiers for d in tier]


def _state_of(tag, styles):
    for d in _decls_for(tag, styles):
        r = _height_state(d)
        if r is not None:
            return r
    return None


def _ancestor_tags(markup, pos):
    """容器所在位置的祖先开标签，由内向外。"""
    stack = []
    for m in _TAG_RE.finditer(markup, 0, pos):
        closing, name, _attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in ("script", "style"):
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
        elif not selfclose and name not in _VOID_TAGS:
            stack.append((name, m.group(0)))
    return list(reversed(stack))


def _pct_resolves(markup, pos, styles):
    """容器写了百分比高度时，往外找它到底解析成什么。

    True 祖先链上有确定高度 / False 祖先是 auto 高（百分比解析为 0）/ None 追不下去。
    """
    for name, tag in _ancestor_tags(markup, pos):
        decls = _decls_for(tag, styles)
        blob = " ".join(decls)
        if _STRETCH_RE.search(blob) or _MIN_HEIGHT_RE.search(blob):
            return None  # 高度可能来自拉伸或对撑，本脚本追不下去
        st = _state_of(tag, styles)
        if st is True:
            return True
        if st is False:
            return False
        if st == "pct":
            # html 的百分比相对初始包含块（视口）解析，是确定高度，链到此为止。
            if name == "html":
                return True
            continue
        if name == "html":
            return False  # 一路到根都没有确定高度
    return False


def _has_visible_height(markup, container_id, styles, has_external_css):
    """图表容器是否有可见高度（仅对被 echarts.init 直接引用的容器调用）。

    返回 (ok, reason)：reason 区分"没写高度"(none) 与"百分比解析为 0"(pct)——两者修法不同。
    保守原则：只有"页面内所有样式来源都能看到、且都没给高度"时才判缺高度；一旦存在外部
    样式表（高度可能来自那里）就不下结论。
    """
    tag, pos = _find_tag_with_id(markup, container_id)
    if not tag:
        return True, ""  # 容器不存在另有告警覆盖，这里不重复报

    state = _state_of(tag, styles)
    if state == "pct":
        if has_external_css:
            return True, ""
        if _pct_resolves(markup, pos, styles) is False:
            return False, "pct"
        return True, ""
    if state is not None:
        return state, "" if state else "zero"

    # 没写 height，但高度可能来自 flex/grid 拉伸或绝对定位对撑——那时容器有高度，只是本
    # 脚本追不出来。这种情况必须闭嘴：它长得和"压根没写高度"一模一样，而报错方向恰好相反。
    if _STRETCH_RE.search(" ".join(_decls_for(tag, styles))):
        return True, ""
    for _name, atag in _ancestor_tags(markup, pos):
        if _STRETCH_RE.search(" ".join(_decls_for(atag, styles))):
            return True, ""
    return bool(has_external_css), "none"


def check_dom_structure(live, markup, code, script_text):
    """返回 (container_findings, lib_findings, stats)。全部为 warn 级素材。"""
    container, lib = [], []
    styles = _style_blocks(live)
    has_external_css = bool(EXTERNAL_CSS_RE.search(live))

    # 容器 id 重复（只看真实 markup，排除注释区与 JS 字符串模板）
    id_lines = {}
    for m in ID_RE.finditer(markup):
        id_lines.setdefault(m.group(1), []).append(line_of(markup, m.start()))
    for _id, locs in id_lines.items():
        if len(locs) > 1:
            container.append(
                _f(locs[0], f'id "{_id}" 重复定义（行 {"、".join(map(str, locs))}）',
                   hint="容器 id 需唯一；重复会导致 getElementById 只命中第一个")
            )

    # 存在性判定池：真实 markup 的 id ∪ 脚本里动态创建/拼接出的 id
    # （必须用含字符串的 script_text —— 动态容器的 id 只存在于 JS 字符串里）
    dynamic_ids = set(ID_RE.findall(script_text))
    for a, b in DYN_ID_RE.findall(script_text):
        dynamic_ids.add(a or b)
    known_ids = set(id_lines) | dynamic_ids

    # init 引用的容器：只认 code 视图（已抹掉 JS 注释/正则）
    echarts_refs = [
        ((m.group(1) or m.group(2)), line_of(code, m.start())) for m in ECHARTS_INIT_RE.finditer(code)
    ]
    chartjs_refs = [
        ((m.group(1) or m.group(2)), line_of(code, m.start())) for m in CHARTJS_INIT_RE.finditer(code)
    ]

    for label, refs in (("echarts.init", echarts_refs), ("new Chart", chartjs_refs)):
        for rid, ln in refs:
            if rid not in known_ids:
                container.append(
                    _f(ln, f'{label} 引用的容器 id "{rid}" 在页面中不存在',
                       hint="getElementById 会返回 null，图表将无处渲染")
                )

    # 用了图表库却没引库 —— "整页图表全不渲染"的另一成因。用 code 视图判"是否真的调用了"，
    # 用 live 视图判"是否引了库"（引库写在 markup 的 <script src> 或 importmap 里）。
    for label, use_re, import_res, fix in (
        ("echarts", ECHARTS_USE_RE, ECHARTS_IMPORT_RES, "在 <head> 加 <script src=...echarts...>"),
        ("Chart.js", CHARTJS_USE_RE, CHARTJS_IMPORT_RES, "在 <head> 加 <script src=...chart.umd.js...>"),
    ):
        m = use_re.search(code)
        if m and not any(r.search(live) for r in import_res):
            lib.append(_f(line_of(code, m.start()), f"代码使用了 {label} 但页面未引入 {label} 库",
                          hint=f"{fix}，否则整页图表全空"))

    # ECharts 容器高度不成立（容器约定 <div style="width:100%;height:360px;">）
    for rid, ln in echarts_refs:
        if rid not in id_lines:
            continue
        ok, why = _has_visible_height(markup, rid, styles, has_external_css)
        if ok:
            continue
        _tag, pos = _find_tag_with_id(markup, rid)
        if why == "pct":
            msg = f'图表容器 "{rid}" 的百分比高度解析为 0（祖先链上没有确定高度），ECharts 将画不出来'
            hint = ("height:100% 相对包含块解析，包含块高度为 auto 时等于 0。要么给祖先容器一个"
                    '确定高度（px / vh），要么把容器写成 style="width:100%;height:360px;"')
        else:
            msg = f'图表容器 "{rid}" 未设置显式高度，ECharts 将画不出来'
            hint = '容器约定：style="width:100%;height:360px;"'
        container.append(_f(line_of(markup, pos) if pos is not None else ln, msg, hint=hint))

    # Chart.js 的 canvas 上直接写了 CSS height —— 与 ECharts 相反，高度必须给外层 wrapper，
    # 写在 canvas 上会导致尺寸计算错误（水平柱状图尤甚），所以这里查的是"有"而不是"没有"。
    canvases = list(CANVAS_TAG_RE.finditer(markup))
    for m in canvases:
        style_attr = re.search(r"""(?<![\w-])style\s*=\s*["']([^"']*)["']""", m.group(0), re.I)
        if style_attr and _HEIGHT_RE.search(style_attr.group(1)):
            container.append(
                _f(line_of(markup, m.start()), "canvas 元素上直接设了 CSS height，Chart.js 尺寸会算错",
                   hint="高度写在外层 wrapper div（position:relative + height），canvas 本身不设高；"
                        "options 用 responsive:true, maintainAspectRatio:false")
            )

    stats = {
        "ids": len(id_lines),
        "echarts_containers": len(echarts_refs),
        "chartjs_containers": len(chartjs_refs),
        "canvases": len(canvases),
        "uses_chart_lib": bool(ECHARTS_USE_RE.search(code) or CHARTJS_USE_RE.search(code)),
    }
    return container, lib, stats


# ── 源码读取（编码探测）──
_META_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?\s*([\w-]+)""", re.I)


def read_html(path):
    """读源码，返回 (文本, 编码说明|None)。

    交付产物里 GBK/GB18030 的中文页面并不罕见（Windows 编辑器另存），硬按 utf-8 读会直接
    抛 UnicodeDecodeError——一份可能完全正常的页面被判成"无法读取"，是纯误报。
    顺序：utf-8 → <meta charset> 声明的编码 → gb18030（GBK 超集）→ big5 → latin-1 兜底。
    """
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        pass
    candidates = []
    m = _META_CHARSET_RE.search(raw[:4096])
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore").lower())
    candidates += ["gb18030", "big5"]
    for enc in candidates:
        if not enc or enc in ("utf-8", "utf8"):
            continue
        try:
            return raw.decode(enc), f"非 utf-8 源码，已按 {enc} 解码"
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1"), "编码无法确定，已按 latin-1 强行解码，结果可能不准"


# ── 对外唯一入口 ──
def _syntax_checks(scripts, parser, install):
    """返回 (check, parser_kind)。永不抛栈。"""
    if not scripts:
        return _c("js_syntax", "skip", "无内联 <script>，语法项无输入（未校验，不等于通过）"), "none"

    if parser is None:
        try:
            import deps

            parser = deps.ensure_js_parser(install=install)
        except Exception as e:
            parser = {"kind": None, "node": None, "env": None, "detail": f"依赖自举不可用: {str(e)[:120]}"}

    kind = parser.get("kind")
    n = len(scripts)
    try:
        if kind == "node":
            hits = check_syntax_with_node(scripts, parser["node"])
            if hits:
                return _c("js_syntax", "fail", _detail(hits, "→ 该 <script> 块整体不执行，块内所有图表全空")), kind
            return _c("js_syntax", "pass", f"{n} 段内联脚本经 node --check 通过"), kind
        if kind == "esprima":
            hits, ok = check_syntax_with_esprima(scripts, parser.get("env"))
            if ok:
                if hits:
                    return _c("js_syntax", "fail", _detail(hits, "→ 该 <script> 块整体不执行，块内所有图表全空")), kind
                return _c("js_syntax", "pass", f"{n} 段内联脚本经 esprima 通过"), kind
            # 探测时还在、真用时没了（缓存被删等）：按未覆盖处理，不能默认通过
            parser = {**parser, "kind": None, "detail": "esprima 探测到但实际不可用"}
            kind = None
    except Exception as e:
        return _c("js_syntax", "skip", f"语法校验执行异常，未覆盖: {str(e)[:140]}"), "none"

    # 无真解析器：只能做启发式括号配平。配平通过 ≠ 语法正确，故最好也只是"未覆盖"。
    why = parser.get("detail") or "无可用 JS 解析器"
    try:
        hits = heuristic_brace_balance(scripts)
    except Exception as e:
        hits = []
        why += f"；启发式亦失败: {str(e)[:80]}"
    if hits:
        return _c("js_syntax", "warn",
                  _detail(hits, f"（启发式括号配平，仅参考；语法未实测：{why}）")), "none"
    return _c("js_syntax", "skip",
              f"无可用 JS 解析器，语法未校验（不等于通过）：{why}；"
              f"启发式括号配平未发现失配，但配平通过不等于语法正确"), "none"


def checks_for(path, source=None, parser=None, install=True):
    """html 源码层静态校验。返回 checks，永不抛栈。

    checks: [{name,status,detail}]，name ∈ {js_syntax, chart_container, chart_lib, source_encoding}
    parser: 允许调用方复用 deps.ensure_js_parser() 的结果（同进程只自举一次）。
    """
    checks = []
    try:
        html, enc_note = read_html(path)
    except Exception as e:
        if source is None:
            return [_c("js_syntax", "skip", f"源码读取失败，静态校验未覆盖: {str(e)[:140]}")]
        html, enc_note = source, None
    checks.append(
        _c("source_encoding", "warn", enc_note + "（建议统一存为 utf-8 并声明 <meta charset>）")
        if enc_note
        else _c("source_encoding", "pass", "utf-8")
    )

    try:
        live, markup, code, script_text = prepare_views(html)
        scripts = extract_inline_scripts(live)
    except Exception as e:
        checks.append(_c("js_syntax", "skip", f"源码切分异常，静态校验未覆盖: {str(e)[:140]}"))
        return checks

    syntax_check, _ = _syntax_checks(scripts, parser, install)
    checks.append(syntax_check)

    try:
        container, lib, stats = check_dom_structure(live, markup, code, script_text)
    except Exception as e:
        checks.append(_c("chart_container", "skip", f"结构检查异常，未覆盖: {str(e)[:140]}"))
        return checks

    # chart_container：DOM id 唯一性 + 图表容器存在性/高度 + canvas 高度
    n_refs = stats["echarts_containers"] + stats["chartjs_containers"]
    if container:
        checks.append(_c("chart_container", "warn",
                         _detail(container, "（静态推断，可能是外部 CSS 供高或 JS 动态创建，需结合内容判断）")))
    elif stats["ids"] == 0 and n_refs == 0 and stats["canvases"] == 0:
        checks.append(_c("chart_container", "skip", "无 DOM id、无图表容器引用、无 canvas，本项无输入"))
    else:
        checks.append(_c("chart_container", "pass",
                         f"{stats['ids']} 个 id 唯一，{n_refs} 个图表容器引用有效，{stats['canvases']} 个 canvas 无高度冲突"))

    # chart_lib：只在识别到 echarts / Chart.js 直写调用时才有输入
    if lib:
        checks.append(_c("chart_lib", "warn", _detail(lib)))
    elif stats["uses_chart_lib"]:
        checks.append(_c("chart_lib", "pass", "已引入所用图表库"))
    else:
        checks.append(_c("chart_lib", "skip", "未识别到 echarts / Chart.js 直写调用，本项无输入"))

    return checks
