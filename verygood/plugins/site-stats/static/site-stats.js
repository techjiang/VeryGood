/* VeryGood 站点数据组件运行时（v1.3.0）—— 内置插件 site-stats。
   职责：浏览量/访客数（不蒜子 + localStorage 兜底）、页面加载耗时、访客地区。
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

  /* ---------- 1. 浏览量 / 访客数：不蒜子统计，不可达时本地兜底 ---------- */
  var PV_EL = 'vg-stats-pv', UV_EL = 'vg-stats-uv', DONE = false;
  function applyLocal() {
    if (DONE) return;
    try {
      var today = new Date().toISOString().slice(0, 10);
      var raw = JSON.parse(localStorage.getItem('vg-stats') || '{}');
      if (raw.day !== today) { raw = { day: today, pv: 0, uv: 1, loaded: false }; }
      if (!raw.loaded) { raw.pv += 1; raw.loaded = true; localStorage.setItem('vg-stats', JSON.stringify(raw)); }
      setText(PV_EL, '≈' + fmt(raw.pv));
      setText(UV_EL, '≈' + fmt(raw.uv));
    } catch (e) { /* 忽略 */ }
  }
  function startBusuanzi() {
    try {
      var s = document.createElement('script');
      s.src = '//busuanzi.icopyright.com/cn/busuanzi.pg';
      s.async = true;
      s.onerror = function () { setTimeout(applyLocal, 500); };
      document.head.appendChild(s);
      /* 不蒜子脚本会向 #busuanzi_value_site_pv / #busuanzi_value_site_uv 回填数字，
         轮询最多 5 秒（10 x 500ms），超时用本地兜底。 */
      var tries = 0;
      var poll = setInterval(function () {
        tries += 1;
        var pvEl = document.getElementById('busuanzi_value_site_pv');
        var uvEl = document.getElementById('busuanzi_value_site_uv');
        var pv = pvEl && pvEl.textContent.replace(/,/g, '');
        var uv = uvEl && uvEl.textContent.replace(/,/g, '');
        if (pv && /^\d+$/.test(pv)) {
          clearInterval(poll);
          DONE = true;
          setText(PV_EL, fmt(parseInt(pv, 10)));
          if (uv && /^\d+$/.test(uv)) setText(UV_EL, fmt(parseInt(uv, 10)));
          return;
        }
        if (tries >= 10) { clearInterval(poll); applyLocal(); }
      }, 500);
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
      startBusuanzi(); fillLoad(); fillRegion();
    });
  } else {
    fillLoad(); fillRegion(); startBusuanzi();
  }
})();