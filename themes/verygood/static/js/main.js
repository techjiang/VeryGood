/* VeryGood Theme · main.js (v1.1) */
(function () {
  'use strict';
  var doc = document;
  var root = doc.documentElement;
  root.classList.add('js');

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

  /* ---------- 公告条：关闭后记忆（v1.1） ---------- */
  var ann = doc.getElementById('announcement');
  var annClose = doc.getElementById('announcement-close');
  if (ann && annClose) {
    try {
      if (localStorage.getItem('vg-ann-close') === '1') ann.remove();
    } catch (e) { ann.remove(); }
    annClose.addEventListener('click', function () {
      try { localStorage.setItem('vg-ann-close', '1'); } catch (e) {}
      ann.style.height = ann.offsetHeight + 'px';
      ann.style.overflow = 'hidden';
      requestAnimationFrame(function () {
        ann.style.height = '0px';
        ann.style.padding = '0';
        ann.style.transition = 'height 0.3s ease, padding 0.3s ease';
      });
      setTimeout(function () { ann.remove(); }, 320);
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

  /* ---------- 图片 / 视频灯箱（v1.1） ---------- */
  var lightbox = doc.getElementById('lightbox');
  if (lightbox) {
    var stage = doc.getElementById('lightbox-stage');
    var lbClose = doc.getElementById('lightbox-close');
    var lbOpen = false;
    function openLightbox(node) {
      stage.innerHTML = '';
      stage.appendChild(node);
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
        lbOpen = false;
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
    /* 灯箱内图片滚动缩放（省）×：直接关闭 */
  }

  /* ---------- 代码块复制按钮 ---------- */
  var copySvg = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var checkSvg = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  doc.querySelectorAll('.md-body pre').forEach(function (pre) {
    var code = pre.querySelector('code');
    if (!code) return;
    var btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'code-copy';
    btn.setAttribute('aria-label', '复制代码');
    btn.title = '复制代码';
    btn.innerHTML = copySvg + '<span>复制</span>';
    pre.appendChild(btn);
    btn.addEventListener('click', function () {
      var text = code.innerText;
      function done() {
        btn.classList.add('is-copied');
        btn.innerHTML = checkSvg + '<span>已复制</span>';
        setTimeout(function () {
          btn.classList.remove('is-copied');
          btn.innerHTML = copySvg + '<span>复制</span>';
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

})();
