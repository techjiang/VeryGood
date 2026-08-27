---
name: deliverable-verify
description: 交付产物取证技能（只读、不改交付文件）。对 docx/pptx/xlsx/pdf/html 做结构合法性与确定性缺陷校验、正文与链接抽取、链接可用性探测；html 额外做内联 JS 语法自检（一处失配整页图表全空）、图表容器约定检查，并经无头浏览器渲染产出运行时探针、渲染后文本与排版几何审计（连线压穿/贴边、浮框压住正文）。本技能是取证流程的唯一操作说明书。不提供多模态视觉排版审核。
---

# 交付产物取证技能

供**产物校验子代理**在交付前核对**最终交付产物**：只读，不修改/生成任何交付文件。

**职责划分**：本技能负责"**怎么取证**"——跑哪些脚本、怎么读结果、每个结论的严重度；
调用方 prompt 只负责"**怎么下判定**"——把证据翻成逐条 verdict。因此脚本用法只在本文件里
维护一份，调用方不应自行手写解析、探活或截图代码。

## 能力边界（先看清有什么、没有什么）

**提供**：
- 结构合法性：zip 完整性、OOXML 标记、能否被对应库打开、页数/片数/段落数、json 可解析
- 内容确定性缺陷：占位符残留（TODO/待补充/lorem/XXX/`{{var}}`/版式默认文字）、docx 无正文与空白页与单段超页、
  pptx 空白页、pdf 空白页（无文本且无图形对象）、html 引用的本地资源缺失、xlsx 公式错误值
- 排版的代码层代理指标：pptx 形状越出画布（带文字的越界记 fail）、文本框互相压盖、字号过小、
  docx 标题下无正文、pdf 无文本层的页、xlsx 图表数据标注冗余（重复图例/类目轴）与相邻标注压盖
  - html 源码层：内联 JS 语法自检（`node --check` / esprima）、图表容器与引库约定、源码编码
  - html 渲染层：白屏/占位符/裂图/分页漏审探针，以及装饰线压穿/贴边/越出、浮框压字、重复绘制
- **正文与链接抽取**：统一落盘为带定位锚的文本 + 去重链接清单（含只存在于超链接关系里的 URL）
- **链接可用性探测**：能否访问（不评估链接内容）
- 量化基线：`text_chars` / `page_count` / `slides` / `paragraphs` / 每 sheet 行列数

**不提供**：
- **多模态视觉排版审核（本流程不做，不作为能力对外承诺）**。因此 **docx/pptx/pdf 的真实渲染排版
  （配色、层次、美观度、跨元素视觉关系）不在校验范围**，应如实标注"未覆盖"，不得凭空判通过或失败。
- 需求逐条判定、内容正确性判断、链接内容是否支撑正文——这些是调用方的职责。
- OCR；md/txt/csv/json 只做非空/编码/json 解析/占位符；其他类型（图片、音视频、压缩包、代码）
  只确认存在且非空并显式标 `skip`。

## 取证流程（按此执行，勿自行发明步骤）

全程**在会话工作目录下执行**（勿 cd）——所有中间产物落"当前工作目录/.tmp/"。

**第 0 步 建短路径 + 依赖自检（合成一条命令）**

技能 base directory（见 `<skill_location>`）很长、含项目 id 与空格，逐条命令重复拼写既费 token
又容易写错。先在工作目录下把它软链成 `.tmp/dv`，**后续所有命令都用短路径**：

```bash
mkdir -p .tmp && ln -sfn "<base>" .tmp/dv && python3 .tmp/dv/scripts/defect_check.py --doctor --install
```

`ln -sfn` 幂等，重复执行无副作用；软链只是入口、不是产物（`.tmp/` 不会被交付物扫描收走）。
若环境不支持软链（如 Windows 无权限、`ln` 报错），退回用 `"<base>/scripts/xxx.py"` 完整路径。

