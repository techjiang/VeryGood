/* VeryGood Theme · search.js —— 纯前端实时搜索（基于 search.json） */
(function () {
  'use strict';
  var input = document.getElementById('search-input');
  var box = document.getElementById('search-results');
  if (!input || !box) return;

  var index = [];
  var loaded = false;
  var lastTerm = '';

  /* 优先用模板里渲染的绝对地址；否则按 basePath 推导 */
  function indexUrl() {
    var el = document.getElementById('search-index');
    if (el && el.getAttribute('href')) return el.getAttribute('href');
    var p = window.location.pathname;
    var base = p.replace(/\/search\/?$/, '');
    return base + '/search.json';
  }

  function load() {
    if (loaded) return Promise.resolve(index);
    return fetch(indexUrl(), { headers: { 'Accept': 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        index = Array.isArray(data) ? data : ((data && data.posts) ? data.posts : []);
        loaded = true;
        return index;
      })
      .catch(function () {
        box.innerHTML = '<p class="search-results__empty">搜索索引加载失败，请稍后重试。</p>';
        throw new Error('search.json load failed');
      });
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function highlight(text, terms) {
    var t = escapeHtml(text);
    terms.forEach(function (term) {
      var re = new RegExp('(' + term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      t = t.replace(re, '<mark>$1</mark>');
    });
    return t;
  }

  function score(post, terms) {
    var s = 0;
    var title = (post.title || '').toLowerCase();
    var tags = (post.tags || []).join(' ').toLowerCase();
    var sum = (post.summary || '').toLowerCase();
    var cat = (post.category || '').toLowerCase();
    var content = (post.content || '').toLowerCase();
    terms.forEach(function (t) {
      if (title.indexOf(t) > -1) s += 10;
      if (tags.indexOf(t) > -1) s += 6;
      if (cat.indexOf(t) > -1) s += 5;
      if (sum.indexOf(t) > -1) s += 3;
      if (content.indexOf(t) > -1) s += 1;
    });
    return s;
  }

  function render(q) {
    var terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var list = index.slice();
    if (terms.length) {
      list = list.map(function (p) { return { p: p, s: score(p, terms) }; })
        .filter(function (x) { return x.s > 0; })
        .sort(function (a, b) { return b.s - a.s; })
        .map(function (x) { return x.p; });
    }
    if (!list.length) {
      box.innerHTML = '<p class="search-results__empty">没有找到与「' + escapeHtml(q.trim()) + '」相关的内容，换个关键词试试。</p>';
      return;
    }
    var html = '<p class="search-form__hint">共找到 ' + list.length + ' 篇相关文章</p>';
    list.forEach(function (post) {
      var displayed = escapeHtml(post.title);
      if (terms.length) displayed = highlight(post.title, terms);
      var summary = post.summary || '';
      if (summary.length > 120) summary = summary.slice(0, 120) + '…';
      var sumHtml = terms.length ? highlight(summary, terms) : escapeHtml(summary);
      var date = post.date ? '<span>' + escapeHtml(post.date) + '</span>' : '';
      var cat = post.category ? '<span>' + escapeHtml(post.category) + '</span>' : '';
      html += '<a class="search-item" href="' + (post.url || '#') + '">'
        + '<h3 class="search-item__title">' + displayed + '</h3>'
        + '<div class="search-item__meta">' + date + cat + '</div>'
        + (sumHtml ? '<p class="search-item__summary">' + sumHtml + '</p>' : '')
        + '</a>';
    });
    box.innerHTML = html;
  }

  function run() {
    var q = (input.value || '').trim();
    if (q === lastTerm && loaded) return;
    lastTerm = q;
    load().then(function () { render(q); }).catch(function () {});
  }

  var timer = null;
  input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(run, 160);
  });

  /* 支持 ?q= 深链：可分享、可被搜索引擎收录的搜索页 */
  var fromUrl = new URLSearchParams(window.location.search).get('q');
  if (fromUrl) {
    input.value = fromUrl;
    load().then(function () { render(fromUrl); }).catch(function () {});
  }
})();