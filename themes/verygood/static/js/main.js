/* VeryGood Theme · main.js (v1.5.0) */
(function () {
  'use strict';
var doc = document;
  var root = doc.documentElement;
  root.classList.add('js');

  /* ---------- 顶栏高度实测（v1.2.0：移动端 fixed 顶栏占位） ---------- */
  var headerEl = doc.querySelector('.site-header');
  var mqMobile = window.matchMedia ? window.matchMedia('(max-width: 860px)') : null;
  function syncHeaderH() {
    if (!headerEl || !mqMobile || !mqMobile.matches) return;
    root.style.setProperty('--vg-header-h', (headerEl.offsetHeight || 64) + 'px');
  }
  if (headerEl && mqMobile) {
    syncHeaderH();
    var hTimer = null;
    function hSchedule() { clearTimeout(hTimer); hTimer = setTimeout(syncHeaderH, 60); }
    if (mqMobile.addEventListener) { mqMobile.addEventListener('change', hSchedule); }
    else if (mqMobile.addListener) { mqMobile.addListener(hSchedule); }
    window.addEventListener('resize', hSchedule);
  }

  /* ---------- 深浅色切换 ---------- */
  var themeBtn = doc.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('vg-theme', next); } catch (e) {}
    });
  }

  /* ---------- 移动端菜单 ---------- */
  var nav = doc.getElementById('site-nav');
  var navBtn = doc.getElementById('nav-toggle');
  if (nav && navBtn) {
    navBtn.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      navBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      navBtn.setAttribute('aria-label', open ? '收起菜单' : '展开菜单');
    });
    doc.addEventListener('click', function (e) {
      if (nav.classList.contains('is-open') && !nav.contains(e.target) && e.target !== navBtn) {
        nav.classList.remove('is-open');
        navBtn.setAttribute('aria-expanded', 'false');
        navBtn.setAttribute('aria-label', '展开菜单');
      }
    });
  }

/* ---------- 公告弹窗：进入页面弹出，关闭后记忆（v1.1.6） ---------- */
  var ann = doc.getElementById('announcement');
  var annClose = doc.getElementById('announcement-close');
  if (ann && annClose) {
    var annDismissed = false;
    try { annDismissed = localStorage.getItem('vg-ann-close') === '1'; } catch (e) {}
    if (!annDismissed) {
      setTimeout(function () { ann.hidden = false; }, 900);
    }
    var annLeaving = false;
    function dismissAnn() {
      if (annLeaving) return;
      annLeaving = true;
      try { localStorage.setItem('vg-ann-close', '1'); } catch (e) {}
      ann.classList.add('is-leaving');
      setTimeout(function () { ann.hidden = true; }, 280);
    }
    annClose.addEventListener('click', dismissAnn);
    ann.addEventListener('click', function (e) {
      if (e.target.closest('.announcement-modal__card')) return;
      dismissAnn();
    });
    doc.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !ann.hidden) dismissAnn();
    });
  }

  /* ---------- 侧栏折叠模块状态记忆（v1.1） ---------- */
  var sideBlocks = doc.querySelectorAll('.side-block');
  sideBlocks.forEach(function (blk) {
    var key = 'vg-side-block:' + (blk.querySelector('.side-block__title') || {}).textContent;
    var saved = null;
    try { saved = localStorage.getItem(key); } catch (e) {}
    if (saved === 'closed') blk.removeAttribute('open');
    if (saved === 'open') blk.setAttribute('open', '');
    blk.addEventListener('toggle', function () {
      try { localStorage.setItem(key, blk.open ? 'open' : 'closed'); } catch (e) {}
    });
  });

  /* ---------- 滚动：头部阴影 / 阅读进度 / 环形回顶（v1.1） ---------- */
  var header = doc.getElementById('site-header');
  var progress = doc.getElementById('progress-bar');
  var toTop = doc.getElementById('back-to-top');
  var ringProg = doc.getElementById('back-to-top__prog');
  var pctEl = doc.getElementById('back-to-top__pct');
