/* VeryGood 站点数据组件运行时（v1.4.0）—— 内置插件 site-stats。
   职责：浏览量/访客数（不蒜子多源 + 本地真实计数兜底）、页面加载耗时、访客地区。
   全部 try/catch 包裹，任何失败静默降级，绝不影响页面主流程。 */
(function () {
  'use strict';
  if (!document.getElementById('vg-stats')) return;

  function $(id) { return document.getElementById(id); }
  function fmt(n) {
    n = Math.max(0, Math.floor(n) || 0);
    if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿';
    if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
    return String(n);
  }
  function setText(id, text) {
    var el = $(id);
    if (el) el.textContent = text;
  }

  /* ---------- 1. 浏览量 / 访客数 ----------
     统计源优先级（多级降级，任何一步失败自动切换下一级）：
       ① 不蒜子 icopyright 域名（script 注入 + 轮询 DOM 回填）
       ② 不蒜子 ibruce.info 老域名（JSONP 回调）
       ③ 本地 localStorage 真实计数（PV 每次加载 +1；UV 仅首次访问 +1） */
  var PV_EL = 'vg-stats-pv', UV_EL = 'vg-stats-uv';
  var LOCAL_DONE = false;

  function applyLocal() {
    if (LOCAL_DONE) return;
    LOCAL_DONE = true;
    try {
      var today = new Date().toISOString().slice(0, 10);
      var raw = JSON.parse(localStorage.getItem('vg-stats') || '{}');
      var isNewDay = raw.day !== today;
      if (isNewDay) raw = { day: today, pv: 0, uv: raw.uvAll || raw.uv || 0, seen: false };
      /* PV：每次页面加载 +1（真实点击计数） */
      raw.pv += 1;
      /* UV：首次访问 +1，当日其他页面不再重复计 */
      if (!raw.seen) {
        if (!isNewDay && raw.pv === 1 && raw.uv === 0) raw.uv = 1;
        else if (isNewDay) raw.uv = (typeof raw.uvAll === 'number' ? raw.uvAll : raw.uv) + 1;
        raw.seen = true;
        raw.uvAll = raw.uv;
      }
      localStorage.setItem('vg-stats', JSON.stringify(raw));
      setText(PV_EL, '≈' + fmt(raw.pv));
      setText(UV_EL, '≈' + fmt(raw.uv));
    } catch (e) { /* 忽略 */ }
  }

  /* ① icopyright 域名：脚本注入 + 轮询 busuanzi_value_site_pv/uv */
  function startBusuanziV1() {
    try {
      var s = document.createElement('script');
      s.src = '//busuanzi.icopyright.com/cn/busuanzi.pg';
      s.async = true;
      s.onerror = function () { startBusuanziV2(); };
      document.head.appendChild(s);
      var tries = 0;
      var poll = setInterval(function () {
        tries += 1;
        var pvEl = document.getElementById('busuanzi_value_site_pv');
        var uvEl = document.getElementById('busuanzi_value_site_uv');
        var pv = pvEl && pvEl.textContent.replace(/,/g, '');
        var uv = uvEl && uvEl.textContent.replace(/,/g, '');
        if (pv && /^\d+$/.test(pv)) {
          clearInterval(poll);
          setText(PV_EL, fmt(parseInt(pv, 10)));
          if (uv && /^\d+$/.test(uv)) setText(UV_EL, fmt(parseInt(uv, 10)));
          return;
        }
        if (tries >= 10) { clearInterval(poll); startBusuanziV2(); }
      }, 500);
    } catch (e) { startBusuanziV2(); }
  }

  /* ② ibruce.info 老域名：JSONP 全局回调 */
  function startBusuanziV2() {
    try {
      var cbName = 'vgBusuanziCb_' + Date.now();
      window[cbName] = function (data) {
        try {
          delete window[cbName];
          if (data) {
            var pv = parseInt(String(data.site_pv || data.pv || '').replace(/,/g, ''), 10);
            var uv = parseInt(String(data.site_uv || data.uv || '').replace(/,/g, ''), 10);
            if (pv > 0) setText(PV_EL, fmt(pv));
            if (uv > 0) setText(UV_EL, fmt(uv));
            return;
          }
        } catch (e) { /* 忽略 */ }
        applyLocal();
      };
      var s = document.createElement('script');
      s.src = '//busuanzi.ibruce.info/busuanzi?jsonpCallback=' + cbName;
      s.async = true;
      s.onerror = function () { applyLocal(); };
      document.head.appendChild(s);
      setTimeout(function () { if (window[cbName]) { try { delete window[cbName]; } catch (e) { window[cbName] = function () {}; } applyLocal(); } }, 4000);
    } catch (e) { applyLocal(); }
  }

  /* ---------- 2. 页面加载耗时（导航到可交互） ---------- */
  function fillLoad() {
    try {
      var ms = 0;
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      if (nav && nav.domContentLoadedEventEnd) {
        ms = nav.domContentLoadedEventEnd - nav.startTime;
      } else if (window.performance.timing) {
        ms = window.performance.timing.domContentLoadedEventEnd - window.performance.timing.navigationStart;
      }
      /* 合理性防御：为负数 / 超过 2 分钟的结果一律不展示（个别环境 nav timing 异常） */
      if (!(ms > 0 && ms < 120000)) {
        var t2 = window.performance.timing;
        if (t2 && t2.domContentLoadedEventEnd && t2.navigationStart) {
          ms = t2.domContentLoadedEventEnd - t2.navigationStart;
        }
      }
      setText('vg-stats-load', (ms > 0 && ms < 120000) ? (ms / 1000).toFixed(1) + 's' : '–');
    } catch (e) { /* 忽略 */ }
  }

  /* ---------- 3. 访客地区：Intl 时区推断 + 语言兜底 ---------- */
  var REGIONS = {
    'Asia/Shanghai': '中国', 'Asia/Hong_Kong': '中国香港', 'Asia/Macau': '中国澳门',
    'Asia/Taipei': '中国台湾', 'Asia/Tokyo': '日本', 'Asia/Seoul': '韩国',
    'Asia/Singapore': '新加坡', 'Asia/Kuala_Lumpur': '马来西亚', 'Asia/Bangkok': '泰国',
    'Asia/Jakarta': '印尼', 'Asia/Ho_Chi_Minh': '越南', 'Asia/Manila': '菲律宾',
    'Asia/Kolkata': '印度', 'Asia/Dubai': '阿联酋', 'Asia/Almaty': '哈萨克斯坦',
    'Europe/London': '英国', 'Europe/Paris': '法国', 'Europe/Berlin': '德国',
    'America/New_York': '美国', 'America/Los_Angeles': '美国', 'America/Chicago': '美国',
    'America/Toronto': '加拿大', 'Australia/Sydney': '澳大利亚', 'Pacific/Auckland': '新西兰'
  };
  function fillRegion() {
    try {
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      var name = REGIONS[tz] || (tz ? tz.replace(/_/g, ' ').replace('/', ' · ') : '');
      if (!name) {
        var lang = (navigator.language || 'zh-CN');
        name = lang.indexOf('zh') === 0 ? '中国' : lang;
      }
      setText('vg-stats-region', name);
    } catch (e) { /* 忽略 */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      startBusuanziV1(); fillLoad(); fillRegion();
    });
  } else {
    fillLoad(); fillRegion(); startBusuanziV1();
  }
})();