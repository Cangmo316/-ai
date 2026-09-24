/* ==========================================================================
   比邻AI · App 原型交互
   ========================================================================== */
(function () {
  'use strict';

  var toastEl = document.getElementById('toast');
  var toastTimer = null;
  var callTimerId = null;
  var callSeconds = 42;

  /* ---------------- 提示条 ---------------- */
  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('is-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-show'); }, 1900);
  }

  /* ---------------- 页面切换 ---------------- */
  var TAB_OF = {
    chats: 'chats', empty: 'chats',
    plans: 'plans', calendar: 'plans',
    me: 'me', roles: 'me', face: 'me', tokens: 'me'
  };

  function go(name) {
    var target = document.querySelector('.screen[data-screen="' + name + '"]');
    if (!target) return;

    Array.prototype.forEach.call(document.querySelectorAll('.screen'), function (s) {
      s.classList.remove('is-active');
    });
    target.classList.add('is-active');

    Array.prototype.forEach.call(document.querySelectorAll('.chip[data-jump]'), function (c) {
      c.classList.toggle('is-active', c.getAttribute('data-jump') === name);
    });

    var tab = TAB_OF[name];
    if (tab) {
      Array.prototype.forEach.call(target.querySelectorAll('.tabbar__item'), function (it) {
        it.classList.toggle('is-active', it.getAttribute('data-tab') === tab);
      });
    }

    if (name === 'vision') { startCall(); } else { stopCall(); }
    var scroller = target.querySelector('.screen-body') || target.querySelector('.chat-body');
    if (scroller) scroller.scrollTop = 0;

    if (history.replaceState) history.replaceState(null, '', '#' + name);
  }

  document.addEventListener('click', function (e) {
    var jump = e.target.closest('[data-jump]');
    if (jump) { go(jump.getAttribute('data-jump')); return; }

    var nav = e.target.closest('[data-go]');
    if (nav) { go(nav.getAttribute('data-go')); return; }

    var tabBtn = e.target.closest('.tabbar__item');
    if (tabBtn) { go(tabBtn.getAttribute('data-tab')); return; }

    var toast = e.target.closest('[data-toast]');
    if (toast) { showToast(toast.getAttribute('data-toast')); return; }
  });

  /* ---------------- 通话计时 ---------------- */
  var timerEl = document.getElementById('callTimer');
  function fmt(s) {
    var m = Math.floor(s / 60), r = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }
  function startCall() {
    callSeconds = 42;
    if (timerEl) timerEl.textContent = '通话中 ' + fmt(callSeconds);
    stopCall();
    callTimerId = setInterval(function () {
      callSeconds += 1;
      if (timerEl) timerEl.textContent = '通话中 ' + fmt(callSeconds);
    }, 1000);
  }
  function stopCall() {
    if (callTimerId) { clearInterval(callTimerId); callTimerId = null; }
  }

  Array.prototype.forEach.call(document.querySelectorAll('.call-btn:not(.call-btn--hangup)'), function (btn) {
    btn.addEventListener('click', function () {
      var on = btn.classList.toggle('is-off');
      var use = btn.querySelector('use');
      var isMic = btn.id === 'muteBtn';
      if (use) use.setAttribute('href', on ? (isMic ? '#i-muted' : '#i-muted') : (isMic ? '#i-mic' : '#i-speaker'));
      showToast(on ? (isMic ? '已静音' : '已关闭扬声器') : (isMic ? '麦克风已开' : '扬声器已开'));
    });
  });

  /* ---------------- 表情面板 ---------------- */
  var emojiPanel = document.getElementById('emojiPanel');
  var emojiBtn = document.getElementById('emojiBtn');
  var composerInput = document.querySelector('.composer__input');

  if (emojiBtn && emojiPanel) {
    emojiBtn.addEventListener('click', function () {
      var open = emojiPanel.classList.toggle('is-open');
      emojiBtn.style.color = open ? 'var(--color-primary)' : '';
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll('.emoji'), function (btn) {
    btn.addEventListener('click', function () {
      var ch = btn.getAttribute('data-emoji') || '';
      if (composerInput) composerInput.value = (composerInput.value || '') + ch;
      showToast('已插入表情 ' + ch + '（原型演示）');
    });
  });

  /* ---------------- 大字体模式 ---------------- */
  var largeToggle = document.getElementById('largeToggle');
  var largeSwitch = document.getElementById('largeSwitch');

  function setLarge(on) {
    document.body.classList.toggle('large-mode', on);
    if (largeToggle) {
      largeToggle.classList.toggle('is-on', on);
      largeToggle.textContent = on ? '大字体模式：开' : '大字体模式';
    }
    if (largeSwitch) largeSwitch.classList.toggle('is-on', on);
  }
  if (largeToggle) largeToggle.addEventListener('click', function () {
    var on = !document.body.classList.contains('large-mode');
    setLarge(on);
    showToast(on ? '已切换大字体模式（正文 20px）' : '已切回标准字号');
  });
  if (largeSwitch) largeSwitch.addEventListener('click', function () {
    var on = !document.body.classList.contains('large-mode');
    setLarge(on);
    showToast(on ? '已开启大字体模式' : '已关闭大字体模式');
  });

  /* ---------------- 日历 ---------------- */
  function buildCalendar() {
    var grid = document.getElementById('calGrid');
    if (!grid) return;
    var YEAR = 2026, MONTH = 9, TODAY = 23, DAYS = 30;
    // 2026-09-01 是周二（周一为一周起点 → 前面空 1 格）
    var LEAD = 1;
    var MARKED = [3, 5, 8, 11, 15, 18, 22, 23, 26, 29];
    var html = '';
    var i;
    for (i = 0; i < LEAD; i++) html += '<span class="cal__day is-mute">' + (31 - LEAD + 1 + i) + '</span>';
    for (i = 1; i <= DAYS; i++) {
      var cls = 'cal__day';
      if (MARKED.indexOf(i) !== -1) cls += ' is-marked';
      if (i === TODAY) cls += ' is-today';
      html += '<button class="' + cls + '" data-day="' + i + '">' + i + '</button>';
    }
    var filled = LEAD + DAYS;
    var tail = (7 - (filled % 7)) % 7;
    for (i = 1; i <= tail; i++) html += '<span class="cal__day is-mute">' + i + '</span>';
    grid.innerHTML = html;

    grid.addEventListener('click', function (e) {
      var day = e.target.closest('[data-day]');
      if (!day) return;
      var d = day.getAttribute('data-day');
      var has = MARKED.indexOf(Number(d)) !== -1;
      showToast('9月' + d + '日 · ' + (has ? '有 ' + (d === '23' ? '4' : '2') + ' 项计划' : '暂无计划'));
    });
  }
  buildCalendar();

  /* ---------------- 3D 捏脸 ---------------- */
  var FACE_PARAMS = [
    { key: 'face',    name: '脸型',  value: 50 },
    { key: 'eye',     name: '眼睛',  value: 55 },
    { key: 'nose',    name: '鼻子',  value: 45 },
    { key: 'mouth',   name: '嘴巴',  value: 50 },
    { key: 'hair',    name: '发型',  value: 60 },
    { key: 'skin',    name: '肤色',  value: 52 },
    { key: 'age',     name: '年龄感', value: 58 },
    { key: 'outfit',  name: '服饰',  value: 48 }
  ];

  function buildSliders() {
    var wrap = document.getElementById('faceControls');
    if (!wrap) return;
    var html = '';
    FACE_PARAMS.forEach(function (p) {
      html += '<div class="slider-row">'
        + '<div class="slider-row__top">'
        + '<span class="slider-row__name">' + p.name + '</span>'
        + '<span class="slider-row__value" data-value="' + p.key + '">' + p.value + '</span>'
        + '</div>'
        + '<input class="slider" type="range" min="0" max="100" value="' + p.value + '" data-param="' + p.key + '" aria-label="' + p.name + '">'
        + '</div>';
    });
    wrap.innerHTML = html;

    Array.prototype.forEach.call(wrap.querySelectorAll('.slider'), function (slider) {
      paintTrack(slider);
      slider.addEventListener('input', function () {
        var key = slider.getAttribute('data-param');
        var val = Number(slider.value);
        var out = wrap.querySelector('[data-value="' + key + '"]');
        if (out) out.textContent = val;
        paintTrack(slider);
        applyFace(key, val);
      });
    });
    applyFaceAll();
  }

  function paintTrack(slider) {
    var pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
    slider.style.setProperty('--pct', pct + '%');
  }

  function preview() {
    var el = document.querySelector('.face-preview');
    if (!el) return {
      head: null, hair: null, torso: null
    };
    return {
      head: el.querySelector('.face-model__head'),
      hair: el.querySelector('.face-model__hair'),
      torso: el.querySelector('.face-model__torso')
    };
  }

  function values() {
    var v = {};
    FACE_PARAMS.forEach(function (p) { v[p.key] = p.value; });
    return v;
  }

  function applyFace(key, val) {
    var store = values();
    store[key] = val;
    var p = preview();
    if (!p.head) return;

    // 脸型：宽高比例
    var w = 88 + (store.face / 100) * 22;
    p.head.style.width = w + 'px';
    p.head.style.height = (104 + (store.face / 100) * 18) + 'px';
    p.head.style.borderRadius = (store.face > 55 ? '48% 48% 46% 46%' : '44% 44% 42% 42%');

    // 肤色：hsl 明度/饱和度
    var hue = 26 + (store.skin / 100) * 6;
    var light = 68 + (store.skin / 100) * 14;
    var sat = 38 + (store.age / 100) * 12;
    p.head.style.background = 'linear-gradient(180deg, hsl(' + hue + ' ' + sat + '% ' + light + '%) 0%, hsl(' + hue + ' ' + sat + '% ' + (light - 8) + '%) 100%)';

    // 发型：高度 + 灰白程度（年龄感）
    p.hair.style.height = (34 + (store.hair / 100) * 26) + 'px';
    var gray = Math.min(90, store.age * 1.15);
    p.hair.style.background = 'hsl(30 ' + Math.max(6, 26 - gray / 5) + '% ' + (16 + gray / 1.6) + '%)';

    // 服饰
    var o = store.outfit / 100;
    p.torso.style.background = 'linear-gradient(180deg, hsl(' + (200 + o * 40) + ' 42% ' + (78 - o * 22) + '%) 0%, hsl(' + (200 + o * 40) + ' 38% ' + (68 - o * 22) + '%) 100%)';
  }

  function applyFaceAll() {
    var store = values();
    Object.keys(store).forEach(function (k) { applyFace(k, store[k]); });
  }

  function randomize() {
    var wrap = document.getElementById('faceControls');
    if (!wrap) return;
    Array.prototype.forEach.call(wrap.querySelectorAll('.slider'), function (slider) {
      var v = Math.round(15 + Math.random() * 70);
      slider.value = v;
      paintTrack(slider);
      var out = wrap.querySelector('[data-value="' + slider.getAttribute('data-param') + '"]');
      if (out) out.textContent = v;
      applyFace(slider.getAttribute('data-param'), v);
    });
    showToast('已随机生成一个新形象');
  }

  var randomBtn = document.getElementById('randomBtn');
  if (randomBtn) randomBtn.addEventListener('click', randomize);
  buildSliders();

  /* ---------------- 角色选择 ---------------- */
  var roleList = document.getElementById('roleList');
  if (roleList) {
    roleList.addEventListener('click', function (e) {
      var card = e.target.closest('.role-card');
      if (!card) return;
      Array.prototype.forEach.call(roleList.querySelectorAll('.role-card'), function (c) {
        c.classList.remove('is-selected');
      });
      card.classList.add('is-selected');
      var name = card.getAttribute('data-role');
      var out = document.getElementById('roleValue');
      if (out) out.textContent = name;
      showToast('已选择：' + name);
    });
  }

  /* ---------------- 初始化（支持 #hash 深链 与 ?large=1） ---------------- */
  if (/[?&]large=1/.test(location.search)) { setLarge(true); }
  var initial = (location.hash || '').replace('#', '');
  if (!document.querySelector('.screen[data-screen="' + initial + '"]')) { initial = 'splash'; }
  go(initial);

  window.addEventListener('hashchange', function () {
    var h = (location.hash || '').replace('#', '');
    if (document.querySelector('.screen[data-screen="' + h + '"]')) { go(h); }
  });
})();