/* 圆环周长：r=20 → 2πr≈125.66 */
  var RING_LEN = 125.66;
  function onScroll() {
    var y = window.pageYOffset || doc.documentElement.scrollTop || 0;
    var h = doc.documentElement.scrollHeight - window.innerHeight;
    var pct = h > 0 ? Math.min(100, Math.max(0, (y / h) * 100)) : 0;
    if (header) header.classList.toggle('is-scrolled', y > 8);
    if (progress) progress.style.width = pct + '%';
    if (toTop) toTop.classList.toggle('is-visible', y > 480);
    /* 接近页面底部时上移回顶按钮，避免压住页脚署名等底部内容 */
    if (toTop) toTop.classList.toggle('is-at-bottom', (y + window.innerHeight) >= (doc.documentElement.scrollHeight - 200));
    if (ringProg) ringProg.style.strokeDashoffset = (RING_LEN * (1 - pct / 100)).toFixed(1);
    if (pctEl) pctEl.textContent = Math.round(pct) + '%';
  }
  /* 滚动监听：浏览器按帧派发 scroll（passive 下开销极小），直接执行不丢帧 */
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  onScroll();
  if (toTop) {
    toTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

/* ---------- 图片 / 视频灯箱（v1.1 基础；v1.1.8：缩放 / 旋转 / 下载 / 全屏） ---------- */
  var lightbox = doc.getElementById('lightbox');
  if (lightbox) {
    var stage = doc.getElementById('lightbox-stage');
    var lbClose = doc.getElementById('lightbox-close');
    var lbToolbar = doc.getElementById('lightbox-toolbar');
    var lbZoomLabel = doc.getElementById('lightbox-zoom');
    var lbOpen = false;
    var lbScale = 1, lbRotate = 0, lbMedia = null;
    function applyTransform() {
      if (!lbMedia) return;
      lbMedia.style.transform = 'scale(' + lbScale + ') rotate(' + lbRotate + 'deg)';
      if (lbZoomLabel) lbZoomLabel.textContent = Math.round(lbScale * 100) + '%';
    }
    function resetTransform() { lbScale = 1; lbRotate = 0; applyTransform(); }
    function openLightbox(node) {
      stage.innerHTML = '';
      stage.appendChild(node);
      lbMedia = null;
      /* 找出 stage 内的媒体元素（img / video），作为缩放旋转的变换对象 */
      if (node && node.tagName === 'IMG' || node && node.tagName === 'VIDEO') lbMedia = node;
      else if (node) {
        var m = node.querySelector('img, video');
        if (m) lbMedia = m;
      }
      if (lbToolbar) lbToolbar.removeAttribute('hidden');
      resetTransform();
      lightbox.removeAttribute('hidden');
      requestAnimationFrame(function () { lightbox.classList.add('is-open'); });
      lbOpen = true;
      doc.body.style.overflow = 'hidden';
    }
    function closeLightbox() {
      if (!lbOpen) return;
      lightbox.classList.remove('is-open');
      setTimeout(function () {
        lightbox.setAttribute('hidden', '');
        stage.innerHTML = '';
        lbOpen = false; lbMedia = null;
        if (lbToolbar) lbToolbar.setAttribute('hidden', '');
        doc.body.style.overflow = '';
      }, 260);
    }
    function makeImg(src, alt) {
      var img = doc.createElement('img');
      img.src = src;
      img.alt = alt || '';
      img.loading = 'eager';
      return img;
    }
    /* 点正文图片 → 灯箱放大（不在链接内的、非懒加载占位会显示） */
    doc.querySelectorAll('.md-body img, .moment__body img').forEach(function (img) {
      var wrap = img.closest('a[href]');
      if (wrap) {
        /* 链接指向同一张图时也进灯箱，否则保持默认跳转 */
        var href = wrap.getAttribute('href') || '';
        if (href === img.getAttribute('src')) {
          wrap.addEventListener('click', function (e) {
            e.preventDefault();
            openLightbox(makeImg(img.getAttribute('src'), img.getAttribute('alt')));
          });
        }
        return;
      }
      img.addEventListener('click', function () {
        openLightbox(makeImg(img.getAttribute('src'), img.getAttribute('alt')));
      });
      img.style.cursor = 'zoom-in';
    });
    /* 正文视频 → 灯箱大屏播放 */
    doc.querySelectorAll('.md-body video, .moment__body video').forEach(function (v) {
      v.addEventListener('click', function () {
        var clone = doc.createElement('video');
        clone.controls = true;
        clone.autoplay = true;
        clone.src = v.currentSrc || v.querySelector('source') && v.querySelector('source').src || v.getAttribute('src') || '';
        if (v.poster && v.poster !== 'null') clone.poster = v.poster;
        clone.setAttribute('playsinline', '');
        openLightbox(clone);
      });
    });
if (lbClose) lbClose.addEventListener('click', closeLightbox);
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox || e.target === stage) closeLightbox();
    });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && lbOpen) closeLightbox();
    });

    /* ---- v1.1.8：缩放手势 / 工具栏 ---- */
    function clampScale(v) { return Math.min(6, Math.max(0.2, v)); }
    /* 双击切换 100% / 200% */
    stage.addEventListener('dblclick', function () {
      lbScale = lbScale > 1.01 ? 1 : 2;
      applyTransform();
    });
    /* 滚轮缩放 */
    stage.addEventListener('wheel', function (e) {
      if (!lbOpen) return;
      e.preventDefault();
      lbScale = clampScale(lbScale + (e.deltaY < 0 ? 0.15 : -0.15));
      applyTransform();
    }, { passive: false });
    if (lbToolbar) {
      lbToolbar.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-lb]');
        if (!btn) return;
        var act = btn.getAttribute('data-lb');
        if (act === 'zoom-in') { lbScale = clampScale(lbScale * 1.25); applyTransform(); }
        else if (act === 'zoom-out') { lbScale = clampScale(lbScale / 1.25); applyTransform(); }
        else if (act === 'rotate') { lbRotate = (lbRotate + 90) % 360; applyTransform(); }
        else if (act === 'fullscreen') {
          if (doc.fullscreenElement) { doc.exitFullscreen && doc.exitFullscreen(); }
          else { lightbox.requestFullscreen && lightbox.requestFullscreen(); }
        }
        else if (act === 'download') {
          var src = lbMedia && (lbMedia.currentSrc || lbMedia.src);
          if (!src) return;
          var a = doc.createElement('a');
          a.href = src;
          a.download = (lbMedia && lbMedia.alt ? lbMedia.alt : 'verygood') + '.jpg';
          doc.body.appendChild(a);
          a.click();
          doc.body.removeChild(a);
        }
      });
    }
    /* 初始化时隐藏工具栏的下载按钮（仅图片可下载更合理，但保持简单：统一显示） */
    /* 灯箱内图片滚动缩放（省）×：已实现滚轮缩放 */
  }

