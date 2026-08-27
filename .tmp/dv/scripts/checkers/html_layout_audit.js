// 排版几何审计（只读）：检出「装饰线压穿内容框」「装饰线贴在内容框边上 / 越出框外」
// 「脱离文档流的浮框压住正文」与「同一段线被画了两遍」。
//
// 由 browser.py 在 html 渲染的**同一个浏览器会话**里经 page.evaluate 执行（本文件去掉
// `window.__LAYOUT_AUDIT =` 赋值后即是一个可直接传给 evaluate 的箭头函数），结果并入
// probe.layout。不新增浏览器会话、不往产物目录写任何文件。
// 也可单独引入调试：加载后调用 window.__LAYOUT_AUDIT()。
//
// 为什么必须有真实 layout：判据是渲染后的坐标。CSS 源码本身完全合法
// （`li::before{top:0;border-top:2px solid}` 挑不出错，`.callout{position:absolute}`
// 更是天天写），错的是它在真实 layout 里正好落到卡片边框那一行、或正好压在正文上
// ——纯静态正则不可能知道 `top:96px` 解析出来会盖住哪几行字。
//
// 判定口径刻意保守（宁漏不误）：排版审计天生比语法审计更容易误报，而一个爱喊狼来了的
// 校验器会被使用者学会忽略，所以这里的门槛比语法检查更高。各处取舍见下方注释。
window.__LAYOUT_AUDIT = () => {
  const MAX_EL = 4000;      // 超大页面截断，防止 O(线×框) 爆炸
  const MAX_TEXT = 2500;    // 文本行盒上限，同上
  const MAX_FIND = 30;
  const EPS = 2;            // 「贴边」阈值：2px 内视为同一条边
  const THIN = 4;           // 细条判定：短边 ≤4px 才算装饰线
  const PROTRUDE = 6;       // 越出阈值：≥6px 才算「明显突出」，避免 1~2px 的抗锯齿噪声
  const COVER_W = 24;       // 压住正文：横向至少盖住 24px（约两个汉字）才算
  const COVER_H = 0.35;     // 纵向至少盖住该行行高的 35%，避免擦边噪声
  const OVERLAY_AREA = 0.5; // 面积超过视口一半的浮层按 modal / 遮罩看待，不判
  const FIXED_BAR_SPAN = 0.8; // fixed 元素横跨视口某一边 80% 以上才按「栏」看待（见 panels）
  const out = { line_on_box: [], box_over_text: [], coincident_lines: [], counts: {}, truncated: false };
  // 因几何不可信（旋转/缩放）而放弃的候选装饰线数。必须回传：否则「一条线都没查到」
  // 和「有线但全被跳过」在结果里长得一模一样，后者是漏报而前者不是。
  let skipped = 0;
  // 与内容框相交、但经命中测试确认被框的实底盖住（页面上看不见）的线数。
  // 单独记一笔而不是静默丢掉：这是本校验器主动放行的一类重叠，数量应当可见。
  let hiddenLines = 0;
  // 与正文行重叠、但经命中测试确认正文画在浮框之上（字看得见）的行数，同上。
  let hiddenCovers = 0;


  const all = document.querySelectorAll("body *");
  out.truncated = all.length > MAX_EL;
  const els = [...all].slice(0, MAX_EL);

  const opaque = (c) => {
    if (!c || c === "transparent" || c === "none") return false;
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return true;
    const p = m[1].split(",").map(parseFloat);
    return p.length < 4 || p[3] > 0.08;
  };
  // 「压住正文」要求的是**真的挡住**，比装饰线的 opaque 门槛高得多：
  // 半透明色带压在文字上是高亮/水印这类设计手法，字还看得见；alpha>0.5 才算遮挡。
  const solid = (c) => {
    if (!c || c === "transparent" || c === "none") return false;
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return true;
    const p = m[1].split(",").map(parseFloat);
    return p.length < 4 || p[3] > 0.5;
  };
  const shown = (st) => st.display !== "none" && st.visibility !== "hidden" && parseFloat(st.opacity || "1") > 0.08;
  const label = (el, pe) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    else if (typeof el.className === "string" && el.className.trim())
      s += "." + el.className.trim().split(/\s+/).slice(0, 2).join(".");
    return (s + (pe || "")).slice(0, 90);
  };
  const textOf = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();
  const padBox = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return {
      l: r.left + (parseFloat(s.borderLeftWidth) || 0), t: r.top + (parseFloat(s.borderTopWidth) || 0),
      r: r.right - (parseFloat(s.borderRightWidth) || 0), b: r.bottom - (parseFloat(s.borderBottomWidth) || 0),
    };
  };
  // 独立 transform 属性（rotate / scale / translate）**不体现在 computed `transform` 里**
  // ——实测 Chrome 下 `rotate:45deg` 的 computed transform 仍是 "none"。这三个属性自 2022 年
  // 起在各浏览器都是基线功能，不是边缘写法，所以每处「几何是否可信」「是否形成包含块」的
  // 判断都必须一并看它们，否则这类元素既不被跳过也不计入 skipped：拿未旋转的坐标去量一条
  // 斜线，会凭空报出一个 P0，而且使用者在 WARN 里看不到任何「这里没敢查」的痕迹。
  const identRotate = (v) => !v || v === "none" || /^0(deg|rad|grad|turn)?$/.test(v.trim());
  const identScale = (v) => !v || v === "none" || /^1(\s+1){0,2}$/.test(v.trim());
  const hasTransformProps = (st) =>
    st.transform !== "none" || !identRotate(st.rotate) || !identScale(st.scale) ||
    (st.translate && st.translate !== "none");

  // 是否为绝对定位后代的包含块。除 position 外，transform / filter / perspective /
  // contain / backdrop-filter 都会让元素成为包含块 —— 少认一个，伪元素的坐标就会按更外层的
  // 祖先解析，算出的 x/y 偏到别处。
  const positioned = (st) =>
    st.position !== "static" || hasTransformProps(st) || st.filter !== "none" ||
    (st.perspective && st.perspective !== "none") ||
    (st.backdropFilter && st.backdropFilter !== "none") ||
    /paint|layout|strict|content/.test(st.contain || "");

  // 绝对定位盒的包含块 = 最近「已定位」祖先的 padding box。
  // 伪元素的宿主自己就是候选 —— 从 el 起算，不能从 el.parentElement 起算，
  // 否则 `ul::before{left:50%}` 会按 li 的宽度去解析，算出的 x 偏到别处。
  const containingBlock = (el, forPseudo) => {
    let p = forPseudo ? el : el.parentElement;
    for (; p; p = p.parentElement) if (positioned(getComputedStyle(p))) return padBox(p);
    const de = document.documentElement;
    return { l: 0, t: 0, r: de.clientWidth, b: de.clientHeight };
  };

  // 矩形几何是否可信：只认纯平移。有旋转/缩放时这套矩形几何不成立，直接放弃——
  // 宁可漏报，也不能拿算错的坐标去指控一份正常的产物。
  const matrixTranslate = (tf) => {
    if (!tf || tf === "none") return [0, 0];
    const m = tf.match(/^matrix\(([^)]+)\)$/);
    if (!m) return null;                    // matrix3d 等一律按不可信处理
    const v = m[1].split(",").map(parseFloat);
    if (v.length !== 6 || v[0] !== 1 || v[1] !== 0 || v[2] !== 0 || v[3] !== 1) return null;
    return [v[4], v[5]];
  };
  // 真实元素只需判「可信/不可信」：getBoundingClientRect 已含全部变换，
  // 纯平移时它就是那条线本身，有旋转/缩放时它退化成外接矩形。
  const rectTrusted = (st) =>
    matrixTranslate(st.transform) !== null && identRotate(st.rotate) && identScale(st.scale);
  // 伪元素的盒子要手算，所以除「可信」外还得拿到确切平移量。translate 用百分比时
  // 取决于自身尺寸，解析容易出错，一律按不可信处理（计入 skipped，不硬判）。
  const pseudoTranslate = (st) => {
    const t = matrixTranslate(st.transform);
    if (!t || !identRotate(st.rotate) || !identScale(st.scale)) return null;
    const tp = (st.translate || "none").trim();
    if (tp === "none" || tp === "") return t;
    const parts = tp.split(/\s+/);
    if (parts.some((p) => p.includes("%"))) return null;
    return [t[0] + (parseFloat(parts[0]) || 0),
            t[1] + (parts.length > 1 ? parseFloat(parts[1]) || 0 : 0)];
  };

  // ── 绘制顺序：谁真的盖住谁 ──────────────────────────────────────────
  // 「重叠」不等于「遮挡」。装饰色块写在文字之前、时间轴中轴线从不透明年份标签背后
  // 穿过，都是重叠但正确的排版 —— 只有被盖住的那一方才是缺陷。
  //
  // 判据不自己算，而是问浏览器：elementFromPoint 做的就是命中测试，层叠上下文、
  // z-index:auto、文档序、transform 全都算在里面。用 z-index 比大小判不出这件事
  // （static 元素上 z-index 根本不生效，跨层叠上下文的 z 值也不能直接比），
  // 而重写一遍 CSS 绘制顺序必然出错，所以这里直接采信真实命中结果。
  //
  // 两个必须处理的坑：
  //   1. elementFromPoint 只认**视口内**坐标。长页面里折线以下的内容一律返回 null，
  //      所以先滚到能看见目标点的位置再测。几何量早在 scroll=0 时收完，不受影响。
  //   2. pointer-events:none 会让命中测试穿过该元素，把「它在上面」读成「不在上面」。
  //      这类元素不采信命中结果。
  const docEl = document.documentElement;
  // 几何量全部是 getBoundingClientRect 给的**视口坐标**，而命中测试要在滚动之后做，
  // 所以先记下收集时的滚动位置，把视口坐标折算成文档坐标再传给 hitAt。
  const baseX = window.scrollX, baseY = window.scrollY;
  let hitBudget = 400;            // 命中测试会强制重排，给个上限防止病态页面卡住
  const hitAt = (docX, docY) => {
    if (hitBudget-- <= 0) return null;
    const vw = docEl.clientWidth, vh = docEl.clientHeight;
    if (docX < window.scrollX || docX >= window.scrollX + vw
        || docY < window.scrollY || docY >= window.scrollY + vh) {
      const maxX = Math.max(0, docEl.scrollWidth - vw), maxY = Math.max(0, docEl.scrollHeight - vh);
      window.scrollTo(Math.max(0, Math.min(docX - vw / 2, maxX)),
                      Math.max(0, Math.min(docY - vh / 2, maxY)));
    }
    const x = docX - window.scrollX, y = docY - window.scrollY;
    if (!(x >= 0 && y >= 0 && x < vw && y < vh)) return null;   // 滚过去也进不了视口
    return document.elementFromPoint(x, y);
  };
  // 返回 true = 该点上 expectEl（或其后代）确实是最上面那一层；false = 不是；null = 判不了。
  // 入参是视口坐标（与各处 rect 同一坐标系），内部折算成文档坐标。
  //
  // `guard` 是「若它在上则应上报」的那一方 —— 也就是这个豁免一旦判错就会造成漏报的一方。
  // 它写了 pointer-events:none 时命中测试会直接穿过它，结果必然偏向豁免，不可采信；
  // 它是 fixed 时只有在收集几何时的滚动位置上测才算数（fixed 元素随视口走）。
  const topIs = (vx, vy, expectEl, guard) => {
    if (guard.noHit) return null;
    if (guard.fixed) window.scrollTo(baseX, baseY);
    const hit = hitAt(vx + baseX, vy + baseY);
    if (!hit) return null;
    if (guard.fixed && (window.scrollX !== baseX || window.scrollY !== baseY)) return null;
    return hit === expectEl || expectEl.contains(hit);
  };


  // 伪元素 border box。getComputedStyle 对伪元素给的是 used 值（百分比已解析、
  // width/height 是 content box），故需补回 padding + border。
  // margin 必须一并算进去：`left:50%; margin-left:-1px` 把线自身宽度居中回来、
  // `margin-left:-150px` 让横向总线居中，都是树形图/组织架构图里的常规写法，
  // 而偏移量（1px~150px）远超 EPS，忽略它算出的坐标会整条线错位。
  const pseudoBox = (el, ps) => {
    const cb = containingBlock(el, true);
    const num = (v) => (v === "auto" || v == null || v === "" ? null : parseFloat(v));
    const px = (v) => parseFloat(v) || 0;
    const bl = px(ps.borderLeftWidth), br = px(ps.borderRightWidth);
    const bt = px(ps.borderTopWidth), bb = px(ps.borderBottomWidth);
    const w = (num(ps.width) || 0) + bl + br + px(ps.paddingLeft) + px(ps.paddingRight);
    const h = (num(ps.height) || 0) + bt + bb + px(ps.paddingTop) + px(ps.paddingBottom);
    // margin 用百分比时相对包含块宽度，computed 值已是解析后的 px；仍带 % 说明拿不到
    // 确切值，按不可信处理。
    if (/%/.test(`${ps.marginLeft}${ps.marginTop}${ps.marginRight}${ps.marginBottom}`)) return null;
    const ml = px(ps.marginLeft), mt = px(ps.marginTop);
    let left = num(ps.left), top = num(ps.top);
    if (left === null) {
      const right = num(ps.right);
      if (right === null) return null;
      // 按 right 定位时，让位的是 margin-right
      left = cb.r - cb.l - right - w - px(ps.marginRight);
    } else {
      left += ml;
    }
    if (top === null) {
      const bot = num(ps.bottom);
      if (bot === null) return null;
      top = cb.b - cb.t - bot - h - px(ps.marginBottom);
    } else {
      top += mt;
    }
    const tr = pseudoTranslate(ps);
    if (!tr) return null;
    const x = cb.l + left + tr[0], y = cb.t + top + tr[1];
    return { l: x, t: y, r: x + w, b: y + h };
  };

  const lines = [], boxes = [], panels = [], textRuns = [];
  let textTrunc = false;
  // 全屏遮罩的最低 z-index。有遮罩就说明页面处于「模态层」状态：遮罩之上的弹窗盖住
  // 底下的正文正是它的设计意图，不是缺陷。没有这条规则，任何 modal 页面都会被误报，
  // 而误报一次就够让使用者学会忽略这个校验器了。
  let maskZ = Infinity;
  const pushSeg = (owner, tag, box, orient, extra) => {
    const w = box.r - box.l, h = box.b - box.t;
    if (w < 0 || h < 0) return;
    lines.push({ owner, tag, ...box, orient, w, h, ...(extra || {}) });
  };
  // 一个盒子的四条可见边框各自是一条线段（长轴沿该边）。
  const pushBorders = (owner, tag, box, st, extra) => {
    const sides = [
      ["Top", "h", { l: box.l, t: box.t, r: box.r, b: box.t + (parseFloat(st.borderTopWidth) || 0) }],
      ["Bottom", "h", { l: box.l, t: box.b - (parseFloat(st.borderBottomWidth) || 0), r: box.r, b: box.b }],
      ["Left", "v", { l: box.l, t: box.t, r: box.l + (parseFloat(st.borderLeftWidth) || 0), b: box.b }],
      ["Right", "v", { l: box.r - (parseFloat(st.borderRightWidth) || 0), t: box.t, r: box.r, b: box.b }],
    ];
    for (const [side, orient, seg] of sides) {
      if ((parseFloat(st["border" + side + "Width"]) || 0) < 1) continue;
      if (st["border" + side + "Style"] === "none" || !opaque(st["border" + side + "Color"])) continue;
      if ((orient === "h" ? seg.r - seg.l : seg.b - seg.t) < 8) continue;
      pushSeg(owner, tag + "/border-" + side.toLowerCase(), seg, orient, extra);
    }
  };

  for (const el of els) {
    const st = getComputedStyle(el);
    if (!shown(st)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;

    // 内容框：三边以上有边框、或有不透明底色，且带文字、够大
    let sides = 0;
    for (const s of ["Top", "Bottom", "Left", "Right"])
      if ((parseFloat(st["border" + s + "Width"]) || 0) >= 1 && opaque(st["border" + s + "Color"])) sides++;
    if (r.width >= 24 && r.height >= 24 && (sides >= 3 || opaque(st.backgroundColor)) && textOf(el))
      boxes.push({ el, l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height,
                   tag: label(el), text: textOf(el).slice(0, 24),
                   // 底色够实才能真的把线遮住 —— 只有这种框才配得上「线在框后面，看不见，
                   // 不是缺陷」这条豁免（见检查一里的绘制顺序判定）。
                   solidBg: solid(st.backgroundColor) });

    // 浮框（脱离文档流的实心面板）：候选「压住正文」的一方。
    // 只收 absolute/fixed —— 普通流里的盒子不可能压住正文，流本身会给它让位；
    // float 也不收，那正是「文字环绕」的正确写法，环绕就是不重叠。
    if (st.position === "absolute" || st.position === "fixed") {
      const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
      const vwArea = Math.max(1, vw * vh);
      const zi = parseInt(st.zIndex, 10) || 0;
      // 先认遮罩：铺满大半个视口、有任何非透明底色的浮层就是 modal 遮罩 / 抽屉。
      // 这一判定**不能**复用下面的 solid()：遮罩的典型写法正是 rgba(0,0,0,.5)，
      // 恰好卡在 solid 的门槛上。记下它的 z-index —— 它之上的一切都属于「模态层」，
      // 弹窗盖住底下正文是设计意图而非缺陷（见 maskZ 的使用处）。
      if ((r.width * r.height) / vwArea >= OVERLAY_AREA && opaque(st.backgroundColor)) {
        maskZ = Math.min(maskZ, zi);
      } else if (r.width >= 40 && r.height >= 24
                 && (solid(st.backgroundColor) || sides >= 3)
                 && rectTrusted(st)) {
        // 要求不透明底色或三边以上边框：否则挡不住字，也就不是缺陷。
        // fixed 元素额外记一笔「是否成条」：吸顶/吸底栏、固定侧栏横跨整条视口边，正文
        // 没有别处可去，缺的是留白；而角上的回到顶部按钮、角标、小浮窗**就是**要浮在
        // 内容之上的设计意图，它压住一行字不是 bug。两者几何上的差别正是「是否横跨
        // 视口的一整条边」，用它做闸门比用面积或位置都稳。真正的剔除放在遍历之后，
        // 与模态层判定同一处 —— 否则模态弹窗（也是不成条的 fixed）会先被当成角落浮窗。
        panels.push({ el, l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height,
                      tag: label(el), pos: st.position, z: zi,
                      noHit: st.pointerEvents === "none", fixed: st.position === "fixed",
                      bar: r.width >= vw * FIXED_BAR_SPAN || r.height >= vh * FIXED_BAR_SPAN });
      }
    }

    // 装饰线：只认「绝对/固定定位」的细条与其边框。
    // 普通流元素的边框贴着邻居是正常排版（表格、列表分隔线），收进来只会制造噪声。
    const thinEnough = (w, h) => Math.min(w, h) <= THIN && Math.max(w, h) >= 8;
    if (st.position === "absolute" || st.position === "fixed") {
      const box = { l: r.left, t: r.top, r: r.right, b: r.bottom };
      // 元素自己的 getBoundingClientRect 已含 transform，但旋转/缩放后它是**外接矩形**，
      // 不再是那条线本身；此时几何不可信，计入 skipped 而不是硬判。
      if (!rectTrusted(st)) {
        if (thinEnough(r.width, r.height)) skipped++;
      } else {
        const meta = { noHit: st.pointerEvents === "none", fixed: st.position === "fixed" };
        if (thinEnough(r.width, r.height) && opaque(st.backgroundColor))
          pushSeg(el, label(el), box, r.width <= r.height ? "v" : "h", meta);
        pushBorders(el, label(el), box, st, meta);
      }
    }
    for (const pe of ["::before", "::after"]) {
      const ps = getComputedStyle(el, pe);
      if (!ps || ps.content === "none" || !shown(ps)) continue;
      if (ps.position !== "absolute" && ps.position !== "fixed") continue;
      const box = pseudoBox(el, ps);
      if (!box) {
        // pseudoBox 返回 null 的两种原因都是「算不准」：定位缺边（left/right 皆 auto）
        // 或 transform 非纯平移。都算放弃，不算「此处无线」。
        skipped++;
        continue;
      }
      const w = box.r - box.l, h = box.b - box.t;
      const meta = { noHit: ps.pointerEvents === "none", fixed: ps.position === "fixed" };
      if (thinEnough(w, h) && opaque(ps.backgroundColor))
        pushSeg(el, label(el, pe), box, w <= h ? "v" : "h", meta);
      pushBorders(el, label(el, pe), box, ps, meta);
    }
  }
  // 两类「不是缺陷」的浮框在这里一并剔除。必须放在元素遍历**之后**：遮罩在文档里通常
  // 写在弹窗前面、但也可能写在后面，遍历途中还不知道 maskZ 的最终值。
  // 放在这里也顺带省掉了「整页只有 modal」时白收一遍文字行盒的开销。
  //   1. 模态层之上的浮框 —— 弹窗盖住底下正文正是它的本职工作。
  //   2. 不成条的 fixed 角落浮元素 —— 回到顶部按钮、角标、小浮窗本来就要浮在内容之上。
  //      顺序上必须先扣掉模态层：模态弹窗同样是「不成条的 fixed」，若先按角落浮窗放行，
  //      它就不会计入 modal_panels，报告里「有几个浮框按模态层放行」这句话会失真。
  const modalPanels = panels.filter((p) => p.z >= maskZ).length;
  const kept = panels.filter((p) => p.z < maskZ);
  const designFixed = kept.filter((p) => p.fixed && !p.bar).length;
  panels.splice(0, panels.length, ...kept.filter((p) => !(p.fixed && !p.bar)));

  // 正文行盒：用 Range 逐个文本节点取 getClientRects()，拿到的是**每一行**的矩形，
  // 而不是整段的外接矩形。这一步不能省 —— 一个 3 行的 <p> 外接矩形横跨整个栏宽，
  // 右侧浮框跟它必然「相交」，用段级矩形判会把所有右浮框都误报成压字。行级才知道
  // 究竟是哪几行被盖住、盖了多少。
  if (panels.length) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const pe = n.parentElement;
        if (!pe || pe.closest("script,style,noscript,template")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const rng = document.createRange();
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (textRuns.length >= MAX_TEXT) { textTrunc = true; break; }
      const host = n.parentElement;
      const hst = getComputedStyle(host);
      if (!shown(hst)) continue;
      // 浮框自己的文字不算「被压的正文」——它在浮框里本来就该在浮框上面。
      if (panels.some((p) => p.el === host || p.el.contains(host))) continue;
      rng.selectNodeContents(n);
      for (const r of rng.getClientRects()) {
        if (r.width < 4 || r.height < 4) continue;
        textRuns.push({ host, hz: parseInt(hst.zIndex, 10) || 0,
                        l: r.left, t: r.top, r: r.right, b: r.bottom, h: r.height,
                        text: (n.nodeValue || "").replace(/\s+/g, " ").trim().slice(0, 20) });
        if (textRuns.length >= MAX_TEXT) { textTrunc = true; break; }
      }
    }
    rng.detach && rng.detach();
  }

  out.counts = { boxes: boxes.length, lines: lines.length, skipped_lines: skipped,
                 panels: panels.length, modal_panels: modalPanels,
                 design_fixed: designFixed, text_runs: textRuns.length };

  // —— 检查一：装饰线与内容框的边重合 / 越界 ——
  // 只判「与该边平行」的线：垂直落线止于卡片顶边是树图正常的 T 型接头，不算缺陷。
  const finds = new Map();
  const add = (kind, seg, box, detail) => {
    const key = kind + "|" + seg.tag + "|" + box.tag;
    let g = finds.get(key);
    if (!g) finds.set(key, (g = { kind, line: seg.tag, box: box.tag, count: 0, examples: [] }));
    g.count++;
    if (g.examples.length < 3) g.examples.push(detail);
  };
  for (const seg of lines) {
    for (const box of boxes) {
      if (seg.owner === box.el) continue;         // 卡片自己的装饰条贴自己的边，是设计
      if (box.el.contains(seg.owner)) continue;   // 线嵌在卡片内部
      const horiz = seg.orient === "h";
      // 沿边方向要有足够重叠，才算「这条线与这个框有关系」。
      const along = horiz
        ? Math.min(seg.r, box.r) - Math.max(seg.l, box.l)
        : Math.min(seg.b, box.b) - Math.max(seg.t, box.t);
      if (along < Math.min(24, (horiz ? box.w : box.h) * 0.5)) continue;

      // 横跨方向必须看**线的中轴**落在哪，不能看重叠量：一条 2px 细线无论怎么压穿卡片，
      // 重叠量最多也只有 2px，用重叠量判定会把「压穿」误当成「差一点没碰上」。
      const axis = horiz ? (seg.t + seg.b) / 2 : (seg.l + seg.r) / 2;
      const near = horiz ? box.b : box.r;         // 线在框的「后边」
      const far = horiz ? box.t : box.l;          // 线在框的「前边」
      const lo = Math.min(far, near), hi = Math.max(far, near);
      if (axis > lo + EPS && axis < hi - EPS) {
        // 中轴落在框内 ≠ 看得见。时间轴的中轴线从不透明年份标签背后穿过是正确写法：
        // 那条线确实与标签相交，但被标签的实底盖住，页面上根本看不到。用真实命中测试
        // 确认到底谁在上面，只在**框有实底、且框确实盖在线之上**时豁免。
        // 贴边一类不做这个豁免：那时线正落在框的边框像素上，命中测试必然返回框本身，
        // 无法区分「被盖住」与「压着边框画」。
        const mid = horiz
          ? [(Math.max(seg.l, box.l) + Math.min(seg.r, box.r)) / 2, axis]
          : [axis, (Math.max(seg.t, box.t) + Math.min(seg.b, box.b)) / 2];
        if (box.solidBg && topIs(mid[0], mid[1], box.el, seg) === true) {
          hiddenLines++;
          continue;
        }
        add("line_crosses_box", seg, box, {
          text: box.text, inset_px: Math.round(Math.min(axis - lo, hi - axis)), at: Math.round(axis),
        });
        continue;
      }
      const d = Math.min(Math.abs(axis - near), Math.abs(axis - far));
      if (d > EPS) continue;
      const edge = Math.abs(axis - near) <= EPS ? (horiz ? "bottom" : "right") : horiz ? "top" : "left";
      // 越出量一并带上，但**不单独作为一类缺陷**：横向总线比单个子卡片宽是 T 型接头的常态
      // （正常树图里总线在卡片下方 28px 处，越出 15px 完全正确）。只有「贴边」才是缺陷，
      // 越出是它的伴生症状——同一个 CSS 错误的两种可见后果，报成两条只会让人以为有两个 bug。
      const p1 = Math.round(Math.max(0, horiz ? box.l - seg.l : box.t - seg.t));
      const p2 = Math.round(Math.max(0, horiz ? seg.r - box.r : seg.b - box.b));
      const detail = { text: box.text, edge, gap_px: Math.round(d), at: Math.round(axis) };
      if (Math.max(p1, p2) >= PROTRUDE) detail.protrude_px = [p1, p2];
      add("line_flush_box_edge", seg, box, detail);
    }
  }
  out.line_on_box = [...finds.values()].sort((a, b) => b.count - a.count).slice(0, MAX_FIND);

  // —— 检查二：浮框压住正文 ——
  // 典型成因：想要「文字环绕浮框」却写了 position:absolute。绝对定位脱离文档流，
  // 正文不会为它让出空间，于是文字直接从框底下穿过去。源码里每条声明都合法，
  // 只有渲染出来才看得见 —— 与「线压卡片」是同一类静默失败。
  const covers = new Map();
  for (const p of panels) {
    for (const tr of textRuns) {
      if (p.el.contains(tr.host) || tr.host.contains(p.el)) continue;
      const ox = Math.min(p.r, tr.r) - Math.max(p.l, tr.l);
      const oy = Math.min(p.b, tr.b) - Math.max(p.t, tr.t);
      if (ox < COVER_W || oy < tr.h * COVER_H) continue;
      // 谁在上面：浮框被正文盖住时字看得见，不是缺陷。判据用真实命中测试而不是
      // z-index 比大小 —— 后者对 static 元素无效（z-index 不生效，返回 auto），
      // 跨层叠上下文的 z 值也不能直接比。命中测试把层叠规则、文档序都算在内。
      const cx = (Math.max(p.l, tr.l) + Math.min(p.r, tr.r)) / 2;
      const cy = (Math.max(p.t, tr.t) + Math.min(p.b, tr.b)) / 2;
      const onTop = topIs(cx, cy, p.el, p);
      if (onTop === false) { hiddenCovers++; continue; }
      // 命中测试判不了（重叠区在视口外、或浮框写了 pointer-events:none 使命中穿透）时，
      // 退回原先的保守口径：只在浮框的 z 不低于正文时才报。
      if (onTop === null && p.z < tr.hz) continue;
      const key = p.tag + "|" + label(tr.host);
      let g = covers.get(key);
      if (!g) covers.set(key, (g = { panel: p.tag, over: label(tr.host), pos: p.pos,
                                     count: 0, examples: [] }));
      g.count++;
      if (g.examples.length < 3)
        g.examples.push({ text: tr.text, cover_w: Math.round(ox), cover_h: Math.round(oy),
                          at: [Math.round(Math.max(p.l, tr.l)), Math.round(Math.max(p.t, tr.t))] });
    }
  }
  out.box_over_text = [...covers.values()].sort((a, b) => b.count - a.count).slice(0, MAX_FIND);
  out.counts.hidden_lines = hiddenLines;
  out.counts.hidden_covers = hiddenCovers;
  if (textTrunc) out.truncated = true;

  // —— 检查三：两条装饰线矩形完全重合（同一段线被画了两遍）——
  const seen = new Map(), dup = new Map();
  for (const seg of lines) {
    const k = [Math.round(seg.l), Math.round(seg.t), Math.round(seg.r), Math.round(seg.b)].join(",");
    const prev = seen.get(k);
    if (!prev) { seen.set(k, seg); continue; }
    if (prev.owner === seg.owner) continue;
    const key = [prev.tag, seg.tag].sort().join(" | ");
    const g = dup.get(key) || { a: prev.tag, b: seg.tag, count: 0, examples: [] };
    g.count++;
    if (g.examples.length < 3) g.examples.push({ rect: k });
    dup.set(key, g);
  }
  out.coincident_lines = [...dup.values()].sort((a, b) => b.count - a.count).slice(0, MAX_FIND);
  return out;
};