`--doctor` 输出 `modules` / `binaries` / `capabilities` / `install_mirrors`：哪些维度可用、哪些降级及原因。
`--install` 幂等——已装好的依赖不会重复装，装不上则降级并标注"因缺少 `<dep>`，`<对应维度>` 未校验"，**严禁因环境缺失静默跳过或误报"合格"**。
因此不需要先跑 `--doctor` 看结果再决定加不加 `--install`，直接一体执行即可。
离线环境用 `DUMATE_DELIVERABLE_NO_INSTALL=1` 只探测不安装。

**第 1 步 取证（三类命令在**同一次响应内全部并行发起**，互不依赖，不要串行等待）**
```bash
# ① 每个产物一条：结构与确定性缺陷判定
python3 .tmp/dv/scripts/defect_check.py   <file>
# ② 所有产物一次传入：正文与链接落盘（每个产物一行 JSON；含 html 时 bash timeout 建议 180000）
python3 .tmp/dv/scripts/content_extract.py <file> [<file> ...]
# ③ 所有产物一次传入：链接可用性（默认 10 并发 / 最多 50 条 / 预算 90s，bash timeout 建议 120000）
python3 .tmp/dv/scripts/link_probe.py <file> [<file> ...]
```

**第 2 步 内容核对**：基于 `content_extract.py` 落盘的 `content.txt`（读取纪律见下），对照需求逐条核对。

**类型路由**：

| 扩展名 | defect_check.py | content_extract.py |
|---|---|---|
| docx | zip + 打开 + 无正文 + 占位符 + **空白页(fail)** + 空章节(warn) | 段落(带标题层级) + 表格 + 页眉页脚 + 超链接 |
| pptx | zip + 打开 + 空白页 + 占位符 + 出界 + 重叠(warn) + 字号(warn) | 逐页文本 + 表格 + 备注页 + 超链接 |
| xlsx | zip + 打开 + 公式错误值(soffice 重算) + 占位符 + **图表标注冗余(重复图例/类目轴)与压盖** | 逐 sheet TSV（值优先，无缓存值回退公式文本） |
| pdf | 打开 + 页数 + 空白页 + 无文本层(warn) + 占位符 | 逐页文本 + 书签 + 注解链接 |
| html | 非空 + 结构 + **本地引用存在性(fail)** + **内联 JS 语法(fail)** + 图表容器/引库(warn) + 源码编码(warn) | **无头浏览器渲染** → 渲染后文本 + 运行时探针 + **排版几何审计** + 链接；浏览器不可用时退化为源码去标签 |
| md/txt/csv/json | 非空 + 编码 + json 解析 + 占位符 | 不支持 |
| 其他 | 仅确认存在且非空，标 `skip` | 不支持 |

## 输出契约与判定档位

### `defect_check.py`：结构与确定性缺陷

字段：`openable`、`format_valid`（无 fail 级缺陷）、`checks[]`{`name`,`status`,`detail`}，
按类型附 `page_count`/`slides`/`sheets`/`charts`/`paragraphs`/`text_chars`/`images`/`formula_check_mode`。

**`status` 三档，语义不可混用**：

- `fail` = **确定性缺陷**，证据充分 → 对应 must 判不满足。
  含：`zip_integrity`/`ooxml_marker`/`library_open` 失败、`non_empty` 失败（docx 无文本且无图无表、
  pptx 无片、pdf 空白页）、`empty_slide`、`blank_page`（docx 空白页，仅当有实测几何或硬分页符支撑时判 fail）、
  `page_overflow`（docx 单段独占一页
  仍放不下，必被裁切）、`placeholder`、`out_of_bounds`、`formula_error`、`local_refs`、`json_parse`、
  `js_syntax`失败（内联脚本语法错误导致 `<script>` 块整体不执行，块内所有图表全空）、
  `chart_labels`（xlsx 图表标注既重复图例/类目轴内容、又估算出相邻标注压盖 —— 冗余与压盖同时成立）。