/* ---------- 代码块：语言徽标 + 图标复制按钮（v1.4.0） ---------- */
  var copySvg = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var checkSvg = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  doc.querySelectorAll('.md-body pre').forEach(function (pre) {
    var code = pre.querySelector('code');
    if (!code) return;
    /* 语言徽标：优先取渲染器输出的 data-lang，JS 兜底从 wrapper 类名提取 */
    var hl = pre.closest('.highlight');
    var lang = (hl && hl.getAttribute('data-lang')) || '';
    if (!lang && hl) {
      var m = /(?:^|\s)language-([\w-]+)/.exec(hl.className);
      if (m) lang = m[1];
    }
    if (lang) {
      var badge = doc.createElement('span');
      badge.className = 'code-lang';
      badge.textContent = lang;
      pre.appendChild(badge);
    }
    var btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'code-copy';
    btn.setAttribute('aria-label', '复制代码');
    btn.title = '复制代码';
    btn.innerHTML = copySvg;
    pre.appendChild(btn);
    btn.addEventListener('click', function () {
      var text = code.innerText;
      function done() {
        btn.classList.add('is-copied');
        btn.setAttribute('aria-label', '已复制');
        btn.title = '已复制';
        btn.innerHTML = checkSvg;
        setTimeout(function () {
          btn.classList.remove('is-copied');
          btn.setAttribute('aria-label', '复制代码');
          btn.title = '复制代码';
          btn.innerHTML = copySvg;
        }, 1800);
      }
      function fallbackCopy() {
        var ta = doc.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        doc.body.appendChild(ta);
        ta.select();
        try { doc.execCommand('copy'); done(); } catch (e) {}
        doc.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallbackCopy);
      } else {
        fallbackCopy();
      }
    });
  });

  /* ---------- 正文外链新标签页打开（站内/锚点链接保持直跳） ---------- */
  doc.querySelectorAll('.md-body a[href], .moment__body a[href]').forEach(function (a) {
    var href = a.getAttribute('href') || '';
    if (/^https?:|^\/\//i.test(href)) {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener nofollow');
    }
  });

  /* ---------- 入场动效 ---------- */
  var revealEls = doc.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.06, rootMargin: '0px 0px -4% 0px' });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('is-in'); });
  }

  /* ---------- 目录滚动高亮 ---------- */
  var tocLinks = doc.querySelectorAll('.post-toc__list a');
  if (tocLinks.length) {
    var heads = [];
    tocLinks.forEach(function (a) {
      var id = a.getAttribute('href').slice(1);
      if (id) heads.push(doc.getElementById(id));
    });
    heads = heads.filter(Boolean);
function spy() {
      var pos = (window.pageYOffset || 0) + 140;
      var current = null;
      for (var i = 0; i < heads.length; i++) {
        if (heads[i].offsetTop <= pos) current = heads[i].getAttribute('id');
      }
      tocLinks.forEach(function (a) {
        a.classList.toggle('is-active', a.getAttribute('href') === '#' + current);
      });
    }
    var spyTick = false;
    function requestSpy() {
      if (spyTick) return;
      spyTick = true;
      requestAnimationFrame(function () {
        spyTick = false;
        spy();
      });
    }
window.addEventListener('scroll', requestSpy, { passive: true });
    spy();
  }

  /* ---------- v1.1.7：文章分享 - 复制链接 ---------- */
  var copyBtns = doc.querySelectorAll('.post-share__copy');
  copyBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var url = btn.getAttribute('data-copy-url') || location.href;
      function done() {
        btn.classList.add('is-copied');
        setTimeout(function () { btn.classList.remove('is-copied'); }, 1600);
      }
      function fallbackCopy() {
        var ta = doc.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        doc.body.appendChild(ta);
        ta.select();
        try { doc.execCommand('copy'); done(); } catch (e) { /* 忽略 */ }
        doc.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, fallbackCopy);
      } else {
        fallbackCopy();
      }
    });
  });

  /* ---------- v1.5.0：署名三层防线之客户端守卫 ----------
   * 第一层：builder.py 构建期字符级 + 双指纹校验（部署即失败）
   * 第二层：base.html 内联 footer JS 守卫（DOM 级删除/替换检测）
   * 第三层（本段）：全局 body MutationObserver
   *   监控整个 <body> 的 childList 变化，一旦 footer 被删除/替换/清空，
   *   立即重建署名并恢复 footer 结构，确保署名在任何情况下都可见。
   */
  var VG_FOOTER_SIGNATURE = 'Powered by TechSauce & VeryGood';
  function vgFindFooter() {
    return doc.querySelector('.site-footer') || doc.getElementById('site-footer') || doc.querySelector('footer');
  }
  function vgCheckAndRestoreFooter() {
    var ft = vgFindFooter();
    if (!ft) {
      /* footer 整个被删——重建一个最小署名 footer */
      ft = doc.createElement('footer');
      ft.className = 'site-footer';
      ft.id = 'site-footer';
      var p = doc.createElement('p');
      p.className = 'vg-signature';
      p.innerHTML = 'Powered by <a href="https://github.com/TechSauce/VeryGood" rel="noopener" target="_blank">TechSauce</a> &amp; <a href="https://github.com/TechSauce/VeryGood" rel="noopener" target="_blank">VeryGood</a>';
      ft.appendChild(p);
      doc.body.appendChild(ft);
      return;
    }
    var sig = ft.querySelector('.vg-signature') || ft.querySelector('p');
    if (!sig || ft.textContent.indexOf('TechSauce') === -1 || ft.textContent.indexOf('VeryGood') === -1) {
      /* 署名被篡改或清空——重建 */
      ft.innerHTML = '';
      var sp = doc.createElement('p');
      sp.className = 'vg-signature';
      sp.innerHTML = 'Powered by <a href="https://github.com/TechSauce/VeryGood" rel="noopener" target="_blank">TechSauce</a> &amp; <a href="https://github.com/TechSauce/VeryGood" rel="noopener" target="_blank">VeryGood</a>';
      ft.appendChild(sp);
    }
  }
  if (typeof MutationObserver !== 'undefined') {
    var vgObserver = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        if (mutations[i].type === 'childList') {
          var removed = mutations[i].removedNodes;
          for (var j = 0; j < removed.length; j++) {
            var node = removed[j];
            if (node && (node.nodeType === 1) &&
                ((node.classList && node.classList.contains('site-footer')) ||
                 (node.id === 'site-footer') ||
                 (node.tagName === 'FOOTER') ||
                 (node.querySelector && node.querySelector('.vg-signature')))) {
              vgCheckAndRestoreFooter();
              return;
            }
          }
        }
      }
    });
    vgObserver.observe(doc.body, { childList: true, subtree: true });
    /* 首次检查 */
    vgCheckAndRestoreFooter();
  }

})();
