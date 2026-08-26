/* VeryGood 内置插件 whisper：时间卡片秒级刷新 + 微语打字机轮播（v1.4.0） */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  var WEEK = ["日", "一", "二", "三", "四", "五", "六"];

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  /* ---- 时钟 ---- */
  function tickClock() {
    var h = document.getElementById("vg-clock-h");
    var m = document.getElementById("vg-clock-m");
    var s = document.getElementById("vg-clock-s");
    var d = document.getElementById("vg-clock-date");
    if (!h || !m || !s || !d) return;
    var now = new Date();
    h.textContent = pad(now.getHours());
    m.textContent = pad(now.getMinutes());
    s.textContent = pad(now.getSeconds());
    d.textContent = now.getFullYear() + "年" + (now.getMonth() + 1) + "月" + now.getDate() + "日" + " · 星期" + WEEK[now.getDay()];
  }
  if (document.getElementById("vg-clock-h")) {
    tickClock();
    setInterval(tickClock, 1000);
  }

  /* ---- 微语打字机 ---- */
  var dataEl = document.getElementById("vg-whisper-data");
  var textEl = document.getElementById("vg-whisper-text");
  var pauseBtn = document.getElementById("vg-whisper-pause");
  var idxEl = document.getElementById("vg-whisper-idx");
  if (dataEl && textEl) {
    var notes = [];
    try {
      notes = JSON.parse(dataEl.textContent || "[]");
    } catch (e) {
      /* 兼容旧产物：实体形式 &quot; 不会被 raw text 反转义，手动画回去再试一次 */
      try { notes = JSON.parse((dataEl.textContent || "[]").replace(/&quot;/g, '"').replace(/&#34;/g, '"').replace(/&amp;/g, '&')); }
      catch (e2) { notes = []; }
    }
    notes = notes.filter(function (n) { return typeof n === "string" && n.trim(); });
    if (notes.length) {
      var TYPE_MS = 90;      // 每字间隔
      var HOLD_MS = 2600;    // 打完停留
      var ERASE_MS = 40;     // 删除间隔
      var ci = 0, pos = 0, deleting = false, paused = false, timer = null;

      function renderIdx() { if (idxEl) idxEl.textContent = (ci + 1) + "/" + notes.length; }

      function step() {
        if (paused) return;
        var txt = notes[ci];
        if (!deleting) {
          pos += 1;
          textEl.textContent = txt.slice(0, pos);
          if (pos >= txt.length) {
            deleting = true;
            timer = setTimeout(step, HOLD_MS);
            return;
          }
        } else {
          pos -= 1;
          textEl.textContent = txt.slice(0, pos);
          if (pos <= 0) {
            ci = (ci + 1) % notes.length;
            renderIdx();
            deleting = false;
            pos = 0;
            timer = setTimeout(step, 420);
            return;
          }
        }
        timer = setTimeout(step, deleting ? ERASE_MS : TYPE_MS);
      }

      renderIdx();
      timer = setTimeout(step, 500);

      if (pauseBtn) {
        pauseBtn.addEventListener("click", function () {
          paused = !paused;
          pauseBtn.textContent = paused ? "继续" : "暂停";
          if (!paused) { clearTimeout(timer); timer = setTimeout(step, 60); }
        });
      }
    } else if (idxEl) {
      idxEl.textContent = "";
    }
  }
})();