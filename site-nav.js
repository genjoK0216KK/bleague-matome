/* Accessible mobile menu. Until initialization succeeds, all links stay visible. */
(function () {
  'use strict';
  var header = document.querySelector('.hdr');
  var button = header && header.querySelector('.nav-toggle');
  var nav = header && header.querySelector('#site-navigation');
  if (!button || !nav || !window.matchMedia) return;
  var mobile = window.matchMedia('(max-width: 1023px)');
  var label = button.querySelector('.nav-toggle-label');
  var open = false;
  function setOpen(value, restoreFocus) {
    open = Boolean(value && mobile.matches);
    header.classList.toggle('nav-open', open);
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? 'メニューを閉じる' : 'メニューを開く');
    if (label) label.textContent = open ? '閉じる' : 'メニュー';
    if (restoreFocus) button.focus();
  }
  function addExtra(href, text) {
    var link = document.createElement('a');
    link.href = href;
    link.className = 'menu-extra';
    link.textContent = text;
    nav.appendChild(link);
  }
  addExtra('articles.html', '記事一覧');
  addExtra('about.html', 'このサイトについて');
  addExtra('contact.html', 'お問い合わせ');
  var close = document.createElement('button');
  close.type = 'button';
  close.className = 'menu-close menu-extra';
  close.textContent = 'メニューを閉じる';
  close.addEventListener('click', function () { setOpen(false, true); });
  nav.appendChild(close);
  button.addEventListener('click', function () { setOpen(!open, false); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false, true);
    }
  });
  document.addEventListener('click', function (event) {
    if (open && !header.contains(event.target)) setOpen(false, false);
  });
  // KBD-01: moving focus out of the open menu closes it, so the header never hides the focused link.
  header.addEventListener('focusout', function (event) {
    if (open && event.relatedTarget && !header.contains(event.relatedTarget)) setOpen(false, false);
  });
  nav.addEventListener('click', function (event) {
    if (event.target.closest('a')) setOpen(false, false);
  });
  // A browser may drop focus from a hidden item before the width change reaches us.
  var lastFocus = null;
  nav.addEventListener('focusin', function (event) { lastFocus = event.target; });
  nav.addEventListener('focusout', function (event) { if (event.target.offsetParent) lastFocus = null; });
  function resized() {
    var focused = document.activeElement === document.body ? lastFocus : document.activeElement;
    var inNav = nav.contains(focused);
    lastFocus = null;
    setOpen(false, mobile.matches && inNav);
    // The extra items disappear on wide screens, so focus moves to a link that stays visible.
    if (!mobile.matches && inNav && focused.classList.contains('menu-extra')) nav.querySelector('a').focus();
  }
  if (mobile.addEventListener) mobile.addEventListener('change', resized);
  else mobile.addListener(resized);
  // Only now is it safe to hide the fallback navigation on small screens.
  setOpen(false, false);
  header.classList.add('nav-enhanced');
  button.hidden = false;
})();

/* Skip link and the way back to the article list. */
(function () {
  'use strict';
  var main = document.querySelector('main') || document.querySelector('.wrap');
  if (main) {
    main.id = main.id || 'content';
    main.tabIndex = -1;
    var skip = document.createElement('a');
    skip.className = 'skip-link';
    skip.href = '#' + main.id;
    skip.textContent = '本文へ移動';
    document.body.insertBefore(skip, document.body.firstChild);
  }
  var home = document.querySelector('.article .breadcrumb a');
  if (home && /\/article-[^\/]*$/.test(location.pathname)) {
    var list = document.createElement('a');
    list.href = 'articles.html';
    list.textContent = '記事一覧';
    home.parentNode.insertBefore(list, home.nextSibling);
    home.parentNode.insertBefore(document.createTextNode(' ／ '), list);
  }
})();

/* Tell readers about wide tables only when a table really overflows. */
(function () {
  'use strict';
  function update(wrap) {
    var table = wrap.querySelector('table');
    if (!table) return;
    var hint = wrap.previousElementSibling;
    if (!hint || !hint.classList.contains('table-hint')) {
      hint = document.createElement('p');
      hint.className = 'table-hint';
      hint.hidden = true;
      wrap.parentNode.insertBefore(hint, wrap);
    }
    var over = wrap.scrollWidth > wrap.clientWidth + 1;
    hint.hidden = !over;
    if (!over) return;
    var edge = wrap.getBoundingClientRect().right;
    var hidden = Array.prototype.filter.call(table.rows[0].cells, function (th) {
      return th.getBoundingClientRect().right > edge + 1;
    }).map(function (th) { return th.textContent.trim(); });
    var names = hidden.slice(0, 2).join('・');
    hint.textContent = '表は横にスクロールできます。' + (names ? '右に' + names + (hidden.length > 2 ? 'など' : '') + 'が続きます' : '');
    if (!wrap.hasAttribute('tabindex')) wrap.tabIndex = 0;
    if (!wrap.getAttribute('aria-label')) {
      var caption = table.querySelector('caption');
      wrap.setAttribute('aria-label', caption ? caption.textContent.trim() : '横にスクロールできる表');
      wrap.setAttribute('role', 'region');
    }
  }
  function updateAll() {
    Array.prototype.forEach.call(document.querySelectorAll('.tablewrap'), update);
  }
  var waiting = false;
  window.addEventListener('resize', function () {
    if (waiting) return;
    waiting = true;
    window.requestAnimationFrame(function () { waiting = false; updateAll(); });
  });
  document.addEventListener('toggle', updateAll, true);
  updateAll();
})();