- `warn` = **启发式参考信号**，可能是设计意图 → 记入证据，**单独不足以判 must 不满足**。
  含：`text_overlap`、`tiny_font`、`empty_section`、`text_layer`（pdf/docx 整页图片或矢量输出属正常）、
  `blank_page`/`blank_page_suspect`（docx 疑似空白页，无硬证据：成因为分节符切页或渲染器行距实现）、`html_structure`、
  `chart_container`（id 重复 / 容器不存在 / ECharts 高度不成立 / Chart.js 在 canvas 上设高）、
  `chart_lib`（用了图表库未引库）、`source_encoding`（非 utf-8，已按声明编码解码）、
  `chart_labels`（xlsx 图表标注只命中冗余或只命中压盖之一：前者可能是刻意标注，后者的标注宽度是
  不建模自动换行的上界）。
- `skip` = **未覆盖**（依赖缺失或数据不足）→ 如实标注，既不算通过也不算失败。
- `pass` = 已实测且无问题。

`formula_check_mode`：`recalc`（soffice 重算，最可信）/ `cached`（读文件内缓存值）/
`no_formula` / `unavailable`（未覆盖，对应 `skip`）。

### `content_extract.py`：正文与链接

**每个产物输出一行 JSON**（多产物就是多行），字段：`content_file`、`links_file`、`text_chars`、
`lines`、`truncated`、`outline`（≤80 条）、`links_count`、`meta`、`notes`、`checks`。**正文不进 stdout。**

`content.txt` 每行前缀定位锚，grep 命中即自带位置：
```
[docx:p12|H1] 第一章 概述        # docx 段落 12，标题 1 级
[docx:t1r2] 覆盖率	98%          # docx 第 1 张表第 2 行
[pptx:s3] 页面文字 / [pptx:s3n] 备注
[xlsx:汇总!R5] 单元格按列 TAB 分隔
[pdf:p7] 第 7 页文本
[html:l12] 渲染后文本第 12 行
```

**读取纪律（务必遵守，否则一份长报告会把上下文打满）**：
- `outline`（已在 stdout 里）可直接通读，用来判断结构、章节、页数是否符合需求。
- `checks` 当前为html产物排版校验结果，验证是否存在重叠/超出/覆盖等问题，为空就是脚本没量出问题——**它不是"产物合格"的结论**。
  内容是否满足需求仍然只能由你读 `content.txt` 自己判断。`checks` 非空时按里面写的问题直接采信，不必再去找证据复核。
- 正文**只允许 `grep`**（带行号与少量上下文）或按锚点定点读片段；证据指针直接引用锚点。
- 仅当 `text_chars < 8000` 时才允许整读 `content.txt`。
- `text_chars` 只计正文，不含前缀锚点，量化判据（字数、篇幅）按它算。
- `truncated=true` 表示正文超出上限被截断 → 未读部分按"未覆盖"标注，必要时抬高 `--max-chars` 重跑。
- `notes` 必读：里面写明了降级情况（如库缺失、行列截断、html 退化为源码去标签）。
- **html 专有：先看 `meta.text_origin`**。`rendered_text` = 正文来自无头浏览器渲染后的 innerText，
  可信；`source_stripped` = 浏览器不可用、退化成源码去标签，此时 **JS 动态生成的内容不在正文里**
  （`notes` 会写明原因），不得凭"正文里没有"判内容缺失，运行时与排版维度一律按"未覆盖"标注。
- 同一产物重复调用 extract 不会重复付浏览器开销：已有且不比产物旧的渲染文本会被直接复用；
  渲染失败也会被记下，同一轮内不重复重试（`notes` 里带"本轮已尝试过"）。产物被修复重写后
  自动重新渲染。

### `link_probe.py`：链接可用性（只判能否访问）

字段：`total`、`checked`、`sampled`、`not_checked`、`budget_exhausted`、`no_egress_suspected`、
`scanned[]`{`file`,`links`,`origin`}、`notes[]`、`results[]`{`url`,`status`,`code`,`detail`,`layer`,`where`}。

默认 10 并发、最多探测 50 条链接、预算 90s；超过 50 条时按域名抽样（每域名至少 1 条）。
多产物一次传入时按 URL 全局去重，`where` 形如 `报告.docx:段落12`、`deck.pptx:第3页`。
`scanned[].origin=parsed` 表示链接是本脚本自己解析的（extract 还没跑完），`cached` 表示复用了 `links.json`。
html 自己解析时只读源码抽链接（`href`/`src` 与正文裸链），**不触发浏览器渲染**，不会和 extract 抢会话。

**`status` 三档**：
- `ok` = 2xx/3xx，链接此刻可访问。
- `dead` = 404/410、DNS 解析失败、连接被拒 → 链接不存在或已失效，是确定性缺陷。
- `unknown` = 401/403/429/5xx、超时、SSL 异常 → 可能是鉴权、风控或环境限制，
  **不得据此判产物缺陷**。
- `no_egress_suspected=true`（≥3 个域名全部栽在网络层且无一成功）→ 判定为环境无外网，
  该批 `dead` 会自动降级为 `unknown`；此时链接维度整体按"未覆盖"处理。
- `sampled=true` / `not_checked` 非空 → 未探测的链接按"未覆盖"标注，不要当成 ok。

## 资源说明

### scripts/
- `defect_check.py`：结构 + 确定性缺陷判定（主手段）；`--doctor [--install]` 依赖自检与自动补装。
- `content_extract.py`：正文与链接抽取，纯路由 —— 按类型 import `extractors/<type>.py`，落盘 content.txt / links.json；
  可一次传多个产物，多个 html 合并进同一浏览器会话渲染。
- `extractors/`：分类型**内容抽取**实现（`docx` / `pptx` / `xlsx` / `pdf` / `html`）+ `common.py`
  （URL 抽取、OOXML 超链接关系解析）。`defect_check.py` 复用其中的解析工具函数，保证口径一致。
- `checkers/`：分类型**结构校验**内核 —— `docx_pages.py`（docx 静态页模型：按分页符/节切页 +
  段落高度推演 → 空白页、单段超页）、`xlsx_charts.py`（xlsx 图表数据标注：成分是否重复图例/类目轴
  已表达的内容——`showSerName`/`showCatName`/`showLegendKey` 未显式关闭时渲染器会一并画出，
  以及按图框尺寸估算相邻标注是否压盖 → `chart_labels`）、`html_static.py`（html 源码层：内联 JS 语法、
  图表容器与引库、源码编码）、`html_layout_audit.js`（html 渲染后排版几何：线-框、浮框-正文行、重复绘制，由
  `browser.py` 在 html 渲染的同一个浏览器会话里 `page.evaluate` 执行，结果由 `extractors/html.py`
  归档成 `checks[]` 里的 `layout_*` 项）。均由主流程调用、按同一套 `status` 四档回报；不单独执行。
- `link_probe.py`：链接可用性探测（可直传产物路径、跨产物全局去重、按域名抽样、HEAD→GET 回落、
  三档判定、无外网识别）；取链接复用 `content_extract` 的实现，故与它无先后依赖。
- `deps.py`：依赖自举 —— PyPI **国内源优先**（清华 → 阿里 → 官方）、`pip install --target` 到技能
  缓存（默认 `~/.cache/dumate-deliverable-verify`，不碰系统环境）、并发安装文件锁、JS 解析器
  探测与按需安装。开关：`DUMATE_DELIVERABLE_MIRROR`(auto|cn|official) /
  `DUMATE_DELIVERABLE_CACHE` / `DUMATE_DELIVERABLE_NO_INSTALL`。
- `browser.py`：html 渲染引擎——`dumate-browser-cli` 驱动无头浏览器（`open --file` 优先，
  这样外链 css/js 才按真实路径解析；页内导航被守卫拒时就地取证并把
  `probe.load_events` 标为 `unavailable`，都打不开才回落 `setContent`；`--no-shots` 只取探针、
  渲染文本与排版几何，本流程只用这条路径）。由
  `extractors/html.py` 内部调用，不需要单独执行。office/pdf 渲染成图（`soffice`+`pdftoppm`）本流程不使用。
  排版几何可用 `DUMATE_DELIVERABLE_LAYOUT_AUDIT=0` 关闭（关闭后几何整体按未覆盖处理）。
- `visual_check.py`：多模态视觉排版审核，**本流程不调用**（实现保留，需显式置
  `DUMATE_DELIVERABLE_VISUAL_CHECK=1` 才启用）。
